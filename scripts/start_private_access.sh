#!/usr/bin/env bash
# 用途：一键本地私有部署并输出可在手机访问的地址（不暴露 OpenD 到公网）
# 使用：bash scripts/start_private_access.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PATH="${VENV_PATH:-$REPO_ROOT/.venv}"
APP_PORT="${APP_PORT:-8501}"

if [[ ! -f "$VENV_PATH/bin/activate" ]]; then
  echo "[ERROR] 找不到虚拟环境：$VENV_PATH/bin/activate"
  echo "请先执行：python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
TAILSCALE_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TAILSCALE_IP=""
if [[ -x "$TAILSCALE_BIN" ]]; then
  TAILSCALE_IP="$($TAILSCALE_BIN ip -4 2>/dev/null | head -n 1 || true)"
fi

cat <<EOF

============================================================
私有部署启动中（无公网隧道）

本机访问:
  http://127.0.0.1:${APP_PORT}
EOF

if [[ -n "$LAN_IP" ]]; then
  cat <<EOF
同一 Wi-Fi 手机访问:
  http://${LAN_IP}:${APP_PORT}
EOF
fi

if [[ -n "$TAILSCALE_IP" ]]; then
  cat <<EOF
Tailscale 私网访问（需手机安装 Tailscale）:
  http://${TAILSCALE_IP}:${APP_PORT}
EOF
fi

cat <<EOF

提示：
1) 仅在你信任的网络中使用局域网地址。
2) OpenD 继续保持本机 127.0.0.1:11111，不要做公网映射。
3) 按 Ctrl+C 可停止服务。
============================================================

EOF

exec streamlit run app.py --server.address 0.0.0.0 --server.port "$APP_PORT"
