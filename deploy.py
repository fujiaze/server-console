#!/usr/bin/env python3
"""
一键部署工具
将 server_agent.py 部署到服务器并安装为系统服务

三种部署方式：
1. 自动部署（需要 paramiko 库 + SSH 密码）
2. 生成粘贴命令（用户 SSH 密码登录后粘贴执行）
3. 手动上传（用户自行上传文件后执行安装命令）

用法：
    python deploy.py --method auto --ssh-password 'xxx'
    python deploy.py --method paste                    # 生成粘贴命令
    python deploy.py --method manual                    # 显示手动步骤
"""

import os
import sys
import base64
import argparse
from pathlib import Path

try:
    import config_manager
except ImportError:
    config_manager = None

# ==================== 配置 ====================
# 默认值从客户端配置文件读取，不存在时使用占位符

_client_cfg = {}
if config_manager:
    _client_cfg = config_manager.load_config(config_manager.CLIENT_CONFIG_PATH) or {}

SERVER_HOST = _client_cfg.get('host', '127.0.0.1')
CONSOLE_PORT = _client_cfg.get('port', 9999)
CONSOLE_PASSWORD = _client_cfg.get('password', 'CHANGE_ME')
SSH_USER = 'root'
AGENT_REMOTE_PATH = '/root/server_agent.py'


def generate_paste_command(agent_path: str, password: str) -> str:
    """
    生成一条可粘贴到服务器终端的命令
    将 server_agent.py 的内容 base64 编码，在服务器上解码并安装
    """
    with open(agent_path, 'rb') as f:
        content = f.read()

    b64 = base64.b64encode(content).decode()

    # 分段拼接（避免单行过长）
    # bash 可以处理长行，但为了可读性分成多段
    cmd = f"""# === Astrometry Server Agent 部署命令 ===
# 在服务器终端粘贴执行即可

# 1. 写入 agent 脚本
echo '{b64}' | base64 -d > {AGENT_REMOTE_PATH}

# 2. 安装 cryptography 库
pip3 install cryptography -q 2>/dev/null

# 3. 首次运行交互式配置口令（设置控制台口令、IP白名单等）
python3 {AGENT_REMOTE_PATH} --setup

# 4. 安装并启动 systemd 服务（口令从配置文件读取，无需命令行传递）
python3 {AGENT_REMOTE_PATH} --install

# 5. 检查状态
systemctl status astrometry-console --no-pager

# === 部署完成后，控制台端口 {CONSOLE_PORT} 将可用 ===
# === 在本地运行: python local_console.py 即可连接 ===
"""

    return cmd


def auto_deploy_paramiko(host: str, ssh_password: str, agent_path: str, console_password: str) -> bool:
    """使用 paramiko 自动部署"""
    try:
        import paramiko
    except ImportError:
        print('[错误] 需要安装 paramiko: pip install paramiko')
        return False

    print(f'[部署] 连接 {host} ...')

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(host, username=SSH_USER, password=ssh_password, timeout=15)
        print(f'[已连接] {host}')
    except Exception as e:
        print(f'[连接失败] {e}')
        return False

    try:
        # 上传 agent 脚本
        print(f'[上传] {agent_path} -> {AGENT_REMOTE_PATH}')
        sftp = ssh.open_sftp()
        sftp.put(agent_path, AGENT_REMOTE_PATH)
        sftp.close()
        print('[完成] 文件上传')

        # 安装 cryptography
        print('[安装] cryptography 库...')
        stdin, stdout, stderr = ssh.exec_command('pip3 install cryptography -q 2>&1')
        print(stdout.read().decode().strip())

        # 安装 systemd 服务（口令从配置文件读取，需先完成 --setup）
        print('[安装] systemd 服务...')
        print('[提示] 服务器需先运行 "python3 {} --setup" 完成口令配置'.format(AGENT_REMOTE_PATH))
        cmd = f"python3 {AGENT_REMOTE_PATH} --install"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out:
            print(out)
        if err:
            print(f'[stderr] {err}')

        # 检查状态
        print('[检查] 服务状态...')
        stdin, stdout, stderr = ssh.exec_command('systemctl is-active astrometry-console')
        status = stdout.read().decode().strip()

        if status == 'active':
            print(f'\n[成功] Agent 已部署并运行！')
            print(f'  控制台端口: {CONSOLE_PORT}')
            print(f'  现在可以运行: python local_console.py')
            return True
        else:
            print(f'[警告] 服务状态: {status}')
            print('  请检查: systemctl status astrometry-console')
            return False

    except Exception as e:
        print(f'[错误] {e}')
        return False
    finally:
        ssh.close()


def show_manual_steps(agent_path: str, password: str):
    """显示手动部署步骤"""
    print("""
╔══════════════════════════════════════════════════════╗
║              手动部署步骤                             ║
╠══════════════════════════════════════════════════════╣

1. 将 server_agent.py 和 config_manager.py 上传到服务器 /root/
   方式不限：阿里云控制台、FTP、U盘等

2. SSH 登录服务器，执行以下命令：

   pip3 install cryptography
   python3 /root/server_agent.py --setup    # 交互式设置口令和配置
   python3 /root/server_agent.py --install  # 安装 systemd 服务

3. 验证服务状态：

   systemctl status astrometry-console

4. 在本地连接控制台：

   python local_console.py

╚══════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(description='一键部署 Server Agent')
    parser.add_argument('--method', choices=['auto', 'paste', 'manual'],
                        default='paste', help='部署方式')
    parser.add_argument('--host', default=SERVER_HOST, help='服务器地址')
    parser.add_argument('--ssh-password', help='SSH 密码（auto 方式需要）')
    parser.add_argument('--console-password', default=CONSOLE_PASSWORD,
                        help='控制台口令')
    parser.add_argument('--agent-path', default=str(Path(__file__).parent / 'server_agent.py'),
                        help='server_agent.py 路径')
    parser.add_argument('--save', default='deploy_command.txt',
                        help='保存粘贴命令到文件')
    args = parser.parse_args()

    agent_path = Path(args.agent_path)
    if not agent_path.exists():
        print(f'[错误] 找不到 {agent_path}')
        sys.exit(1)

    if args.method == 'auto':
        if not args.ssh_password:
            print('[错误] auto 方式需要 --ssh-password 参数')
            sys.exit(1)
        auto_deploy_paramiko(args.host, args.ssh_password, str(agent_path), args.console_password)

    elif args.method == 'paste':
        cmd = generate_paste_command(str(agent_path), args.console_password)

        # 保存到文件
        with open(args.save, 'w', encoding='utf-8') as f:
            f.write(cmd)
        print(f'[已保存] 部署命令已保存到 {args.save}')
        print()
        print('=== 部署步骤 ===')
        print(f'1. SSH 密码登录服务器: ssh {SSH_USER}@{args.host}')
        print(f'2. 复制 {args.save} 的全部内容')
        print(f'3. 粘贴到服务器终端执行')
        print(f'4. 部署完成后，在本地运行: python local_console.py')
        print()
        print('=== 命令预览（前500字符）===')
        print(cmd[:500] + '\n... (完整内容见文件)')

    elif args.method == 'manual':
        show_manual_steps(str(agent_path), args.console_password)


if __name__ == '__main__':
    main()
