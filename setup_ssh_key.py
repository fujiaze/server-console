#!/usr/bin/env python3
"""
SSH 密钥管理工具
生成密钥对、查看公钥、通过控制台配置到服务器

用法：
    python setup_ssh_key.py --generate          # 生成 RSA 4096 密钥对
    python setup_ssh_key.py --show              # 显示公钥
    python setup_ssh_key.py --deploy            # 通过控制台部署公钥到服务器
    python setup_ssh_key.py --all               # 生成 + 部署
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import config_manager
except ImportError:
    config_manager = None

# 从客户端配置文件读取默认值，不存在时使用占位符
_client_cfg = {}
if config_manager:
    _client_cfg = config_manager.load_config(config_manager.CLIENT_CONFIG_PATH) or {}
DEFAULT_HOST = _client_cfg.get('host', '127.0.0.1')
DEFAULT_PORT = _client_cfg.get('port', 9999)
DEFAULT_PASSWORD = _client_cfg.get('password', 'CHANGE_ME')


def generate_key(key_path: str = None, key_type: str = 'rsa', bits: int = 4096) -> bool:
    """生成 SSH 密钥对"""
    if not key_path:
        key_path = str(Path.home() / '.ssh' / 'id_rsa')

    key_file = Path(key_path)

    # 如果密钥已存在，询问
    if key_file.exists():
        print(f'[警告] 密钥已存在: {key_path}')
        answer = input('  覆盖? (y/N): ').strip().lower()
        if answer != 'y':
            print('[取消]')
            return False
        # 删除旧密钥
        key_file.unlink(missing_ok=True)
        key_file.with_suffix('.pub').unlink(missing_ok=True)

    # 确保 .ssh 目录存在
    key_file.parent.mkdir(parents=True, exist_ok=True)

    print(f'[生成] {key_type.upper()} {bits} 位密钥...')

    cmd = [
        'ssh-keygen',
        '-t', key_type,
        '-b', str(bits),
        '-f', key_path,
        '-N', '',  # 空密码
        '-C', f'{os.getenv("USERNAME", "user")}@{os.getenv("COMPUTERNAME", "pc")}'
    ]

    if key_type == 'ed25519':
        # ed25519 不需要 -b 参数
        cmd = [c for c in cmd if c not in ('-b', str(bits))]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f'[错误] {result.stderr}')
            return False
    except FileNotFoundError:
        print('[错误] 找不到 ssh-keygen，请确保 OpenSSH 已安装')
        return False

    # 设置权限（Windows 上可能需要手动设置）
    print(f'[完成] 私钥: {key_path}')
    print(f'[完成] 公钥: {key_path}.pub')
    return True


def show_public_key(key_path: str = None) -> str | None:
    """显示公钥内容"""
    if not key_path:
        # 尝试多种密钥类型
        for name in ['id_rsa', 'id_ed25519', 'id_ecdsa']:
            p = Path.home() / '.ssh' / f'{name}.pub'
            if p.exists():
                key_path = str(p)
                break

    if not key_path:
        print('[错误] 找不到 SSH 公钥')
        print('  请先运行: python setup_ssh_key.py --generate')
        return None

    pub_path = Path(key_path)
    if not pub_path.exists():
        # 尝试 .pub 后缀
        pub_path = Path(f'{key_path}.pub')

    if not pub_path.exists():
        print(f'[错误] 公钥文件不存在: {pub_path}')
        return None

    content = pub_path.read_text().strip()
    print(f'[公钥] {pub_path}')
    print(f'  {content}')
    return content


def deploy_via_console(host: str, port: int, password: str, public_key: str = None) -> bool:
    """通过控制台将公钥部署到服务器"""
    # 导入控制台
    sys.path.insert(0, str(Path(__file__).parent))
    from local_console import ServerConsole

    console = ServerConsole(host, port, password)
    if not console.connect():
        return False

    try:
        return console.setup_ssh_key(public_key)
    finally:
        console.disconnect()


def main():
    parser = argparse.ArgumentParser(description='SSH 密钥管理工具')
    parser.add_argument('--generate', action='store_true', help='生成 SSH 密钥对')
    parser.add_argument('--show', action='store_true', help='显示公钥')
    parser.add_argument('--deploy', action='store_true', help='部署公钥到服务器')
    parser.add_argument('--all', action='store_true', help='生成 + 部署')
    parser.add_argument('--key-path', help='密钥路径')
    parser.add_argument('--type', default='rsa', choices=['rsa', 'ed25519', 'ecdsa'], help='密钥类型')
    parser.add_argument('--bits', type=int, default=4096, help='密钥位数')
    parser.add_argument('--host', default=DEFAULT_HOST, help='服务器地址')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='控制台端口')
    parser.add_argument('--password', default=DEFAULT_PASSWORD, help='控制台口令')
    args = parser.parse_args()

    if args.all:
        args.generate = True
        args.deploy = True

    if not any([args.generate, args.show, args.deploy]):
        parser.print_help()
        return

    if args.generate:
        if not generate_key(args.key_path, args.type, args.bits):
            sys.exit(1)
        print()

    pub_key = None
    if args.show or args.deploy:
        pub_key = show_public_key(args.key_path)
        if not pub_key:
            sys.exit(1)
        print()

    if args.deploy:
        print(f'=== 部署 SSH 公钥到 {args.host} ===')
        if deploy_via_console(args.host, args.port, args.password, pub_key):
            print()
            print('[成功] SSH 公钥已配置！')
            print(f'  现在可以免密登录: ssh root@{args.host}')
        else:
            print('[失败] 部署失败')
            sys.exit(1)


if __name__ == '__main__':
    main()
