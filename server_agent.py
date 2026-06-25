#!/usr/bin/env python3
"""
Astrometry Server Control Agent
服务器端控制守护进程 - 以 root 权限运行，提供加密远程控制能力

安全特性：
- PBKDF2-HMAC-SHA256 口令哈希（10万次迭代，从配置文件读取）
- HMAC-SHA256 口令认证（使用 PBKDF2 派生密钥）
- AES-256-CBC 加密通信（强制要求 cryptography 库，无降级）
- 时间戳防重放攻击
- IP 白名单（accept 后检查，不在白名单则关闭连接）
- 暴力破解防护（5次失败封禁IP 15分钟）
- 认证后空闲超时（30分钟无操作断开）
- 操作审计日志（按天轮转，保留30天）
- 文件传输 SHA-256 完整性校验
- 流式命令执行（exec_stream）与取消（cancel）

部署方式：
    python3 server_agent.py --setup    # 首次运行交互式设置口令和配置
    python3 server_agent.py --install  # 安装为 systemd 服务
    python3 server_agent.py            # 前台运行
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
import select
import logging
import ipaddress
import subprocess
import threading
import argparse
import logging.handlers
from pathlib import Path

import config_manager

# ==================== 配置 ====================

SERVER_CONFIG_PATH = config_manager.SERVER_CONFIG_PATH
LISTEN_HOST_DEFAULT = '0.0.0.0'
LISTEN_PORT_DEFAULT = 9999
AUTH_TIMEOUT = 10  # 认证超时秒数
MAX_REPLAY_AGE = 300  # 时间戳有效窗口（5分钟）
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB 分块传输
IDLE_TIMEOUT = 30 * 60  # 认证后空闲超时（30分钟）
BAN_THRESHOLD = 5  # 暴力破解封禁阈值
BAN_DURATION = 15 * 60  # 封禁时长（15分钟）
LOG_BACKUP_DAYS = 30  # 审计日志保留天数

# ==================== 强制 cryptography 库 ====================

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    _CRYPTO_BACKEND = default_backend()
except ImportError:
    print('[FATAL] cryptography 库未安装，请运行: pip3 install cryptography')
    sys.exit(1)


# ==================== 加密通道 ====================

class CryptoChannel:
    """AES-256-CBC 加密通信通道（强制使用 cryptography，无降级）"""

    def __init__(self, conn: socket.socket, key: bytes):
        self.conn = conn
        # key 为 PBKDF2 派生的 32 字节密钥
        self.key = key

    def _encrypt(self, plaintext: bytes) -> bytes:
        """AES-256-CBC 加密，返回 IV + 密文"""
        iv = os.urandom(16)
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(iv),
            backend=_CRYPTO_BACKEND,
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return iv + ciphertext

    def _decrypt(self, data: bytes) -> bytes:
        """AES-256-CBC 解密，输入为 IV + 密文"""
        iv = data[:16]
        ciphertext = data[16:]
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(iv),
            backend=_CRYPTO_BACKEND,
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = padded[-1]
        return padded[:-pad_len]

    def send_message(self, obj: dict) -> bool:
        """发送加密 JSON 消息"""
        try:
            plaintext = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            encrypted = self._encrypt(plaintext)
            header = struct.pack('>I', len(encrypted))
            self.conn.sendall(header + encrypted)
            return True
        except Exception as e:
            print(f'[SEND ERROR] {e}')
            return False

    def recv_message(self) -> dict | None:
        """接收并解密 JSON 消息"""
        try:
            header = self._recv_exact(4)
            if not header:
                return None
            length = struct.unpack('>I', header)[0]
            if length > 100 * 1024 * 1024:
                print(f'[RECV ERROR] message too large: {length}')
                return None
            data = self._recv_exact(length)
            if not data:
                return None
            plaintext = self._decrypt(data)
            return json.loads(plaintext.decode('utf-8'))
        except Exception as e:
            print(f'[RECV ERROR] {e}')
            return None

    def _recv_exact(self, n: int) -> bytes | None:
        """精确接收 n 字节"""
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
                print(f'[RECV ERROR] {e}')
                return None
        return bytes(buf)


# ==================== 认证 ====================

def verify_auth(derived_key: bytes, salt: bytes, timestamp: bytes,
                nonce: bytes, recv_hmac: bytes) -> bool:
    """验证 HMAC 认证（使用 PBKDF2 派生密钥）"""
    ts = struct.unpack('>Q', timestamp)[0]
    now = int(time.time())
    if abs(now - ts) > MAX_REPLAY_AGE:
        print(f'[AUTH] timestamp out of range: ts={ts}, now={now}')
        return False

    expected = hmac.new(
        derived_key,
        salt + timestamp + nonce,
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(expected, recv_hmac)


# ==================== IP 白名单 ====================

def is_ip_allowed(client_ip: str, whitelist: list) -> bool:
    """检查客户端 IP 是否在白名单中（支持单 IP 和 CIDR）"""
    if not whitelist:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            if '/' in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if ip in network:
                    return True
            else:
                if ip == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


# ==================== 暴力破解防护 ====================

_fail_counts: dict = {}  # ip -> 失败次数
_ban_until: dict = {}    # ip -> 封禁截止时间戳
_brute_lock = threading.Lock()


def is_banned(client_ip: str) -> bool:
    """检查 IP 是否被封禁"""
    with _brute_lock:
        if client_ip in _ban_until:
            if time.time() < _ban_until[client_ip]:
                return True
            # 封禁过期，清理
            del _ban_until[client_ip]
            _fail_counts.pop(client_ip, None)
        return False


def record_auth_fail(client_ip: str) -> bool:
    """记录认证失败，返回是否触发封禁"""
    with _brute_lock:
        _fail_counts[client_ip] = _fail_counts.get(client_ip, 0) + 1
        if _fail_counts[client_ip] >= BAN_THRESHOLD:
            _ban_until[client_ip] = time.time() + BAN_DURATION
            return True
        return False


def record_auth_success(client_ip: str) -> None:
    """记录认证成功，清除失败计数"""
    with _brute_lock:
        _fail_counts.pop(client_ip, None)
        _ban_until.pop(client_ip, None)


# ==================== 审计日志 ====================

class AuditLogger:
    """操作审计日志（按天轮转，保留指定天数）"""

    def __init__(self, log_path: str):
        self.log_path = log_path
        try:
            os.makedirs(log_path, exist_ok=True)
        except OSError:
            self.log_path = None
            return
        self.logger = logging.getLogger('astrometry_audit')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        # 清理已有 handler，避免重复
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)
        try:
            handler = logging.handlers.TimedRotatingFileHandler(
                os.path.join(log_path, 'audit.log'),
                when='midnight',
                backupCount=LOG_BACKUP_DAYS,
                encoding='utf-8',
            )
            handler.suffix = '%Y-%m-%d'
            formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)s] [%(client_ip)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        except (OSError, PermissionError):
            self.log_path = None

    def log(self, client_ip: str, level: str, message: str) -> None:
        if not self.log_path:
            return
        extra = {'client_ip': client_ip}
        try:
            if level == 'WARNING':
                self.logger.warning(message, extra=extra)
            elif level == 'ERROR':
                self.logger.error(message, extra=extra)
            else:
                self.logger.info(message, extra=extra)
        except Exception:
            pass


# ==================== 命令处理 ====================

def handle_exec(cmd: str, timeout: int = 300) -> dict:
    """执行 shell 命令"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            'status': 'ok',
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': f'Command timeout after {timeout}s'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


# 流式进程表：addr -> subprocess.Popen
_stream_procs: dict = {}
_stream_lock = threading.Lock()


def handle_exec_stream(channel: CryptoChannel, cmd: str, ctx: dict) -> None:
    """流式执行命令，实时通过 channel 发送 stdout/stderr"""
    addr = ctx['addr']
    client_ip = ctx['client_ip']
    audit: AuditLogger = ctx['audit']

    if audit:
        audit.log(client_ip, 'INFO', f'exec_stream: {cmd}')

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )
    except Exception as e:
        channel.send_message({'status': 'error', 'error': str(e)})
        return

    with _stream_lock:
        _stream_procs[addr] = proc

    try:
        while proc.poll() is None:
            try:
                rlist, _, _ = select.select([proc.stdout, proc.stderr], [], [], 1.0)
            except (OSError, ValueError):
                break
            for stream in rlist:
                line = stream.readline()
                if line:
                    key = 'stdout' if stream is proc.stdout else 'stderr'
                    if not channel.send_message({'status': 'stream', key: line}):
                        # 连接断开，终止进程
                        proc.terminate()
                        return
        # 进程结束，读取剩余输出
        try:
            out = proc.stdout.read() if proc.stdout else ''
            err = proc.stderr.read() if proc.stderr else ''
        except Exception:
            out = ''
            err = ''
        if out:
            channel.send_message({'status': 'stream', 'stdout': out})
        if err:
            channel.send_message({'status': 'stream', 'stderr': err})
    finally:
        try:
            proc.stdout.close()
            proc.stderr.close()
        except Exception:
            pass
        with _stream_lock:
            _stream_procs.pop(addr, None)

    channel.send_message({'status': 'done', 'returncode': proc.returncode})
    if audit:
        audit.log(client_ip, 'INFO', f'exec_stream done: returncode={proc.returncode}')


def handle_cancel(ctx: dict) -> dict:
    """取消正在运行的流式命令"""
    addr = ctx['addr']
    with _stream_lock:
        proc = _stream_procs.get(addr)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return {'status': 'cancelled'}
    return {'status': 'error', 'error': 'No running stream command'}


def _sha256_file(path: str) -> str:
    """计算文件 SHA-256"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            data = f.read(CHUNK_SIZE)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def handle_upload_start(path: str, size: int) -> dict:
    """开始文件上传"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_suffix(p.suffix + '.partial')
    _upload_state[path] = {
        'tmp_path': str(tmp_path),
        'size': size,
        'received': 0,
        'f': open(tmp_path, 'wb'),
    }
    return {'status': 'ready'}


def handle_upload_chunk(path: str, data_b64: str) -> dict:
    """接收文件分块"""
    if path not in _upload_state:
        return {'status': 'error', 'error': 'Upload not started'}
    state = _upload_state[path]
    data = base64.b64decode(data_b64)
    state['f'].write(data)
    state['received'] += len(data)
    return {'status': 'ok', 'received': state['received']}


def handle_upload_end(path: str) -> dict:
    """完成文件上传，计算 SHA-256 完整性校验"""
    if path not in _upload_state:
        return {'status': 'error', 'error': 'Upload not started'}
    state = _upload_state.pop(path)
    state['f'].close()
    p = Path(path)
    shutil_move(state['tmp_path'], str(p))
    actual_size = p.stat().st_size
    sha256 = _sha256_file(path)
    return {'status': 'ok', 'size': actual_size, 'path': str(p), 'sha256': sha256}


def handle_download_start(path: str) -> dict:
    """开始文件下载，计算 SHA-256 完整性校验"""
    p = Path(path)
    if not p.exists():
        return {'status': 'error', 'error': 'File not found'}
    if not p.is_file():
        return {'status': 'error', 'error': 'Not a file'}
    size = p.stat().st_size
    sha256 = _sha256_file(path)
    _download_state[path] = {'f': open(p, 'rb'), 'size': size, 'offset': 0}
    return {'status': 'ready', 'size': size, 'sha256': sha256}


def handle_download_chunk(path: str) -> dict:
    """发送文件分块"""
    if path not in _download_state:
        return {'status': 'error', 'error': 'Download not started'}
    state = _download_state[path]
    data = state['f'].read(CHUNK_SIZE)
    if not data:
        return {'status': 'end'}
    state['offset'] += len(data)
    return {
        'status': 'chunk',
        'data': base64.b64encode(data).decode(),
        'offset': state['offset'],
        'remaining': state['size'] - state['offset'],
    }


def handle_download_end(path: str) -> dict:
    """完成文件下载"""
    if path in _download_state:
        state = _download_state.pop(path)
        state['f'].close()
    return {'status': 'ok'}


def handle_stat(path: str) -> dict:
    """获取文件/目录信息"""
    p = Path(path)
    if not p.exists():
        return {'status': 'ok', 'exists': False}
    stat = p.stat()
    return {
        'status': 'ok',
        'exists': True,
        'size': stat.st_size,
        'is_dir': p.is_dir(),
        'is_file': p.is_file(),
        'mode': oct(stat.st_mode),
        'mtime': stat.st_mtime,
    }


def handle_list(path: str) -> dict:
    """列出目录内容"""
    p = Path(path)
    if not p.exists():
        return {'status': 'error', 'error': 'Path not found'}
    if not p.is_dir():
        return {'status': 'error', 'error': 'Not a directory'}
    files = []
    for item in sorted(p.iterdir()):
        try:
            stat = item.stat()
            files.append({
                'name': item.name,
                'size': stat.st_size,
                'is_dir': item.is_dir(),
                'mtime': stat.st_mtime,
            })
        except OSError:
            continue
    return {'status': 'ok', 'files': files, 'count': len(files)}


def handle_ping() -> dict:
    """心跳检测"""
    return {
        'status': 'pong',
        'hostname': socket.gethostname(),
        'time': time.time(),
        'uptime': _get_uptime(),
    }


def _get_uptime() -> float:
    try:
        with open('/proc/uptime') as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


def shutil_move(src: str, dst: str) -> None:
    """移动文件（延迟导入以保留顶层简洁）"""
    import shutil
    shutil.move(src, dst)


# 上传/下载状态
_upload_state: dict = {}
_download_state: dict = {}

# 已使用的 nonce（防重放）
_used_nonces: set = set()
_nonce_lock = threading.Lock()


def process_request(channel: CryptoChannel, msg: dict, ctx: dict) -> dict | None:
    """处理请求，返回响应字典；返回 None 表示已自行发送消息（如流式命令）"""
    action = msg.get('action', '')
    client_ip = ctx['client_ip']
    audit: AuditLogger = ctx['audit']

    if action == 'ping':
        if audit:
            audit.log(client_ip, 'INFO', 'ping')
        return handle_ping()
    elif action == 'exec':
        cmd = msg.get('cmd', '')
        if audit:
            audit.log(client_ip, 'INFO', f'exec: {cmd}')
        return handle_exec(cmd, msg.get('timeout', 300))
    elif action == 'exec_stream':
        handle_exec_stream(channel, msg.get('cmd', ''), ctx)
        return None
    elif action == 'cancel':
        return handle_cancel(ctx)
    elif action == 'upload_start':
        path = msg.get('path', '')
        if audit:
            audit.log(client_ip, 'INFO', f'upload_start: {path}')
        return handle_upload_start(path, msg.get('size', 0))
    elif action == 'upload_chunk':
        return handle_upload_chunk(msg.get('path', ''), msg.get('data', ''))
    elif action == 'upload_end':
        path = msg.get('path', '')
        resp = handle_upload_end(path)
        if audit and resp.get('status') == 'ok':
            audit.log(client_ip, 'INFO',
                      f'upload_end: {path} sha256={resp.get("sha256", "")[:16]}...')
        return resp
    elif action == 'download_start':
        path = msg.get('path', '')
        resp = handle_download_start(path)
        if audit and resp.get('status') == 'ready':
            audit.log(client_ip, 'INFO',
                      f'download_start: {path} sha256={resp.get("sha256", "")[:16]}...')
        return resp
    elif action == 'download_chunk':
        return handle_download_chunk(msg.get('path', ''))
    elif action == 'download_end':
        return handle_download_end(msg.get('path', ''))
    elif action == 'stat':
        return handle_stat(msg.get('path', ''))
    elif action == 'list':
        return handle_list(msg.get('path', ''))
    else:
        return {'status': 'error', 'error': f'Unknown action: {action}'}


# ==================== 连接处理 ====================

def handle_client(conn: socket.socket, addr, config: dict, audit: AuditLogger):
    """处理单个客户端连接"""
    client_ip = addr[0]
    ctx = {
        'addr': addr,
        'client_ip': client_ip,
        'audit': audit,
        'config': config,
    }

    # === IP 白名单检查 ===
    whitelist = config.get('ip_whitelist', [])
    if whitelist and not is_ip_allowed(client_ip, whitelist):
        print(f'[REJECT] IP 不在白名单: {client_ip}')
        if audit:
            audit.log(client_ip, 'WARNING', 'connection rejected: not in whitelist')
        conn.close()
        return

    # === 暴力破解封禁检查 ===
    if is_banned(client_ip):
        print(f'[BANNED] {client_ip} 已被封禁')
        if audit:
            audit.log(client_ip, 'WARNING', 'connection rejected: IP banned')
        conn.close()
        return

    print(f'[CONNECT] {addr[0]}:{addr[1]}')
    conn.settimeout(AUTH_TIMEOUT)

    try:
        # === 握手阶段 ===
        proto = conn.recv(64)
        if not proto or b'ASTROCONSOLE' not in proto:
            conn.sendall(b'PROTOCOL_ERROR\n')
            return

        # 发送 READY + password_salt（使用配置中的固定盐）
        salt = bytes.fromhex(config['password_salt'])
        conn.sendall(b'READY\n' + salt)

        # 接收认证信息: timestamp(8) + nonce(16) + hmac(32)
        auth_data = _recv_exact_raw(conn, 56)
        if not auth_data or len(auth_data) < 56:
            conn.sendall(b'AUTH_FAIL\n')
            return

        timestamp = auth_data[:8]
        nonce = auth_data[8:24]
        recv_hmac = auth_data[24:56]

        # 派生密钥（从配置文件的 password_hash 读取，即 PBKDF2 派生结果）
        derived_key = bytes.fromhex(config['password_hash'])

        # 验证认证
        if not verify_auth(derived_key, salt, timestamp, nonce, recv_hmac):
            conn.sendall(b'AUTH_FAIL\n')
            banned = record_auth_fail(client_ip)
            print(f'[AUTH FAIL] {addr[0]}:{addr[1]}' +
                  (f' -> 已封禁' if banned else ''))
            if audit:
                audit.log(client_ip, 'WARNING',
                          f'auth failed{" (banned)" if banned else ""}')
            return

        # 检查 nonce 是否重复（防重放）
        nonce_key = nonce.hex()
        with _nonce_lock:
            if nonce_key in _used_nonces:
                conn.sendall(b'AUTH_FAIL\n')
                print(f'[REPLAY ATTACK] {addr[0]}:{addr[1]}')
                if audit:
                    audit.log(client_ip, 'WARNING', 'replay attack detected')
                return
            _used_nonces.add(nonce_key)
            if len(_used_nonces) > 1000:
                _used_nonces.clear()
                _used_nonces.add(nonce_key)

        record_auth_success(client_ip)
        conn.sendall(b'AUTH_OK\n')
        # 认证后设置空闲超时
        conn.settimeout(IDLE_TIMEOUT)
        print(f'[AUTH OK] {addr[0]}:{addr[1]}')
        if audit:
            audit.log(client_ip, 'INFO', 'authenticated')

        # === 加密通信阶段 ===
        channel = CryptoChannel(conn, derived_key)

        while True:
            msg = channel.recv_message()
            if msg is None:
                break

            response = process_request(channel, msg, ctx)
            if response is not None:
                if not channel.send_message(response):
                    break

    except socket.timeout:
        print(f'[TIMEOUT] {addr[0]}:{addr[1]}')
        if audit:
            audit.log(client_ip, 'WARNING', 'idle timeout disconnected')
    except Exception as e:
        print(f'[ERROR] {addr[0]}:{addr[1]}: {e}')
        if audit:
            audit.log(client_ip, 'ERROR', f'connection error: {e}')
    finally:
        conn.close()
        print(f'[DISCONNECT] {addr[0]}:{addr[1]}')


def _recv_exact_raw(conn: socket.socket, n: int) -> bytes | None:
    """精确接收 n 字节"""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        except Exception:
            return None
    return bytes(buf)


# ==================== 服务器启动 ====================

def run_server(config: dict, audit: AuditLogger):
    """启动服务器"""
    host = config.get('host', LISTEN_HOST_DEFAULT)
    port = config.get('port', LISTEN_PORT_DEFAULT)

    print('╔══════════════════════════════════════════════╗')
    print('║   Astrometry Server Control Agent v2.0       ║')
    print('╠══════════════════════════════════════════════╣')
    print(f'║  监听: {host}:{port:<28} ║')
    print(f'║  PID:  {os.getpid():<35} ║')
    print(f'║  用户: {os.getenv("USER", "root"):<34} ║')
    print('║  加密: AES-256-CBC + HMAC-SHA256             ║')
    print('║  认证: PBKDF2 派生密钥 (100k 迭代)           ║')
    print(f'║  白名单: {len(config.get("ip_whitelist", []))} 条规则' +
          ' ' * 25)
    print('║  审计: 按天轮转，保留30天                     ║')
    print('╚══════════════════════════════════════════════╝')

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((host, port))
    except OSError as e:
        print(f'[FATAL] 无法绑定端口 {port}: {e}')
        sys.exit(1)

    server.listen(5)
    print('[LISTENING] 等待连接...')

    while True:
        try:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, config, audit),
                daemon=True,
            )
            thread.start()
        except KeyboardInterrupt:
            print('\n[SHUTDOWN] 服务器关闭')
            break
        except Exception as e:
            print(f'[ACCEPT ERROR] {e}')


# ==================== systemd 安装 ====================

SERVICE_TEMPLATE = """[Unit]
Description=Astrometry Server Control Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 {script_path}
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""


def install_systemd_service(script_path: str, config: dict):
    """安装为 systemd 服务（口令从配置文件读取，不再从命令行传递）"""
    os.makedirs('/etc/astrometry', exist_ok=True)

    # 确认配置文件已存在且口令已设置
    if not config.get('password_hash') or not config.get('password_salt'):
        print('[错误] 配置文件未设置口令，请先运行: python3 server_agent.py --setup')
        sys.exit(1)

    service_content = SERVICE_TEMPLATE.format(script_path=script_path)
    service_path = '/etc/systemd/system/astrometry-console.service'
    with open(service_path, 'w') as f:
        f.write(service_content)
    os.chmod(service_path, 0o644)
    print(f'[OK] 服务文件写入 {service_path}')

    # 确保审计日志目录存在
    log_path = config.get('log_path', '/var/log/astrometry-console')
    os.makedirs(log_path, exist_ok=True)

    # 启用并启动
    os.system('systemctl daemon-reload')
    os.system('systemctl enable astrometry-console')
    os.system('systemctl start astrometry-console')
    print('[OK] 服务已启动: systemctl status astrometry-console')


def uninstall_systemd_service():
    """卸载 systemd 服务"""
    os.system('systemctl stop astrometry-console')
    os.system('systemctl disable astrometry-console')
    try:
        os.remove('/etc/systemd/system/astrometry-console.service')
    except FileNotFoundError:
        pass
    os.system('systemctl daemon-reload')
    print('[OK] 服务已卸载')


def main():
    parser = argparse.ArgumentParser(description='Astrometry Server Control Agent')
    parser.add_argument('--host', default=None, help='监听地址（覆盖配置文件）')
    parser.add_argument('--port', type=int, default=None, help='监听端口（覆盖配置文件）')
    parser.add_argument('--setup', action='store_true',
                        help='首次运行交互式设置口令和配置')
    parser.add_argument('--install', action='store_true', help='安装为 systemd 服务')
    parser.add_argument('--uninstall', action='store_true', help='卸载 systemd 服务')
    args = parser.parse_args()

    if args.uninstall:
        uninstall_systemd_service()
        return

    # --setup：首次运行引导
    if args.setup:
        config_manager.first_run_setup(SERVER_CONFIG_PATH, is_server=True)
        return

    # 加载配置
    config = config_manager.load_config(SERVER_CONFIG_PATH)
    if not config or not config.get('password_hash') or not config.get('password_salt'):
        print('[错误] 配置文件不存在或未设置口令。')
        print('  请先运行: python3 server_agent.py --setup')
        sys.exit(1)

    # 命令行参数覆盖
    if args.host:
        config['host'] = args.host
    if args.port:
        config['port'] = args.port
    config.setdefault('host', LISTEN_HOST_DEFAULT)
    config.setdefault('port', LISTEN_PORT_DEFAULT)
    config.setdefault('ip_whitelist', ['127.0.0.1'])
    config.setdefault('log_path', '/var/log/astrometry-console')

    # 初始化审计日志
    audit = AuditLogger(config['log_path'])

    if args.install:
        script_path = os.path.abspath(__file__)
        install_systemd_service(script_path, config)
        return

    # 前台运行
    run_server(config, audit)


if __name__ == '__main__':
    main()
