#!/usr/bin/env python3
"""
Astrometry Server Console - 本地控制台客户端
连接到服务器端 agent，以 root 权限远程控制服务器

功能：
- 执行任意 shell 命令（普通 / 流式）
- 上传/下载文件（带 SHA-256 完整性校验）
- 管理索引文件
- 部署/更新服务器代码
- 交互式 REPL
- 配置文件管理（~/.astrometry/console.conf）

用法：
    python local_console.py                          # 首次运行引导配置
    python local_console.py --exec "ls /usr/local/astrometry/data"
    python local_console.py --stream "long_running_command"
"""

from __future__ import annotations

import os
import sys
import json
import time
import hmac
import hashlib
import socket
import struct
import base64
import argparse
from pathlib import Path

import config_manager

# ==================== 配置 ====================

CLIENT_CONFIG_PATH = config_manager.CLIENT_CONFIG_PATH
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 9999
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB


# ==================== 加密通道（与 server_agent.py 对应） ====================

class CryptoChannel:
    """AES-256-CBC 加密通信通道（强制使用 cryptography，无降级）"""

    def __init__(self, conn: socket.socket, key: bytes):
        self.conn = conn
        self.key = key
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            self._Cipher = Cipher
            self._algorithms = algorithms
            self._modes = modes
            self._backend = default_backend()
        except ImportError:
            print('[FATAL] cryptography 库未安装，请运行: pip install cryptography')
            sys.exit(1)

    def _encrypt(self, plaintext: bytes) -> bytes:
        iv = os.urandom(16)
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        cipher = self._Cipher(
            self._algorithms.AES(self.key),
            self._modes.CBC(iv),
            backend=self._backend,
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return iv + ciphertext

    def _decrypt(self, data: bytes) -> bytes:
        iv = data[:16]
        ciphertext = data[16:]
        cipher = self._Cipher(
            self._algorithms.AES(self.key),
            self._modes.CBC(iv),
            backend=self._backend,
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = padded[-1]
        return padded[:-pad_len]

    def send_message(self, obj: dict) -> bool:
        try:
            plaintext = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            encrypted = self._encrypt(plaintext)
            header = struct.pack('>I', len(encrypted))
            self.conn.sendall(header + encrypted)
            return True
        except Exception as e:
            print(f'[发送错误] {e}')
            return False

    def recv_message(self) -> dict | None:
        try:
            header = self._recv_exact(4)
            if not header:
                return None
            length = struct.unpack('>I', header)[0]
            if length > 100 * 1024 * 1024:
                print(f'[接收错误] 消息过大: {length}')
                return None
            data = self._recv_exact(length)
            if not data:
                return None
            plaintext = self._decrypt(data)
            return json.loads(plaintext.decode('utf-8'))
        except Exception as e:
            print(f'[接收错误] {e}')
            return None

    def _recv_exact(self, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = self.conn.recv(n - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except socket.timeout:
                return None
            except Exception as e:
                print(f'[接收错误] {e}')
                return None
        return bytes(buf)


# ==================== 配置加载 ====================

def load_client_config() -> dict:
    """加载客户端配置，不存在则引导首次设置"""
    config = config_manager.load_config(CLIENT_CONFIG_PATH)
    if not config or not config.get('password') or config.get('password') == 'CHANGE_ME':
        print('[首次运行] 未检测到有效配置，开始引导设置...')
        config = config_manager.first_run_setup(CLIENT_CONFIG_PATH, is_server=False)
    return config


# ==================== 服务器连接 ====================

class ServerConsole:
    """服务器控制台"""

    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self.channel = None
        self.conn = None

    def connect(self) -> bool:
        """连接并认证"""
        print(f'[连接] {self.host}:{self.port} ...')
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.settimeout(15)

        try:
            self.conn.connect((self.host, self.port))
        except Exception as e:
            print(f'[连接失败] {e}')
            return False

        try:
            # 发送协议标识
            self.conn.sendall(b'ASTROCONSOLE/1.0\n')

            # 接收 READY + salt
            ready = self.conn.recv(64)
            if not ready or b'READY' not in ready:
                print('[认证失败] 服务器未就绪')
                return False

            # salt 是 READY\n 之后的 32 字节
            salt_start = ready.index(b'\n') + 1
            salt = ready[salt_start:]
            while len(salt) < 32:
                salt += self.conn.recv(32 - len(salt))

            # 使用 PBKDF2 从口令和盐派生密钥（与服务器端一致）
            derived_key = hashlib.pbkdf2_hmac(
                'sha256', self.password.encode('utf-8'), salt,
                config_manager.PBKDF2_ITERATIONS, dklen=config_manager.DKLEN,
            )

            # 生成认证信息（使用派生密钥作为 HMAC 密钥）
            timestamp = struct.pack('>Q', int(time.time()))
            nonce = os.urandom(16)
            auth_hmac = hmac.new(
                derived_key,
                salt + timestamp + nonce,
                hashlib.sha256,
            ).digest()

            # 发送认证
            self.conn.sendall(timestamp + nonce + auth_hmac)

            # 接收认证结果
            result = self.conn.recv(64)
            if not result or b'AUTH_OK' not in result:
                print('[认证失败] 口令错误或被拒绝')
                return False

            # 进入加密通信模式
            self.conn.settimeout(None)
            self.channel = CryptoChannel(self.conn, derived_key)
            print(f'[已连接] {self.host}:{self.port}')
            return True

        except Exception as e:
            print(f'[认证错误] {e}')
            return False

    def disconnect(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            self.channel = None
            print('[已断开]')

    def _request(self, msg: dict) -> dict | None:
        """发送请求并接收响应"""
        if not self.channel:
            print('[错误] 未连接')
            return None
        if not self.channel.send_message(msg):
            return None
        return self.channel.recv_message()

    # ==================== 命令方法 ====================

    def exec_cmd(self, cmd: str, timeout: int = 300) -> dict | None:
        """执行远程命令"""
        return self._request({'action': 'exec', 'cmd': cmd, 'timeout': timeout})

    def exec_stream(self, cmd: str) -> int | None:
        """流式执行远程命令，实时打印输出，返回退出码"""
        if not self.channel:
            print('[错误] 未连接')
            return None
        if not self.channel.send_message({'action': 'exec_stream', 'cmd': cmd}):
            return None

        while True:
            msg = self.channel.recv_message()
            if msg is None:
                print('[错误] 连接中断')
                return None
            status = msg.get('status')
            if status == 'stream':
                if msg.get('stdout'):
                    sys.stdout.write(msg['stdout'])
                    sys.stdout.flush()
                if msg.get('stderr'):
                    sys.stderr.write(msg['stderr'])
                    sys.stderr.flush()
            elif status == 'done':
                return msg.get('returncode')
            elif status == 'error':
                print(f'[错误] {msg.get("error", "")}')
                return msg.get('returncode', 1)
            else:
                print(f'[未知响应] {msg}')

    def cancel_stream(self) -> dict | None:
        """取消正在运行的流式命令"""
        return self._request({'action': 'cancel'})

    def ping(self) -> dict | None:
        """心跳检测"""
        return self._request({'action': 'ping'})

    def stat(self, path: str) -> dict | None:
        """获取文件信息"""
        return self._request({'action': 'stat', 'path': path})

    def list_dir(self, path: str) -> dict | None:
        """列出目录"""
        return self._request({'action': 'list', 'path': path})

    def _sha256_file(self, local_path: str) -> str:
        """计算本地文件 SHA-256"""
        h = hashlib.sha256()
        with open(local_path, 'rb') as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()

    def upload_file(self, local_path: str, remote_path: str, show_progress=True) -> bool:
        """上传文件（分块传输，带 SHA-256 完整性校验）"""
        local = Path(local_path)
        if not local.exists() or not local.is_file():
            print(f'[错误] 本地文件不存在: {local_path}')
            return False

        size = local.stat().st_size
        print(f'[上传] {local_path} -> {remote_path} ({size / 1024 / 1024:.1f} MB)')

        # 计算本地文件 SHA-256
        local_sha = self._sha256_file(local_path)

        # 开始上传
        resp = self._request({'action': 'upload_start', 'path': remote_path, 'size': size})
        if not resp or resp.get('status') != 'ready':
            print(f'[错误] 无法开始上传: {resp}')
            return False

        # 分块发送
        sent = 0
        with open(local_path, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                resp = self._request({
                    'action': 'upload_chunk',
                    'path': remote_path,
                    'data': base64.b64encode(chunk).decode(),
                })
                if not resp or resp.get('status') != 'ok':
                    print(f'[错误] 上传失败: {resp}')
                    return False
                sent = resp.get('received', sent + len(chunk))
                if show_progress:
                    pct = sent * 100 / size if size > 0 else 100
                    bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
                    print(f'\r  {bar} {pct:.1f}% ({sent}/{size})', end='', flush=True)

        if show_progress:
            print()

        # 完成上传
        resp = self._request({'action': 'upload_end', 'path': remote_path})
        if not resp or resp.get('status') != 'ok':
            print(f'[错误] 完成上传失败: {resp}')
            return False

        # SHA-256 完整性校验
        remote_sha = resp.get('sha256', '')
        if remote_sha and remote_sha != local_sha:
            print(f'[错误] SHA-256 校验失败！')
            print(f'  本地: {local_sha}')
            print(f'  远程: {remote_sha}')
            return False

        print(f'[完成] {remote_path} ({resp.get("size", 0)} bytes) sha256={remote_sha[:16]}...')
        return True

    def download_file(self, remote_path: str, local_path: str, show_progress=True) -> bool:
        """下载文件（分块传输，带 SHA-256 完整性校验）"""
        # 开始下载
        resp = self._request({'action': 'download_start', 'path': remote_path})
        if not resp or resp.get('status') != 'ready':
            print(f'[错误] 无法开始下载: {resp}')
            return False

        size = resp.get('size', 0)
        expected_sha = resp.get('sha256', '')
        print(f'[下载] {remote_path} -> {local_path} ({size / 1024 / 1024:.1f} MB)')

        # 确保本地目录存在
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)

        # 分块接收
        received = 0
        with open(local_path, 'wb') as f:
            while True:
                resp = self._request({'action': 'download_chunk', 'path': remote_path})
                if not resp:
                    print('[错误] 下载中断')
                    return False

                status = resp.get('status')
                if status == 'end':
                    break
                elif status == 'chunk':
                    data = base64.b64decode(resp['data'])
                    f.write(data)
                    received = resp.get('offset', received + len(data))
                    if show_progress and size > 0:
                        pct = received * 100 / size
                        bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
                        print(f'\r  {bar} {pct:.1f}% ({received}/{size})', end='', flush=True)
                else:
                    print(f'[错误] 下载失败: {resp}')
                    return False

        if show_progress:
            print()

        # 完成下载
        self._request({'action': 'download_end', 'path': remote_path})

        # SHA-256 完整性校验
        if expected_sha:
            local_sha = self._sha256_file(local_path)
            if local_sha != expected_sha:
                print(f'[错误] SHA-256 校验失败！')
                print(f'  本地: {local_sha}')
                print(f'  远程: {expected_sha}')
                return False
            print(f'[校验] SHA-256 一致: {local_sha[:16]}...')

        print(f'[完成] {local_path} ({received} bytes)')
        return True

    # ==================== 高级功能 ====================

    def deploy_agent(self, local_agent_path: str = None) -> bool:
        """部署 server_agent.py 到服务器并安装为服务"""
        if not local_agent_path:
            local_agent_path = str(Path(__file__).parent / 'server_agent.py')

        if not Path(local_agent_path).exists():
            print(f'[错误] 找不到 {local_agent_path}')
            return False

        print('=== 部署 Server Agent ===')

        # 上传 agent 脚本（同时上传配置管理模块）
        config_mgr_path = str(Path(__file__).parent / 'config_manager.py')
        if Path(config_mgr_path).exists():
            self.upload_file(config_mgr_path, '/root/config_manager.py')

        if not self.upload_file(local_agent_path, '/root/server_agent.py'):
            return False

        # 安装 cryptography
        print('[安装] cryptography 库...')
        resp = self.exec_cmd('pip3 install cryptography 2>&1')
        if resp:
            print(resp.get('stdout', ''))

        # 首次运行设置（交互式）
        print('[配置] 请在服务器上完成首次配置...')
        resp = self.exec_stream('python3 /root/server_agent.py --setup')
        if resp is not None:
            print(f'[配置] 返回码: {resp}')

        # 安装 systemd 服务（口令从配置文件读取，不再命令行传递）
        print('[安装] systemd 服务...')
        resp = self.exec_cmd('python3 /root/server_agent.py --install 2>&1')
        if resp:
            print(resp.get('stdout', ''))
            if resp.get('returncode', 1) != 0:
                print(f'[警告] 安装可能有错误: {resp.get("stderr", "")}')

        # 检查状态
        print('[检查] 服务状态...')
        resp = self.exec_cmd('systemctl is-active astrometry-console')
        if resp and 'active' in resp.get('stdout', ''):
            print('[成功] Agent 已部署并运行')
            return True
        else:
            print('[警告] 服务可能未正常启动，请检查')
            return False

    def setup_ssh_key(self, public_key: str = None) -> bool:
        """配置 SSH 公钥到服务器 authorized_keys"""
        if not public_key:
            pub_key_path = Path.home() / '.ssh' / 'id_rsa.pub'
            if not pub_key_path.exists():
                print('[错误] 找不到本地 SSH 公钥，请先运行 ssh-keygen 生成')
                return False
            public_key = pub_key_path.read_text().strip()

        print('[配置] SSH 公钥...')
        cmd = (
            'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
            'echo "{pk}" >> ~/.ssh/authorized_keys && '
            'chmod 600 ~/.ssh/authorized_keys && '
            'sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys'
        ).format(pk=public_key)
        resp = self.exec_cmd(cmd)
        if resp and resp.get('returncode') == 0:
            print('[成功] SSH 公钥已配置')
            return True
        else:
            print(f'[失败] {resp}')
            return False

    def check_indexes(self) -> dict | None:
        """检查服务器索引文件状态"""
        print('[检查] 索引文件...')
        resp = self.exec_cmd(
            'ls -la /usr/local/astrometry/data/index-*.fits 2>/dev/null | '
            'awk \'{print $5, $9}\' | sort -k2'
        )
        if resp:
            output = resp.get('stdout', '')
            files = []
            for line in output.strip().split('\n'):
                if line:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        files.append({'size': int(parts[0]), 'name': parts[1]})
            total = sum(f['size'] for f in files)
            print(f'  索引文件: {len(files)} 个')
            print(f'  总大小: {total / 1024 / 1024 / 1024:.2f} GB')

            series = {}
            for f in files:
                name = f['name']
                parts = name.split('-')
                if len(parts) >= 2:
                    s = parts[1]
                    series[s] = series.get(s, 0) + 1

            print('  系列分布:')
            for s in sorted(series):
                print(f'    {s}: {series[s]} 个文件')

            return {'files': files, 'count': len(files), 'total': total, 'series': series}
        return None


# ==================== 交互式 REPL ====================

HELP_TEXT = """
╔══════════════════════════════════════════════════════╗
║            服务器控制台命令列表                       ║
╠══════════════════════════════════════════════════════╣
║  help / h          显示此帮助                         ║
║  exit / quit       退出控制台                         ║
║  ping              心跳检测                           ║
║  exec <cmd>        执行 shell 命令                    ║
║  stream <cmd>      流式执行命令（实时输出）           ║
║  cancel            取消正在运行的流式命令             ║
║  ls <path>         列出远程目录                       ║
║  stat <path>       查看文件信息                       ║
║  upload <l> <r>    上传文件（带SHA-256校验）          ║
║  download <r> <l>  下载文件（带SHA-256校验）          ║
║  deploy            部署 agent 到服务器                ║
║  ssh-key           配置 SSH 公钥                      ║
║  indexes           检查索引文件状态                   ║
║  upload-indexes    上传本地索引文件到服务器           ║
║  svc-status        查看 astrometry 服务状态           ║
║  svc-restart       重启 astrometry API 服务           ║
║  logs [n]          查看最近 n 行日志 (默认50)         ║
╚══════════════════════════════════════════════════════╝
"""


def interactive_repl(console: ServerConsole):
    """交互式命令行"""
    print(HELP_TEXT)

    while True:
        try:
            line = input(f'\n[{console.host}]# ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n[退出]')
            break

        if not line:
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''

        if cmd in ('exit', 'quit', 'q'):
            break
        elif cmd in ('help', 'h', '?'):
            print(HELP_TEXT)
        elif cmd == 'ping':
            resp = console.ping()
            if resp:
                print(f'  主机: {resp.get("hostname", "?")}')
                print(f'  时间: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(resp.get("time", 0)))}')
                print(f'  运行: {resp.get("uptime", 0):.0f} 秒')
            else:
                print('[错误] 无响应')
        elif cmd == 'exec':
            if not args:
                print('用法: exec <命令>')
                continue
            resp = console.exec_cmd(args)
            if resp:
                if resp.get('stdout'):
                    print(resp['stdout'], end='')
                if resp.get('stderr'):
                    print(f'[stderr] {resp["stderr"]}', end='')
                print(f'[返回码: {resp.get("returncode", "?")}]')
            else:
                print('[错误] 无响应')
        elif cmd == 'stream':
            if not args:
                print('用法: stream <命令>')
                continue
            rc = console.exec_stream(args)
            print(f'[返回码: {rc}]')
        elif cmd == 'cancel':
            resp = console.cancel_stream()
            if resp:
                print(f'  {resp.get("status", "?")}: {resp.get("error", "")}')
            else:
                print('[错误] 无响应')
        elif cmd == 'ls':
            path = args or '/'
            resp = console.list_dir(path)
            if resp and resp.get('status') == 'ok':
                for f in resp.get('files', []):
                    ftype = '📁' if f['is_dir'] else '📄'
                    size = f['size']
                    if size > 1024 * 1024:
                        ssize = f'{size / 1024 / 1024:.1f}M'
                    elif size > 1024:
                        ssize = f'{size / 1024:.1f}K'
                    else:
                        ssize = str(size)
                    print(f'  {ftype} {f["name"]:<40} {ssize}')
                print(f'  共 {resp.get("count", 0)} 项')
            else:
                print(f'[错误] {resp}')
        elif cmd == 'stat':
            if not args:
                print('用法: stat <路径>')
                continue
            resp = console.stat(args)
            if resp:
                print(json.dumps(resp, indent=2, ensure_ascii=False))
            else:
                print('[错误] 无响应')
        elif cmd == 'upload':
            p = args.split(None, 1)
            if len(p) != 2:
                print('用法: upload <本地路径> <远程路径>')
                continue
            console.upload_file(p[0], p[1])
        elif cmd == 'download':
            p = args.split(None, 1)
            if len(p) != 2:
                print('用法: download <远程路径> <本地路径>')
                continue
            console.download_file(p[0], p[1])
        elif cmd == 'deploy':
            console.deploy_agent()
        elif cmd == 'ssh-key':
            console.setup_ssh_key()
        elif cmd == 'indexes':
            console.check_indexes()
        elif cmd == 'upload-indexes':
            upload_indexes_command(console)
        elif cmd == 'svc-status':
            resp = console.exec_cmd('systemctl status astrometry-api --no-pager 2>&1; echo "---"; systemctl status astrometry-console --no-pager 2>&1')
            if resp:
                print(resp.get('stdout', ''))
        elif cmd == 'svc-restart':
            resp = console.exec_cmd('systemctl restart astrometry-api 2>&1')
            if resp:
                print(resp.get('stdout', ''))
                print('[完成] astrometry-api 已重启')
        elif cmd == 'logs':
            n = args or '50'
            resp = console.exec_cmd(f'journalctl -u astrometry-api --no-pager -n {n} 2>&1')
            if resp:
                print(resp.get('stdout', ''))
        else:
            print(f'未知命令: {cmd}，输入 help 查看帮助')


def upload_indexes_command(console: ServerConsole):
    """上传本地索引文件到服务器"""
    local_dir = Path(__file__).parent / 'indexes'
    if not local_dir.exists():
        print(f'[错误] 本地索引目录不存在: {local_dir}')
        print('  请先将索引文件下载到此目录')
        return

    fits_files = list(local_dir.glob('index-*.fits'))
    if not fits_files:
        print(f'[错误] {local_dir} 中没有索引文件')
        return

    print(f'找到 {len(fits_files)} 个索引文件')

    server_state = console.check_indexes()
    server_files = set()
    if server_state:
        for f in server_state['files']:
            server_files.add(Path(f['name']).name)

    to_upload = [f for f in fits_files if f.name not in server_files]
    if not to_upload:
        print('[完成] 所有索引文件已在服务器上')
        return

    print(f'需要上传 {len(to_upload)} 个文件')

    for i, f in enumerate(to_upload, 1):
        print(f'\n[{i}/{len(to_upload)}] {f.name}')
        console.upload_file(str(f), f'/usr/local/astrometry/data/{f.name}')

    print(f'\n[完成] 共上传 {len(to_upload)} 个索引文件')


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description='Astrometry Server Console')
    parser.add_argument('--host', default=None, help='服务器地址（覆盖配置文件）')
    parser.add_argument('--port', type=int, default=None, help='服务器端口（覆盖配置文件）')
    parser.add_argument('--password', default=None, help='认证口令（覆盖配置文件）')
    parser.add_argument('--setup', action='store_true', help='重新进行客户端配置引导')
    parser.add_argument('--exec', dest='exec_cmd', help='执行单条命令并退出')
    parser.add_argument('--stream', dest='stream_cmd', help='流式执行命令并退出')
    parser.add_argument('--ping', action='store_true', help='心跳检测')
    parser.add_argument('--upload', nargs=2, metavar=('LOCAL', 'REMOTE'), help='上传文件')
    parser.add_argument('--download', nargs=2, metavar=('REMOTE', 'LOCAL'), help='下载文件')
    parser.add_argument('--deploy', action='store_true', help='部署 agent 到服务器')
    parser.add_argument('--ssh-key', action='store_true', help='配置 SSH 公钥')
    parser.add_argument('--indexes', action='store_true', help='检查索引文件')
    args = parser.parse_args()

    # --setup：重新配置
    if args.setup:
        config_manager.first_run_setup(CLIENT_CONFIG_PATH, is_server=False)
        return

    # 加载配置
    config = load_client_config()
    host = args.host or config.get('host', DEFAULT_HOST)
    port = args.port or config.get('port', DEFAULT_PORT)
    password = args.password or config.get('password', 'CHANGE_ME')

    console = ServerConsole(host, port, password)

    if not console.connect():
        sys.exit(1)

    # 单命令模式
    if args.ping:
        resp = console.ping()
        if resp:
            print(f'OK - {resp.get("hostname")} - {resp.get("uptime", 0):.0f}s')
        else:
            print('FAIL')
            sys.exit(1)
    elif args.exec_cmd:
        resp = console.exec_cmd(args.exec_cmd)
        if resp:
            if resp.get('stdout'):
                sys.stdout.write(resp['stdout'])
            if resp.get('stderr'):
                sys.stderr.write(resp['stderr'])
            sys.exit(resp.get('returncode', 1))
        else:
            sys.exit(1)
    elif args.stream_cmd:
        rc = console.exec_stream(args.stream_cmd)
        sys.exit(rc if rc is not None else 1)
    elif args.upload:
        ok = console.upload_file(args.upload[0], args.upload[1])
        sys.exit(0 if ok else 1)
    elif args.download:
        ok = console.download_file(args.download[0], args.download[1])
        sys.exit(0 if ok else 1)
    elif args.deploy:
        ok = console.deploy_agent()
        sys.exit(0 if ok else 1)
    elif args.ssh_key:
        ok = console.setup_ssh_key()
        sys.exit(0 if ok else 1)
    elif args.indexes:
        console.check_indexes()
    else:
        # 交互模式
        try:
            interactive_repl(console)
        finally:
            console.disconnect()


if __name__ == '__main__':
    main()
