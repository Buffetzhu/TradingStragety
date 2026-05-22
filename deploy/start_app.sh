#!/bin/bash
# 用途：在 Macbook 上启动 Streamlit 主应用，供 launchd 守护进程调用。
# 参数：无
# 输出：Streamlit 日志写入 deploy/logs/streamlit.log
# 退出码：0=正常退出（被 launchd 重启），非零=失败
# Known Issues:
#   - 启动前需确保 Futu OpenD 已经在本机运行并监听 11111 端口（OpenD 仍需手动从 GUI 启动）
#   - 若 venv 路径变化需要同步修改下面的 VENV_PATH

set -euo pipefail

# 仓库根目录（脚本位置的上一级）
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PATH="${VENV_PATH:-$REPO_ROOT/.venv}"
LOG_DIR="$REPO_ROOT/deploy/logs"
mkdir -p "$LOG_DIR"

# 简易自检：OpenD 端口是否在监听
if ! nc -z 127.0.0.1 11111 2>/dev/null; then
  echo "[$(date '+%F %T')] WARN: Futu OpenD (127.0.0.1:11111) 未监听，账户/行情功能会降级到缓存数据" >> "$LOG_DIR/streamlit.log"
fi

# 激活虚拟环境
if [ -f "$VENV_PATH/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_PATH/bin/activate"
else
  echo "[$(date '+%F %T')] ERROR: 找不到虚拟环境 $VENV_PATH/bin/activate" >> "$LOG_DIR/streamlit.log"
  exit 1
fi

echo "[$(date '+%F %T')] 启动 Streamlit (PID=$$)" >> "$LOG_DIR/streamlit.log"
exec streamlit run app.py >> "$LOG_DIR/streamlit.log" 2>&1
