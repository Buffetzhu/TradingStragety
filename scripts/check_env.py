"""
用途：一键环境自检 —— Python 依赖、关键目录、OpenD 在线状态。
参数：
  --opend-host HOST   OpenD 主机（默认 127.0.0.1）
  --opend-port PORT   OpenD 端口（默认 11111）
  --skip-opend        跳过 OpenD 检查（离线场景）
输出：
  逐项打印 [OK] / [WARN] / [FAIL] 及说明。
退出码：
  0 = 全部 OK 或仅 WARN；1 = 至少一项 FAIL。
Known Issues:
  - 富途 SDK 未装时 OpenD 检查会自动降级为 WARN，不会 FAIL。
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PACKAGES = [
    "pandas",
    "numpy",
    "streamlit",
    "plotly",
]
OPTIONAL_PACKAGES = [
    "futu",  # 富途 SDK
]
REQUIRED_DIRS = [
    "data",
    "data/cache",
    "output",
]
REQUIRED_FILES = [
    "app.py",
    "VERSION",
    "src/trend_option_backtest/__init__.py",
]


def _status(level: str, msg: str) -> None:
    icon = {"OK": "[OK]   ", "WARN": "[WARN] ", "FAIL": "[FAIL] "}[level]
    print(f"{icon}{msg}")


def check_packages() -> int:
    failures = 0
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _status("OK", f"依赖 {pkg} 已安装")
        except ImportError as exc:
            _status("FAIL", f"依赖 {pkg} 缺失：{exc}")
            failures += 1
    for pkg in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg)
            _status("OK", f"可选依赖 {pkg} 已安装")
        except ImportError:
            _status("WARN", f"可选依赖 {pkg} 未安装；账户/行情功能不可用。pip install {pkg}-api")
    return failures


def check_paths() -> int:
    failures = 0
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if path.is_file():
            _status("OK", f"文件存在 {rel}")
        else:
            _status("FAIL", f"缺失文件 {rel}")
            failures += 1
    for rel in REQUIRED_DIRS:
        path = ROOT / rel
        if path.is_dir():
            _status("OK", f"目录存在 {rel}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            _status("WARN", f"目录 {rel} 缺失已自动创建")
    return failures


def check_opend(host: str, port: int) -> int:
    try:
        with socket.create_connection((host, port), timeout=2):
            _status("OK", f"OpenD {host}:{port} TCP 端口可达")
    except OSError as exc:
        _status(
            "WARN",
            f"OpenD {host}:{port} 不可达：{exc}。账户/行情读取会失败；如不需要可加 --skip-opend",
        )
        return 0  # WARN 不计入 failures
    # 进一步用 futu SDK 校验握手
    try:
        from futu import OpenQuoteContext  # type: ignore[import-untyped]

        ctx = OpenQuoteContext(host=host, port=port)
        ret, _ = ctx.get_global_state()
        ctx.close()
        if ret == 0:
            _status("OK", "OpenD 握手成功（get_global_state ret=0）")
        else:
            _status("WARN", f"OpenD TCP 可达但握手失败 ret={ret}；可能未登录账户")
    except ImportError:
        _status("WARN", "futu SDK 未安装，跳过握手检查")
    except Exception as exc:  # noqa: BLE001
        _status("WARN", f"OpenD 握手异常：{exc}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="环境自检")
    parser.add_argument("--opend-host", default="127.0.0.1")
    parser.add_argument("--opend-port", type=int, default=11111)
    parser.add_argument("--skip-opend", action="store_true")
    args = parser.parse_args()

    print(f"=== TradingStragety 环境自检 (root={ROOT}) ===")
    print(f"Python: {sys.version.split()[0]}")
    total_fail = 0
    print("\n[1/3] 检查 Python 依赖")
    total_fail += check_packages()
    print("\n[2/3] 检查项目目录与文件")
    total_fail += check_paths()
    print("\n[3/3] 检查 OpenD 连接")
    if args.skip_opend:
        _status("WARN", "已通过 --skip-opend 跳过 OpenD 检查")
    else:
        total_fail += check_opend(args.opend_host, args.opend_port)

    print()
    if total_fail == 0:
        _status("OK", "环境自检通过，可以继续。")
        return 0
    _status("FAIL", f"环境自检发现 {total_fail} 项致命问题，请修复后重试。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
