#!/bin/bash
# =============================================================================
# Astrometry Server Control Agent - 通用一键安装脚本
#
# 兼容发行版: Ubuntu/Debian、CentOS/RHEL/Rocky/Alma、Fedora、Alpine、Arch、openSUSE
#
# 用法:
#     bash install.sh              # 安装并启动
#     bash install.sh --uninstall  # 卸载
#
# 安全约束:
#     - 不含任何真实 IP / 口令 / 主机名
#     - 口令由用户交互输入，不硬编码
#     - 默认端口 9999
# =============================================================================
set -e

# ----------------------- 常量 -----------------------
SERVICE_NAME="astrometry-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TARGET_DIR="/root"
AGENT_FILE="${TARGET_DIR}/server_agent.py"
CONFIGMOD_FILE="${TARGET_DIR}/config_manager.py"
CONFIG_PATH="/etc/astrometry/agent.conf"
LOG_DIR="/var/log/astrometry-console"

# ----------------------- 颜色输出 -----------------------
if [ -t 1 ]; then
    C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_NC='\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_NC=''
fi

info() { printf "${C_BLUE}[INFO]${C_NC} %s\n" "$*"; }
warn() { printf "${C_YELLOW}[WARN]${C_NC} %s\n" "$*"; }
ok()   { printf "${C_GREEN}[ OK ]${C_NC} %s\n" "$*"; }
die()  { printf "${C_RED}[FATAL]${C_NC} %s\n" "$*" >&2; exit 1; }

# ----------------------- 基础检查 -----------------------
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "请以 root 身份运行此脚本（或使用 sudo）"
    fi
}

# 在脚本目录或当前目录下查找同目录部署文件
find_source_file() {
    local filename="$1" src=""
    local script_src="${BASH_SOURCE[0]:-$0}"
    local script_dir
    script_dir="$(cd "$(dirname "$script_src")" 2>/dev/null && pwd)" || script_dir=""
    if [ -n "$script_dir" ] && [ -f "${script_dir}/${filename}" ]; then
        src="${script_dir}/${filename}"
    elif [ -f "$(pwd)/${filename}" ]; then
        src="$(pwd)/${filename}"
    fi
    echo "$src"
}

# ----------------------- 发行版检测 -----------------------
detect_distro() {
    if [ ! -r /etc/os-release ]; then
        die "无法读取 /etc/os-release，仅支持主流 Linux 发行版"
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-}"
    DISTRO_ID_LIKE="${ID_LIKE:-}"
}

# ----------------------- 依赖安装（按发行版） -----------------------
install_deps_apt() {
    info "使用 apt 安装依赖..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y python3 python3-pip
}

install_deps_dnf() {
    info "使用 dnf 安装依赖..."
    dnf install -y python3 python3-pip
}

install_deps_yum() {
    info "使用 yum 安装依赖..."
    yum install -y python3 python3-pip || yum install -y python3 python3-setuptools
}

install_deps_apk() {
    info "使用 apk 安装依赖..."
    apk update
    apk add --no-cache python3 py3-pip
}

install_deps_pacman() {
    info "使用 pacman 安装依赖..."
    pacman -Sy --noconfirm python python-pip
}

install_deps_zypper() {
    info "使用 zypper 安装依赖..."
    zypper --non-interactive refresh
    zypper --non-interactive install python3 python3-pip
}

install_deps() {
    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint)
            install_deps_apt ;;
        fedora)
            install_deps_dnf ;;
        centos|rhel|rocky|almalinux|ol|amzn)
            if command -v dnf >/dev/null 2>&1; then install_deps_dnf
            else install_deps_yum; fi ;;
        alpine)
            install_deps_apk ;;
        arch|manjaro|garuda)
            install_deps_pacman ;;
        opensuse*|sles|suse)
            install_deps_zypper ;;
        *)
            # 回退：依据 ID_LIKE 判断
            case "$DISTRO_ID_LIKE" in
                *debian*)   install_deps_apt ;;
                *rhel*|*fedora*)
                    if command -v dnf >/dev/null 2>&1; then install_deps_dnf
                    else install_deps_yum; fi ;;
                *arch*)     install_deps_pacman ;;
                *suse*)     install_deps_zypper ;;
                *alpine*)   install_deps_apk ;;
                *)
                    die "不支持的发行版: ${DISTRO_ID}（ID_LIKE=${DISTRO_ID_LIKE}）。请手动安装 python3 与 python3-pip 后重试。"
                    ;;
            esac ;;
    esac
}

# ----------------------- 安装 cryptography -----------------------
install_cryptography() {
    info "安装 cryptography 加密库..."
    local pip_cmd
    if command -v pip3 >/dev/null 2>&1; then
        pip_cmd="pip3"
    elif python3 -m pip --version >/dev/null 2>&1; then
        pip_cmd="python3 -m pip"
    else
        die "pip 不可用，请手动安装 python3-pip 后重试"
    fi

    # PEP 668：新版 Debian/Ubuntu/PEP668 系统需 --break-system-packages
    if ! $pip_cmd install cryptography >/tmp/_pip_crypto.log 2>&1; then
        warn "标准安装失败，尝试 --break-system-packages ..."
        if ! $pip_cmd install --break-system-packages cryptography; then
            die "cryptography 安装失败，请检查网络或 pip 配置后重试"
        fi
    fi
    ok "cryptography 安装完成"
}

# ----------------------- 部署代码文件 -----------------------
deploy_files() {
    local src_agent src_config
    src_agent="$(find_source_file server_agent.py)"
    src_config="$(find_source_file config_manager.py)"

    if [ -z "$src_agent" ]; then
        die "未找到 server_agent.py，请将其与 install.sh 放在同一目录后重试（或在当前目录执行）"
    fi
    if [ -z "$src_config" ]; then
        die "未找到 config_manager.py（server_agent.py 依赖此模块），请将其与 install.sh 放在同一目录"
    fi

    info "部署文件到 ${TARGET_DIR}/ ..."
    cp -f "$src_agent"   "$AGENT_FILE"
    cp -f "$src_config"  "$CONFIGMOD_FILE"
    chmod 0644 "$AGENT_FILE" "$CONFIGMOD_FILE"
    ok "代码文件部署完成"
}

# ----------------------- 交互式配置（口令/端口/IP白名单） -----------------------
run_setup() {
    info "进入交互式配置（由 agent 自带 --setup 引导）..."
    info "  - 监听端口默认 9999（回车保留）"
    info "  - 口令需输入两次以确认"
    info "  - IP 白名单可选（回车保留默认）"
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    # 调用 agent 自带的交互式引导：设置 host/port/口令(两次)/IP白名单/日志路径
    python3 "$AGENT_FILE" --setup
    ok "配置已写入 ${CONFIG_PATH}"
}

# ----------------------- systemd 服务 -----------------------
write_systemd_unit() {
    info "写入 systemd 服务文件..."
    cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Astrometry Server Control Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /root/server_agent.py
Restart=always
RestartSec=5
User=root
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF
    ok "服务文件已写入 ${SERVICE_FILE}"
}

enable_start_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        warn "未检测到 systemctl（系统可能未使用 systemd，如 Alpine/OpenRC）。"
        warn "已跳过服务安装。请手动启动: nohup /usr/bin/python3 ${AGENT_FILE} &"
        warn "服务文件已生成于 ${SERVICE_FILE}，可自行适配 init 系统。"
        return 0
    fi
    info "启用并启动服务..."
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    systemctl restart "${SERVICE_NAME}.service"
    sleep 1
    if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        ok "服务已启动并设为开机自启"
    else
        warn "服务可能未正常运行，请执行: systemctl status ${SERVICE_NAME}"
    fi
}

# ----------------------- 安装主流程 -----------------------
do_install() {
    require_root
    info "=== 开始安装 Astrometry Server Control Agent ==="
    detect_distro
    info "检测到发行版: ${DISTRO_ID} ${DISTRO_ID_LIKE:+(like ${DISTRO_ID_LIKE})}"

    install_deps
    command -v python3 >/dev/null 2>&1 || die "python3 安装失败"
    install_cryptography
    deploy_files
    run_setup
    write_systemd_unit
    enable_start_service

    echo
    ok "=== 安装完成 ==="
    info "服务名称: ${SERVICE_NAME}"
    info "配置文件: ${CONFIG_PATH}"
    info "日志目录: ${LOG_DIR}"
    info "常用命令:"
    echo "    systemctl status  ${SERVICE_NAME}"
    echo "    systemctl restart ${SERVICE_NAME}"
    echo "    journalctl -u ${SERVICE_NAME} -f"
}

# ----------------------- 卸载 -----------------------
do_uninstall() {
    require_root
    info "=== 开始卸载 Astrometry Server Control Agent ==="

    if [ -f "$SERVICE_FILE" ] || command -v systemctl >/dev/null 2>&1; then
        if command -v systemctl >/dev/null 2>&1; then
            systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
            systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
        fi
        rm -f "$SERVICE_FILE"
        if command -v systemctl >/dev/null 2>&1; then
            systemctl daemon-reload 2>/dev/null || true
        fi
        ok "已停止并移除 systemd 服务"
    else
        warn "未发现 systemd 服务，跳过"
    fi

    local remove_data="n"
    if [ -t 0 ]; then
        read -r -p "是否同时删除代码与配置 (${AGENT_FILE}, ${CONFIGMOD_FILE}, ${CONFIG_PATH}, ${LOG_DIR})? [y/N]: " remove_data || true
    fi
    case "$remove_data" in
        y|Y|yes|YES)
            rm -f "$AGENT_FILE" "$CONFIGMOD_FILE" "$CONFIG_PATH"
            rm -rf "$LOG_DIR" 2>/dev/null || true
            ok "已删除代码、配置与日志"
            ;;
        *)
            info "保留代码与配置文件，仅停止并移除服务"
            ;;
    esac

    ok "=== 卸载完成 ==="
}

# ----------------------- 入口 -----------------------
usage() {
    cat <<EOF
用法:
    bash install.sh              # 安装并启动服务
    bash install.sh --uninstall  # 卸载服务
    bash install.sh --help       # 显示帮助

环境要求:
    - 主流 Linux 发行版 (Ubuntu/Debian/CentOS/RHEL/Fedora/Alpine/Arch/openSUSE)
    - root 权限
    - 同目录下需存在 server_agent.py 与 config_manager.py
EOF
}

case "${1:-}" in
    --uninstall|-u)
        do_uninstall
        ;;
    --help|-h)
        usage
        ;;
    "")
        do_install
        ;;
    *)
        echo "未知参数: $1" >&2
        usage
        exit 1
        ;;
esac
