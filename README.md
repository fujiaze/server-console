# Server Console — 加密远程服务器管理工具

[English](./README_EN.md) | **中文**

一个轻量级加密远程服务器管理工具，用加密控制台通道替代繁琐的 SSH 操作。专为 AI 辅助服务器运维设计。

## 功能特性

- **AES-256-CBC 加密通信** — 所有流量加密，无明文传输
- **HMAC-SHA256 认证** — PBKDF2 密钥派生（10 万次迭代）
- **IP 白名单** — 限制只有受信任的客户端 IP 可连接（支持 CIDR）
- **暴力破解防护** — 5 次认证失败后自动封禁该 IP 15 分钟
- **流式命令执行** — 长命令实时输出 stdout/stderr，AI 可监控进度
- **文件传输** — 上传/下载带 SHA-256 完整性校验
- **审计日志** — 所有操作自动记录，按天轮转，保留 30 天
- **空闲超时** — 30 分钟无操作自动断开
- **一键安装** — 通用安装脚本，兼容所有主流 Linux 发行版
- **AI Skill 集成** — AI 可通过控制台直接操作服务器

## 快速开始

### 1. 在服务器上安装

```bash
# 一键安装（推荐）
curl -sSL https://github.com/fujiaze/server-console/raw/main/install.sh | bash

# 或从本地副本安装
bash install.sh
```

安装脚本会自动：
1. 检测 Linux 发行版，使用对应包管理器安装依赖（python3、cryptography）
2. 交互式引导设置口令、端口、IP 白名单
3. 安装并启动 systemd 服务

### 2. 在本地配置客户端

```bash
# 首次运行 — 交互式配置连接信息
python local_console.py

# 执行远程命令
python local_console.py --exec "ls -la /var/log"

# 流式执行长命令（实时输出）
python local_console.py --stream "apt update && apt upgrade -y"

# 上传文件
python local_console.py --upload script.sh /tmp/script.sh

# 交互模式
python local_console.py
```

### 3. 安装 AI Skill（重要）

安装 AI Skill 后，AI 可以在 TRAE IDE 中直接帮你管理服务器——执行命令、传输文件、部署代码、排查故障，全部通过加密通道完成。

**安装方法：**

将仓库中的 `skills/server-console/SKILL.md` 复制到 TRAE 工作区的 `.trae/skills/` 目录：

```bash
# 在你的 TRAE 工作区根目录执行
mkdir -p .trae/skills/server-console
cp skills/server-console/SKILL.md .trae/skills/server-console/SKILL.md
```

或者从 GitHub 直接下载：

```bash
mkdir -p .trae/skills/server-console
curl -sSL https://github.com/fujiaze/server-console/raw/main/skills/server-console/SKILL.md \
  -o .trae/skills/server-console/SKILL.md
```

**安装后效果：**

- 当你告诉 AI "帮我查看服务器状态"、"重启服务"、"上传代码到服务器" 时，AI 会自动调用本工具
- AI 先用 `--ping` 检测连接，再执行操作
- 长命令自动使用流式模式，AI 实时监控输出
- 首次使用时，AI 会引导你完成 agent 部署和客户端配置

> **注意：** Skill 文件安装后，AI 需要重新加载或新开会话才能识别。

## 文件说明

| 文件 | 说明 |
|------|------|
| `server_agent.py` | 服务器端守护进程（以 root 运行，监听 9999 端口） |
| `local_console.py` | 客户端控制台（交互式 REPL + 命令行模式） |
| `config_manager.py` | 配置管理（PBKDF2 口令哈希、配置读写、首次引导） |
| `install.sh` | 通用一键安装脚本（所有 Linux 发行版） |
| `setup_ssh_key.py` | SSH 密钥管理工具 |
| `deploy.py` | 部署工具 |
| `scan_privacy.py` | 隐私扫描工具（发布前检查） |
| `.env.example` | 配置示例文件 |
| `skills/server-console/SKILL.md` | AI Skill 定义文件（安装到 .trae/skills/ 后生效） |

## 安全架构

```
客户端                              服务器
  |                                   |
  |--- ASTROCONSOLE/1.0 ------------->|
  |<--------- READY + salt -----------|  (32字节随机salt)
  |                                   |
  |--- timestamp+nonce+hmac --------->|  HMAC = PBKDF2(口令, salt)
  |<--------- AUTH_OK ----------------|  (或 AUTH_FAIL / 封禁)
  |                                   |
  |=== AES-256-CBC 加密通信 ==========>|  密钥 = PBKDF2(口令, salt, 100000)
  |    [exec] [stream] [upload]       |
  |    [download] [stat] [list]       |
  |    [cancel] [ping]                |
  |===================================|
```

### 安全机制

| 机制 | 实现方式 |
|------|----------|
| 口令存储 | PBKDF2-HMAC-SHA256，10 万次迭代，配置文件 0600 权限 |
| 通信加密 | AES-256-CBC，每条消息使用随机 IV |
| 认证 | HMAC-SHA256 + timestamp + nonce 防重放 |
| IP 白名单 | 可配置允许列表，支持 CIDR 格式 |
| 暴力破解防护 | 5 次失败 → 封禁该 IP 15 分钟 |
| 空闲超时 | 30 分钟无操作自动断开 |
| 文件完整性 | SHA-256 哈希校验（上传/下载） |
| 审计日志 | 按天轮转，保留 30 天 |

## 交互式控制台命令

```
help              显示帮助
ping              心跳检测
exec <cmd>        执行 shell 命令
stream <cmd>      流式执行长命令（实时输出）
cancel            取消正在运行的流式命令
ls <path>         列出远程目录
stat <path>       查看文件信息
upload <l> <r>    上传文件
download <r> <l>  下载文件
exit / quit       退出
```

## 支持的 Linux 发行版

| 发行版 | 包管理器 |
|--------|----------|
| Ubuntu / Debian | apt |
| CentOS / RHEL / Rocky / Alma | yum / dnf |
| Fedora | dnf |
| Alpine | apk |
| Arch Linux | pacman |
| openSUSE | zypper |

## 配置文件

### 服务器端（`/etc/astrometry/agent.conf`）
```json
{
  "host": "0.0.0.0",
  "port": 9999,
  "password_hash": "<pbkdf2_hash>",
  "password_salt": "<hex_salt>",
  "ip_whitelist": ["127.0.0.1", "10.0.0.0/8"],
  "log_path": "/var/log/astrometry-console"
}
```

### 客户端（`~/.astrometry/console.conf`）
```json
{
  "host": "your-server-ip",
  "port": 9999,
  "password": "your-password"
}
```

## 卸载

```bash
bash install.sh --uninstall
```

## 公网部署安全提示

> 虽然本工具实现了多层安全机制，但暴露在公网仍有风险。强烈建议：
> 1. 优先使用 VPN/SSH 隧道访问，不直接暴露 9999 端口
> 2. 如必须公网暴露，务必配置严格 IP 白名单 + 防火墙
> 3. 使用强口令（建议 20+ 字符随机字符串）
> 4. 定期检查审计日志，关注异常连接

## 详细文档

完整的部署、使用、运维文档请参见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

## 许可证

MIT
