#!/usr/bin/env python3
"""
配置管理模块
管理服务器端和客户端的配置文件，提供口令哈希、配置读写、首次运行引导等功能。

安全特性：
- PBKDF2-HMAC-SHA256 口令哈希（10万次迭代）
- 配置文件权限 0600
- 不含任何真实 IP/口令/主机名，默认值一律使用占位符

配置文件路径：
- 服务器端：/etc/astrometry/agent.conf
- 客户端：~/.astrometry/console.conf

配置文件格式：JSON
- 服务器端：host, port, password_hash, password_salt, ip_whitelist, log_path
- 客户端：host, port, password
"""

from __future__ import annotations

import os
import json
import hmac
import hashlib
import getpass
from pathlib import Path

# ==================== 常量 ====================

PBKDF2_ITERATIONS = 100000
DKLEN = 32

SERVER_CONFIG_PATH = '/etc/astrometry/agent.conf'
CLIENT_CONFIG_PATH = '~/.astrometry/console.conf'

DEFAULT_SERVER_CONFIG = {
    'host': '0.0.0.0',
    'port': 9999,
    'password_hash': '',
    'password_salt': '',
    'ip_whitelist': ['127.0.0.1'],
    'log_path': '/var/log/astrometry-console',
}

DEFAULT_CLIENT_CONFIG = {
    'host': '127.0.0.1',
    'port': 9999,
    'password': 'CHANGE_ME',
}


# ==================== 口令哈希 ====================

def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """生成口令的 PBKDF2 哈希，返回 (hash_hex, salt_hex)"""
    if salt is None:
        salt = os.urandom(32)
    derived = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt,
        PBKDF2_ITERATIONS, dklen=DKLEN,
    )
    return derived.hex(), salt.hex()


def verify_password(password: str, password_hash_hex: str, password_salt_hex: str) -> bool:
    """验证口令是否与存储的哈希匹配"""
    try:
        salt = bytes.fromhex(password_salt_hex)
        expected = bytes.fromhex(password_hash_hex)
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt,
        PBKDF2_ITERATIONS, dklen=DKLEN,
    )
    return hmac.compare_digest(derived, expected)


def derive_key(password: str, salt_hex: str) -> bytes:
    """从口令和盐派生密钥（用于 HMAC 认证和 AES 加密）"""
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt,
        PBKDF2_ITERATIONS, dklen=DKLEN,
    )


# ==================== 配置读写 ====================

def load_config(path: str) -> dict | None:
    """加载配置文件，不存在或格式错误返回 None"""
    p = Path(path).expanduser()
    if not p.exists():
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_config(path: str, config: dict) -> None:
    """保存配置文件，权限设为 0600"""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(p, 0o600)
    except OSError:
        # Windows 等不支持 chmod 的环境下忽略
        pass


# ==================== 首次运行引导 ====================

def first_run_setup(path: str, is_server: bool = True) -> dict:
    """首次运行交互式引导，生成配置文件并返回配置字典"""
    p = Path(path).expanduser()

    if is_server:
        config = dict(DEFAULT_SERVER_CONFIG)
        print('=== 服务器端首次配置 ===')
        host = input(f'监听地址 [{config["host"]}]: ').strip()
        if host:
            config['host'] = host
        port_str = input(f'监听端口 [{config["port"]}]: ').strip()
        if port_str:
            try:
                config['port'] = int(port_str)
            except ValueError:
                print('[警告] 端口无效，使用默认值')

        while True:
            pw1 = getpass.getpass('设置控制台口令: ')
            if not pw1:
                print('[错误] 口令不能为空')
                continue
            pw2 = getpass.getpass('再次输入口令: ')
            if pw1 != pw2:
                print('[错误] 两次输入不一致，请重试')
                continue
            break

        h, s = hash_password(pw1)
        config['password_hash'] = h
        config['password_salt'] = s

        wl = input(
            f'IP 白名单（逗号分隔，回车使用默认 {",".join(config["ip_whitelist"])}）: '
        ).strip()
        if wl:
            config['ip_whitelist'] = [x.strip() for x in wl.split(',') if x.strip()]

        log_path = input(f'审计日志路径 [{config["log_path"]}]: ').strip()
        if log_path:
            config['log_path'] = log_path
    else:
        config = dict(DEFAULT_CLIENT_CONFIG)
        print('=== 客户端首次配置 ===')
        host = input(f'服务器地址 [{config["host"]}]: ').strip()
        if host:
            config['host'] = host
        port_str = input(f'服务器端口 [{config["port"]}]: ').strip()
        if port_str:
            try:
                config['port'] = int(port_str)
            except ValueError:
                print('[警告] 端口无效，使用默认值')
        while True:
            pw = getpass.getpass('控制台口令: ')
            if not pw:
                print('[错误] 口令不能为空')
                continue
            pw2 = getpass.getpass('再次输入口令: ')
            if pw != pw2:
                print('[错误] 两次输入不一致，请重试')
                continue
            break
        config['password'] = pw

    save_config(path, config)
    print(f'[完成] 配置已保存到 {p}')
    return config
