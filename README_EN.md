# Server Console — Encrypted Remote Server Management Tool

**English** | [中文](./README.md)

A lightweight, encrypted remote server management tool that replaces cumbersome SSH sessions with a secure console channel. Designed for AI-assisted server operations.

## Features

- **AES-256-CBC encrypted communication** — All traffic encrypted, no plaintext over the wire
- **HMAC-SHA256 authentication** — PBKDF2 key derivation (100,000 iterations)
- **IP whitelist** — Restrict access to trusted client IPs (supports CIDR)
- **Brute-force protection** — Auto-ban after 5 failed auth attempts (15 min)
- **Streaming command execution** — Real-time stdout/stderr for long-running commands
- **File transfer** — Upload/download with SHA-256 integrity verification
- **Audit logging** — All operations logged with daily rotation (30-day retention)
- **Idle timeout** — Auto-disconnect after 30 minutes of inactivity
- **One-click install** — Universal installer for all major Linux distributions
- **AI Skill compatible** — AI can operate servers directly through the console

## Quick Start

### 1. Install on Server

```bash
curl -sSL https://github.com/fujiaze/server-console/raw/main/install.sh | bash
```

The installer will:
1. Detect your Linux distribution and install dependencies
2. Guide you through setting a password, port, and IP whitelist
3. Install and start the systemd service

### 2. Configure Client

```bash
python local_console.py          # First run — interactive setup
python local_console.py --exec "ls -la /var/log"
python local_console.py --stream "apt update && apt upgrade -y"
python local_console.py --upload script.sh /tmp/script.sh
```

### 3. Install AI Skill (Important)

Copy `skills/server-console/SKILL.md` to your TRAE workspace:

```bash
mkdir -p .trae/skills/server-console
cp skills/server-console/SKILL.md .trae/skills/server-console/SKILL.md
```

After installation, AI can directly manage your server — execute commands, transfer files, deploy code, and troubleshoot, all through the encrypted channel.

## Files

| File | Description |
|------|-------------|
| `server_agent.py` | Server-side daemon (runs as root, port 9999) |
| `local_console.py` | Client console (interactive REPL + CLI) |
| `config_manager.py` | Configuration management (PBKDF2 hashing) |
| `install.sh` | Universal one-click installer |
| `skills/server-console/SKILL.md` | AI Skill definition (install to .trae/skills/) |

## Security

- Password: PBKDF2-HMAC-SHA256, 100k iterations, 0600 file permissions
- Encryption: AES-256-CBC with random IV per message
- Auth: HMAC-SHA256 with timestamp + nonce anti-replay
- IP whitelist with CIDR support
- Brute-force protection: 5 failures → 15-min ban
- Idle timeout: 30 min auto-disconnect
- File integrity: SHA-256 verification
- Audit log: daily rotation, 30-day retention

## Supported Linux Distributions

Ubuntu/Debian (apt), CentOS/RHEL (yum/dnf), Fedora (dnf), Alpine (apk), Arch (pacman), openSUSE (zypper)

## Uninstall

```bash
bash install.sh --uninstall
```

## Documentation

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed deployment and usage guide.

## License

MIT
