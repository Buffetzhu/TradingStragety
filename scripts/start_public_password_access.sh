#!/usr/bin/env bash
# 用途：本地运行 Streamlit，并通过 Cloudflare Quick Tunnel 提供外网访问。
# 要求：必须设置 APP_ACCESS_PASSWORD；仅暴露 8501，不暴露 OpenD 11111。
# 使用：
#   export APP_ACCESS_PASSWORD='your-strong-password'
#   bash scripts/start_public_password_access.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PATH="${VENV_PATH:-$REPO_ROOT/.venv}"
APP_PORT="${APP_PORT:-8501}"

if [[ -z "${APP_ACCESS_PASSWORD:-}" ]]; then
  echo "[ERROR] APP_ACCESS_PASSWORD 未设置。"
  echo "请先执行：export APP_ACCESS_PASSWORD='请改成强密码'"
  exit 1
fi

if [[ ! -f "$VENV_PATH/bin/activate" ]]; then
  echo "[ERROR] 找不到虚拟环境：$VENV_PATH/bin/activate"
  echo "请先执行：python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "[ERROR] 未安装 cloudflared。"
  echo "安装命令：brew install cloudflared"
  exit 1
fi

STREAMLIT_LOG="$REPO_ROOT/deploy/logs/streamlit-public.log"
CLOUDFLARED_LOG="$REPO_ROOT/deploy/logs/cloudflared-public.log"
mkdir -p "$(dirname "$STREAMLIT_LOG")"

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"

cleanup() {
  if [[ -n "${CF_PID:-}" ]] && kill -0 "$CF_PID" 2>/dev/null; then
    kill "$CF_PID" 2>/dev/null || true
  fi
  if [[ -n "${ST_PID:-}" ]] && kill -0 "$ST_PID" 2>/dev/null; then
    kill "$ST_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# 只监听本机回环，避免局域网裸露；外网访问统一走 cloudflared
streamlit run app.py --server.address 127.0.0.1 --server.port "$APP_PORT" >"$STREAMLIT_LOG" 2>&1 &
ST_PID=$!

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${APP_PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${APP_PORT}" >/dev/null 2>&1; then
  echo "[ERROR] Streamlit 未成功启动，请查看日志：$STREAMLIT_LOG"
  exit 1
fi

cloudflared tunnel --url "http://127.0.0.1:${APP_PORT}" --no-autoupdate >"$CLOUDFLARED_LOG" 2>&1 &
CF_PID=$!

PUBLIC_URL=""
for _ in {1..40}; do
  if [[ -f "$CLOUDFLARED_LOG" ]]; then
    PUBLIC_URL="$(grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$CLOUDFLARED_LOG" | head -n 1 || true)"
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[WARN] 暂未解析到公网地址，请查看日志：$CLOUDFLARED_LOG"
else
  cat <<EOF

============================================================
外网访问已启动（免安装客户端）

公网地址：
  $PUBLIC_URL

访问方式：
1) 任意网络打开上面 URL
2) 先输入 APP_ACCESS_PASSWORD
3) 验证通过后进入系统

安全边界：
- 仅暴露 Web 入口 8501
- OpenD 继续留在本机 127.0.0.1:11111，不对公网暴露

停止服务：按 Ctrl+C
============================================================

EOF
fi

wait "$CF_PID"
