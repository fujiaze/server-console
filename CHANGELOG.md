# Changelog

## [2.0.0] - 2026-06-25

### Security Upgrades
- **BREAKING**: Removed XOR fallback encryption — cryptography library is now required
- **BREAKING**: Configuration moved from CLI arguments to config files
- Password storage changed to PBKDF2-HMAC-SHA256 (100,000 iterations)
- Password no longer passed via command-line arguments (prevents process list leakage)
- Added IP whitelist support (single IP and CIDR notation)
- Added brute-force protection (5 failures → 15-min ban)
- Added idle timeout (30 min auto-disconnect)
- Added audit logging with daily rotation (30-day retention)
- Added SHA-256 file integrity verification on upload/download
- Config file permissions locked to 0600

### New Features
- Streaming command execution (`exec_stream` action) with real-time output
- Command cancellation (`cancel` action) for terminating running processes
- `--stream` CLI parameter and `stream` interactive command
- Universal one-click installer (`install.sh`) for all Linux distributions
- `config_manager.py` module for configuration management
- First-run interactive setup wizard
- `--setup` flag for server agent configuration
- `--uninstall` flag for installer

### Privacy
- Removed all hardcoded IPs, passwords, and hostnames from source code
- Default values use placeholders (`0.0.0.0`, `CHANGE_ME`)
- Added `.gitignore` to exclude sensitive files from version control
- Added `.env.example` for configuration reference

### AI Skill
- Added `server-console` TRAE Skill for AI-assisted server management
- AI can execute commands, transfer files, and manage services remotely
- Includes first-time deployment guidance

## [1.0.0] - 2026-06-24

### Initial Release
- Server agent with AES-256-CBC encryption
- HMAC-SHA256 authentication with anti-replay
- Local console client with interactive REPL
- File upload/download (chunked transfer)
- SSH key management utility
- Deployment tools
