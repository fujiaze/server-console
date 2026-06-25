---
name: "server-console"
description: "通过加密控制台通道远程管理服务器。当用户需要操作、管理、部署到远程 Linux 服务器，或 AI 需要在远程服务器上执行命令、传输文件、管理服务时调用此技能。Invoke when user asks to operate, manage, deploy to, or troubleshoot a remote Linux server, or when AI needs to execute commands, transfer files, or manage services on a remote server."
---

# Server Console — 服务器远程管理技能

本技能让 AI 通过加密控制台通道（`local_console.py`）远程管理 Linux 服务器。AI 可以执行命令、传输文件、管理服务，并指导用户完成首次部署。

## 前置条件

- 工作目录中存在 `local_console.py`
- 服务器上已部署并运行 `server_agent.py`（控制端 agent）
- 客户端配置已设置（运行一次 `python local_console.py` 即可引导配置，配置保存在 `~/.astrometry/console.conf`）

## 快速参考

### 1. 连接检测（Ping）
```bash
python local_console.py --ping
```
验证 agent 是否运行、控制台通道是否正常。返回主机名和运行时间。

### 2. 执行命令（非流式）
```bash
python local_console.py --exec "ls -la /var/log"
```
在服务器上执行 shell 命令，返回 stdout/stderr/returncode。适用于 5 分钟内完成的快速命令。

**注意：** PowerShell 环境下 `$` 变量会被插值，需用单引号包裹：
```powershell
# 正确 - 单引号阻止 PowerShell 解析 $s
python local_console.py --exec 'echo $HOME'
```

### 3. 流式执行长命令
```bash
python local_console.py --stream "apt update && apt upgrade -y"
```
实时流式输出 stdout/stderr。适用于长时间运行的命令（下载、编译、安装）。AI 可监控进度并决定是否需要干预。

### 4. 上传文件
```bash
python local_console.py --upload local_file.py /remote/path/file.py
```
上传本地文件到服务器，带 SHA-256 完整性校验，显示进度条。

### 5. 下载文件
```bash
python local_console.py --download /remote/path/file.txt local_file.txt
```
下载远程文件到本地，带 SHA-256 完整性校验。

### 6. 交互模式
```bash
python local_console.py
```
打开交互式 REPL，可用命令：`help`、`ping`、`exec <cmd>`、`stream <cmd>`、`cancel`、`ls <path>`、`stat <path>`、`upload <l> <r>`、`download <r> <l>`、`exit`。

## 常见操作模板

### 部署/更新服务器代码
```bash
# 上传新的 API 服务器代码
python local_console.py --upload my_app.py /opt/app/my_app.py
# 重启服务
python local_console.py --exec "systemctl restart my-app"
# 检查状态
python local_console.py --exec "systemctl status my-app --no-pager | head -10"
```

### 查看服务日志
```bash
python local_console.py --exec "journalctl -u my-app --no-pager -n 50"
```

### 检查磁盘空间和内存
```bash
python local_console.py --exec "df -h / && echo '---' && free -m"
```

### 安装软件包
```bash
python local_console.py --stream "apt update && apt install -y <package>"
```

### 上传并运行脚本
```bash
# 上传脚本
python local_console.py --upload my_script.sh /tmp/my_script.sh
# 赋予执行权限并运行
python local_console.py --exec "chmod +x /tmp/my_script.sh && bash /tmp/my_script.sh"
```

### 检查服务状态
```bash
python local_console.py --exec "systemctl status astrometry-agent --no-pager"
python local_console.py --exec "ss -tlnp | grep 9999"
```

## 首次部署指导

如果服务器尚未安装 agent，按以下步骤引导用户：

### 步骤 1：在服务器上安装 agent

引导用户在服务器上执行一键安装脚本：
```bash
curl -sSL https://github.com/fujiaze/server-console/raw/main/install.sh | bash
```

安装脚本会自动：
- 检测 Linux 发行版并安装依赖（python3、cryptography）
- 部署 agent 脚本到 `/root/`
- 交互式引导设置口令、端口、IP 白名单
- 安装并启动 systemd 服务

### 步骤 2：配置客户端

在本地执行：
```bash
python local_console.py
```
首次运行会提示输入服务器 IP、端口、口令，配置保存到 `~/.astrometry/console.conf`。

### 步骤 3：验证连接
```bash
python local_console.py --ping
```

### 步骤 4：AI 接管

连接成功后，AI 即可通过 `--exec`、`--stream`、`--upload`、`--download` 等命令远程管理服务器。

## PowerShell 变量插值警告

在 PowerShell 中使用 `--exec` 或 `--stream` 时，`$` 字符会被当作 PowerShell 变量解析。使用**单引号**可原样传递：

```powershell
# 错误 - PowerShell 会解析 $s
python local_console.py --exec "echo $s"

# 正确 - 单引号将 $s 原样传递给 bash
python local_console.py --exec 'echo $s'
```

对于同时包含单引号和双引号的复杂脚本，建议上传为文件后在服务器上执行。

## 流式命令使用建议

AI 使用流式命令时的最佳实践：
1. **长命令用流式**：下载、编译、安装等耗时命令使用 `--stream`，避免超时
2. **监控输出**：实时观察输出，发现错误可及时干预
3. **取消机制**：如需中断，使用交互模式的 `cancel` 命令
4. **超时处理**：非流式命令默认超时 300 秒，超时后可改用流式

## 故障排除

- **连接被拒绝**：Agent 未运行。引导用户在服务器上执行 `systemctl start astrometry-agent`
- **认证失败**：口令不匹配。引导用户重新运行 `python local_console.py`（首次配置）
- **超时**：命令执行时间过长。改用 `--stream` 流式执行
- **权限不足**：Agent 可能未以 root 运行。确认 systemd 服务配置 `User=root`
- **IP 被封禁**：连续 5 次认证失败会触发封禁（15 分钟）。等待或重启服务清除
- **cryptography 未安装**：执行 `pip3 install cryptography` 并重启 agent
