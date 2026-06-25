# Server Console — Encrypted Remote Server Management Tool

A lightweight, encrypted remote server management tool that replaces cumbersome SSH sessions with a secure console channel. Designed for AI-assisted server operations.

## Features

- **AES-256-CBC encrypted communication** — All traffic encrypted, no plaintext over the wire
- **HMAC-SHA256 authentication** — PBKDF2 key derivation (100,000 iterations)
- **IP whitelist** — Restrict access to trusted client IPs
- **Brute-force protection** — Auto-ban after 5 failed auth attempts (15 min)
- **Streaming command execution** — Real-time stdout/stderr for long-running commands
- **File transfer** — Upload/download with SHA-256 integrity verification
- **Audit logging** — All operations logged with rotation (30-day retention)
- **Idle timeout** — Auto-disconnect after 30 minutes of inactivity
- **One-click install** — Universal installer for all major Linux distributions
- **AI Skill compatible** — AI can operate servers directly through the console

## Quick Start

### Install on Server

```bash
# Download and run the installer
curl -sSL https://github.com/YOUR_USERNAME/server-console/raw/main/install.sh | bash

# Or from a local copy
bash install.sh
```

The installer will:
1. Detect your Linux distribution and install dependencies
2. Guide you through setting a password, port, and IP whitelist
3. Install and start the systemd service

### Use from Client

```bash
# First run — configure connection
python local_console.py

# Execute a command
python local_console.py --exec "ls -la /var/log"

# Stream a long-running command
python local_console.py --stream "apt update && apt upgrade -y"

# Upload a file
python local_console.py --upload script.sh /tmp/script.sh

# Interactive mode
python local_console.py
```

## Files

| File | Description |
|------|-------------|
| `server_agent.py` | Server-side daemon (runs as root, listens on port 9999) |
| `local_console.py` | Client-side console (interactive REPL + CLI mode) |
| `config_manager.py` | Configuration management (PBKDF2 password hashing) |
| `install.sh` | Universal one-click installer for all Linux distros |
| `setup_ssh_key.py` | SSH key management utility |
| `.env.example` | Configuration example file |

## Security Architecture

```
Client                           Server
  |                                |
  |--- ASTROCONSOLE/1.0 ---------->|
  |<--------- READY + salt --------|
  |                                |
  |--- timestamp+nonce+hmac ------>|  HMAC = PBKDF2(password, salt)
  |<--------- AUTH_OK -------------|
  |                                |
  |=== AES-256-CBC Encrypted ======|
  |    [exec] [stream] [upload]    |
  |    [download] [stat] [list]    |
  |================================|
```

### Security Features

| Feature | Implementation |
|---------|---------------|
| Password storage | PBKDF2-HMAC-SHA256, 100k iterations |
| Communication encryption | AES-256-CBC with random IV per message |
| Authentication | HMAC-SHA256 with timestamp + nonce anti-replay |
| IP whitelist | Configurable allowlist (supports CIDR) |
| Brute-force protection | 5 failures → 15-min IP ban |
| Idle timeout | 30 min auto-disconnect |
| File integrity | SHA-256 hash verification on upload/download |
| Audit log | Daily rotation, 30-day retention |

## Interactive Console Commands

```
help              Show help
ping              Heartbeat check
exec <cmd>        Execute shell command
stream <cmd>      Stream long-running command
cancel            Cancel running stream command
ls <path>         List remote directory
stat <path>       File info
upload <l> <r>    Upload file
download <r> <l>  Download file
indexes           Check astrometry index files
svc-status        Show service status
svc-restart       Restart API service
logs [n]          Show last n log lines
exit              Quit
```

## Supported Linux Distributions

| Distribution | Package Manager |
|-------------|----------------|
| Ubuntu / Debian | apt |
| CentOS / RHEL / Rocky / Alma | yum / dnf |
| Fedora | dnf |
| Alpine | apk |
| Arch Linux | pacman |
| openSUSE | zypper |

## Configuration

### Server (`/etc/astrometry/agent.conf`)
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

### Client (`~/.astrometry/console.conf`)
```json
{
  "host": "your-server-ip",
  "port": 9999,
  "password": "your-password"
}
```

## Uninstall

```bash
bash install.sh --uninstall
```

## License

MIT
