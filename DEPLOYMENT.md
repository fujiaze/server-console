# 部署与使用详细指南

本文档详细说明服务器控制台工具的完整部署流程，从开发机环境准备到服务器部署再到日常使用。

---

## 目录

1. [开发机环境准备（Windows）](#1-开发机环境准备windows)
2. [GitHub 仓库发布](#2-github-仓库发布)
3. [服务器端部署](#3-服务器端部署)
4. [客户端配置与使用](#4-客户端配置与使用)
5. [AI Skill 集成](#5-ai-skill-集成)
6. [安全最佳实践](#6-安全最佳实践)
7. [日常运维](#7-日常运维)
8. [故障排除](#8-故障排除)
9. [卸载与清理](#9-卸载与清理)

---

## 1. 开发机环境准备（Windows）

### 1.1 安装 Git

```powershell
# 方式 A：winget 安装（推荐）
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements

# 方式 B：手动下载
# 访问 https://git-scm.com/download/win 下载安装
```

验证安装：
```powershell
git --version
# 应输出: git version 2.x.x.windows.x
```

### 1.2 安装 GitHub CLI

```powershell
# 方式 A：winget 安装（可能需要 UAC 提权）
winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements

# 方式 B：便携版（免安装，无需管理员权限）
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "https://github.com/cli/cli/releases/latest/download/gh_2.95.0_windows_amd64.zip" -OutFile "$env:TEMP\gh.zip"
Expand-Archive -Path "$env:TEMP\gh.zip" -DestinationPath "$env:LOCALAPPDATA\gh-cli" -Force
# 加入 PATH
$ghPath = "$env:LOCALAPPDATA\gh-cli\bin"
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$ghPath", "User")
```

验证安装：
```powershell
gh --version
# 应输出: gh version 2.x.x
```

### 1.3 配置 Git 用户信息

```powershell
# 设置全局用户名和邮箱（用于 commit 署名）
git config --global user.name "你的名字"
git config --global user.email "your-email@example.com"

# 可选：配置默认分支名
git config --global init.defaultBranch main
```

---

## 2. GitHub 仓库发布

### 2.1 认证 GitHub CLI

```powershell
gh auth login
```

按交互提示操作：
1. **What account do you want to log into?** → `GitHub.com`
2. **What is your preferred protocol for Git operations?** → `HTTPS`
3. **Authenticate Git with your GitHub credentials?** → `Yes`
4. **How would you like to authenticate?** → `Login with a web browser`
5. 复制屏幕显示的一次性代码（如 `XXXX-XXXX`）
6. 浏览器自动打开，粘贴代码并授权

验证认证：
```powershell
gh auth status
# 应输出: ✓ Logged in to github.com as fujiaze
```

### 2.2 初始化本地仓库

```powershell
cd C:\Users\你的用户名\Desktop\TRAE

# 初始化 git 仓库
git init

# 检查将要提交的文件（确保无隐私泄露）
git add .
git status
```

**预期将被跟踪的文件（共 11 个）：**
- `.env.example`
- `.gitignore`
- `CHANGELOG.md`
- `DEPLOYMENT.md`
- `README.md`
- `config_manager.py`
- `deploy.py`
- `install.sh`
- `local_console.py`
- `scan_privacy.py`
- `server_agent.py`
- `setup_ssh_key.py`

> **如果出现其他文件（尤其是 .conf、.env、.pem、README_server_console.md、ASTROMETRY_DEPLOYMENT_GUIDE.md），说明 .gitignore 配置有误，需立即检查。**

### 2.3 隐私扫描

```powershell
python scan_privacy.py
```

确保输出 `[PASS] 未发现敏感信息`。

### 2.4 首次提交并推送

```powershell
# 创建首次提交
git commit -m "Initial release: encrypted server console v2.0.0

- AES-256-CBC encrypted communication (mandatory)
- PBKDF2-HMAC-SHA256 password hashing (100k iterations)
- HMAC-SHA256 authentication with timestamp+nonce anti-replay
- IP whitelist with CIDR support
- Brute-force protection (5 failures -> 15-min ban)
- Idle timeout (30 min)
- Audit logging with daily rotation (30-day retention)
- SHA-256 file integrity verification
- Streaming command execution
- Universal one-click installer for all Linux distros
- AI Skill integration for AI-assisted server management"

# 创建公开仓库并推送（仓库名可自定义）
gh repo create server-console --public --source=. --push --description "Encrypted remote server management console with AI Skill support"

# 或者创建私有仓库
gh repo create server-console --private --source=. --push --description "Encrypted remote server management console"
```

推送成功后，仓库地址为：`https://github.com/fujiaze/server-console`

### 2.5 后续更新推送

```powershell
# 修改代码后
git add .
git commit -m "feat: 描述你的改动"
git push
```

---

## 3. 服务器端部署

### 3.1 一键安装（推荐）

在任意 Linux 服务器上执行：

```bash
# 从 GitHub 一键安装
curl -sSL https://github.com/fujiaze/server-console/raw/main/install.sh | bash
```

安装脚本会自动：
1. 检测 Linux 发行版（Ubuntu/Debian/CentOS/RHEL/Alpine/Arch/Fedora/openSUSE）
2. 使用对应包管理器安装 `python3`、`pip`、`cryptography`
3. 部署 `server_agent.py` 和 `config_manager.py` 到 `/root/`
4. 交互式引导设置：监听地址、端口、控制台口令（需输入两次）、IP 白名单、日志路径
5. 创建 systemd 服务 `astrometry-agent.service` 并启动

### 3.2 手动安装

```bash
# 1. 安装依赖
# Ubuntu/Debian
apt update && apt install -y python3 python3-pip
pip3 install cryptography

# CentOS/RHEL
yum install -y python3 python3-pip
pip3 install cryptography

# Alpine
apk add python3 py3-pip
pip3 install cryptography

# 2. 下载脚本
curl -sSL https://github.com/fujiaze/server-console/raw/main/server_agent.py -o /root/server_agent.py
curl -sSL https://github.com/fujiaze/server-console/raw/main/config_manager.py -o /root/config_manager.py

# 3. 首次配置
python3 /root/server_agent.py --setup

# 4. 安装 systemd 服务（脚本会自动处理）
```

### 3.3 服务管理

```bash
# 启动 / 停止 / 重启
systemctl start astrometry-agent
systemctl stop astrometry-agent
systemctl restart astrometry-agent

# 查看状态
systemctl status astrometry-agent

# 查看日志
journalctl -u astrometry-agent -f

# 查看审计日志
ls -la /var/log/astrometry-console/
tail -f /var/log/astrometry-console/audit.log
```

### 3.4 防火墙配置（公网部署时必需）

```bash
# Ubuntu/Debian (ufw)
ufw allow from <你的IP> to any port 9999
ufw deny 9999

# CentOS/RHEL (firewalld)
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<你的IP>/32" port port=9999 protocol=tcp accept'
firewall-cmd --permanent --remove-port=9999/tcp
firewall-cmd --reload

# iptables
iptables -A INPUT -p tcp --dport 9999 -s <你的IP> -j ACCEPT
iptables -A INPUT -p tcp --dport 9999 -j DROP
```

---

## 4. 客户端配置与使用

### 4.1 首次配置

```bash
python local_console.py
# 首次运行会交互式引导：
# 1. 输入服务器地址
# 2. 输入端口（默认 9999）
# 3. 输入控制台口令（需输入两次）
# 配置保存到 ~/.astrometry/console.conf
```

### 4.2 单命令模式

```bash
# 心跳检测
python local_console.py --ping

# 执行命令（等待结果）
python local_console.py --exec "ls -la /var/log"

# 流式执行长命令（实时输出）
python local_console.py --stream "apt update && apt upgrade -y"
python local_console.py --stream "tail -f /var/log/syslog"

# 上传文件
python local_console.py --upload script.sh /tmp/script.sh

# 下载文件
python local_console.py --download /var/log/syslog ./syslog.log

# 列出远程目录
python local_console.py --ls /usr/local/astrometry/data

# 指定临时服务器/口令
python local_console.py --host 192.168.x.x --password 'your-pass' --ping
```

### 4.3 交互模式

```bash
python local_console.py
```

进入交互式 REPL 后可用命令：

| 命令 | 说明 |
|------|------|
| `help` | 显示帮助 |
| `ping` | 心跳检测 |
| `exec <cmd>` | 执行命令 |
| `stream <cmd>` | 流式执行长命令 |
| `cancel` | 取消正在运行的流式命令 |
| `ls <path>` | 列出远程目录 |
| `stat <path>` | 查看文件信息 |
| `upload <local> <remote>` | 上传文件 |
| `download <remote> <local>` | 下载文件 |
| `exit` / `quit` | 退出 |

### 4.4 流式执行示例

流式模式适合长时间运行的命令，实时显示输出：

```bash
python local_console.py
> stream apt update && apt upgrade -y
# 实时看到 apt 的输出
# 如需中断，在另一个终端运行：
# python local_console.py --exec "" # 或在交互模式输入 cancel
```

---

## 5. AI Skill 集成

本工具配套提供 TRAE AI Skill，让 AI 在用户人工帮助下部署 agent 后，直接通过控制台操作服务器。

### 5.1 Skill 文件位置

Skill 文件位于 `.trae/skills/server-console/SKILL.md`（注意：.trae 目录不会上传到 GitHub，需在本地保留）。

### 5.2 AI 能做的事

- **连接检测**：`python local_console.py --ping`
- **执行命令**：`python local_console.py --exec "命令"`
- **流式执行**：`python local_console.py --stream "长命令"`
- **文件传输**：`python local_console.py --upload/--download`
- **服务管理**：通过 exec 执行 systemctl 命令
- **首次部署指导**：引导用户在服务器上执行 install.sh

### 5.3 AI 使用注意事项

- AI 应先 `--ping` 确认连接，再执行其他操作
- 长命令使用 `--stream` 模式，避免超时
- PowerShell 环境下，命令中的 `$` 变量需用单引号包裹避免插值
- 文件传输完成后检查 SHA-256 校验结果

---

## 6. 安全最佳实践

### 6.1 公网部署检查清单

- [ ] 修改默认口令为强口令（16+ 字符，含大小写数字符号）
- [ ] IP 白名单设置为你的固定 IP（不要用 0.0.0.0/0）
- [ ] 防火墙限制 9999 端口只允许白名单 IP
- [ ] 确认审计日志正常记录
- [ ] 确认暴力破解防护生效（故意输错 5 次测试封禁）
- [ ] 确认空闲超时生效（30 分钟无操作断开）

### 6.2 口令安全

- 口令以 PBKDF2-HMAC-SHA256 哈希存储（10 万次迭代）
- 口令不出现在命令行参数（避免进程列表泄露）
- 配置文件权限 0600
- 修改口令：在服务器上重新运行 `python3 /root/server_agent.py --setup`

### 6.3 通信安全

- AES-256-CBC 加密所有通信
- 每条消息使用随机 IV
- HMAC-SHA256 认证 + timestamp + nonce 防重放
- 文件传输有 SHA-256 完整性校验

### 6.4 安全警告

> **公网部署风险提示**：虽然本工具实现了多层安全机制，但暴露在公网仍有风险。强烈建议：
> 1. 优先使用 VPN/SSH 隧道访问，不直接暴露 9999 端口
> 2. 如必须公网暴露，务必配置严格 IP 白名单 + 防火墙
> 3. 定期检查审计日志，关注异常连接
> 4. 使用强口令（建议 20+ 字符随机字符串）

---

## 7. 日常运维

### 7.1 查看审计日志

```bash
# 在服务器上
ls -la /var/log/astrometry-console/
# audit.log          当前日志
# audit.log.2026-06-24  昨天的日志（自动轮转）

# 实时查看
tail -f /var/log/astrometry-console/audit.log

# 通过控制台查看
python local_console.py --exec "tail -50 /var/log/astrometry-console/audit.log"
```

### 7.2 更新 Agent 代码

```bash
# 客户端上传新版本
python local_console.py --upload server_agent.py /root/server_agent.py
python local_console.py --upload config_manager.py /root/config_manager.py

# 重启服务
python local_console.py --exec "systemctl restart astrometry-agent"

# 验证
python local_console.py --ping
```

### 7.3 修改配置

```bash
# 修改口令/端口/白名单
python local_console.py --exec "python3 /root/server_agent.py --setup"

# 或直接编辑配置文件
python local_console.py --exec "vi /etc/astrometry/agent.conf"
python local_console.py --exec "systemctl restart astrometry-agent"
```

---

## 8. 故障排除

### 8.1 连接被拒绝

```
[连接失败] [WinError 10061] 由于目标计算机积极拒绝
```

**原因**：服务器上 agent 未运行或端口被防火墙拦截。

**解决**：
1. 检查服务状态：`python local_console.py --exec "systemctl status astrometry-agent"`
2. 检查端口监听：`python local_console.py --exec "ss -tlnp | grep 9999"`
3. 检查防火墙：`python local_console.py --exec "ufw status"` 或 `firewall-cmd --list-all`

### 8.2 认证失败

```
[认证失败] 口令错误或被拒绝
```

**原因**：口令不匹配，或 IP 被封禁。

**解决**：
1. 确认客户端配置 `~/.astrometry/console.conf` 中口令正确
2. 检查是否被暴力破解防护封禁（等 15 分钟或重启服务）
3. 在服务器上重置：`python3 /root/server_agent.py --setup`

### 8.3 IP 被封禁

```
[连接失败] 连接被拒绝（IP 不在白名单或已被封禁）
```

**解决**：
1. 确认客户端 IP 在服务器白名单中
2. 如被封禁，在服务器上重启服务清除封禁：`systemctl restart astrometry-agent`
3. 检查审计日志确认封禁原因

### 8.4 cryptography 库未安装

```
[FATAL] cryptography 库未安装，请运行: pip install cryptography
```

**解决**：
```bash
# 服务器上安装
python local_console.py --exec "pip3 install cryptography"
python local_console.py --exec "systemctl restart astrometry-agent"
```

### 8.5 流式命令无输出

**原因**：命令本身无输出，或缓冲区未刷新。

**解决**：
1. 确认命令在服务器上直接执行有输出
2. 尝试加 `--line-buffered` 或 `stdbuf -oL`
3. 使用 `cancel` 命令中断后重试

### 8.6 文件校验失败

```
[错误] SHA-256 校验失败！
  本地: xxxxx
  远程: yyyyy
```

**原因**：网络传输中断或文件被修改。

**解决**：重新上传/下载文件。

---

## 9. 卸载与清理

### 9.1 服务器端卸载

```bash
# 方式 A：使用安装脚本卸载
bash install.sh --uninstall

# 方式 B：手动卸载
systemctl stop astrometry-agent
systemctl disable astrometry-agent
rm -f /etc/systemd/system/astrometry-agent.service
systemctl daemon-reload
rm -f /root/server_agent.py /root/config_manager.py
rm -rf /etc/astrometry/
rm -rf /var/log/astrometry-console/
```

### 9.2 客户端清理

```bash
# 删除客户端配置
rm -rf ~/.astrometry/
```

### 9.3 GitHub 仓库删除

```bash
gh repo delete fujiaze/server-console --yes
```

---

## 附录：文件清单

| 文件 | 用途 | 是否上传 GitHub |
|------|------|----------------|
| `server_agent.py` | 服务器端守护进程 | ✅ |
| `local_console.py` | 客户端控制台 | ✅ |
| `config_manager.py` | 配置管理（PBKDF2 哈希） | ✅ |
| `install.sh` | 通用一键安装脚本 | ✅ |
| `setup_ssh_key.py` | SSH 密钥管理工具 | ✅ |
| `deploy.py` | 部署工具 | ✅ |
| `scan_privacy.py` | 隐私扫描工具 | ✅ |
| `.env.example` | 配置示例 | ✅ |
| `README.md` | 项目说明 | ✅ |
| `CHANGELOG.md` | 版本变更记录 | ✅ |
| `DEPLOYMENT.md` | 本文档 | ✅ |
| `.gitignore` | Git 忽略规则 | ✅ |
| `/etc/astrometry/agent.conf` | 服务器配置（含口令哈希） | ❌ |
| `~/.astrometry/console.conf` | 客户端配置（含明文口令） | ❌ |

---

## 许可证

MIT License — 可自由使用、修改、分发。
