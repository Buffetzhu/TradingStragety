"""
用途：账户验收冒烟测试 —— 在不下单的前提下，验证真实富途账户读流程。
参数：
  --host HOST          OpenD 主机（默认 127.0.0.1）
  --port PORT          OpenD 端口（默认 11111）
  --market MARKET      市场（US/HK/CN/SG，默认 US）
  --env ENV            交易环境（REAL/SIMULATE，默认 REAL）
  --acc-id ID          账户 ID（可选）
输出：
  逐步打印 [OK]/[FAIL] 及关键字段。如全部通过，输出账户和持仓摘要。
退出码：
  0 = 全部通过；1 = 任一步失败。
Known Issues:
  - 仅做 READ-ONLY，不调用任何下单/撤单 API。
  - 富途 SDK 未装 / OpenD 未启动 时直接 FAIL，不会自动降级。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _status(level: str, msg: str) -> None:
    icon = {"OK": "[OK]   ", "FAIL": "[FAIL] ", "INFO": "[INFO] "}[level]
    print(f"{icon}{msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="账户验收冒烟测试（只读）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--market", default="US", choices=["US", "HK", "CN", "SG"])
    parser.add_argument("--env", default="REAL", choices=["REAL", "SIMULATE"])
    parser.add_argument("--acc-id", type=int, default=None)
    args = parser.parse_args()

    print("=== 账户验收冒烟测试（READ-ONLY） ===")
    print(f"OpenD: {args.host}:{args.port}  市场: {args.market}  环境: {args.env}")

    try:
        from trend_option_backtest.providers.futu_provider import (
            FutuDataConfig,
            FutuHistoricalDataProvider,
        )
    except ImportError as exc:
        _status("FAIL", f"导入 FutuHistoricalDataProvider 失败：{exc}")
        return 1

    provider = FutuHistoricalDataProvider(
        FutuDataConfig(host=args.host, port=args.port, cache_dir=ROOT / "data" / "cache")
    )
    failures = 0

    # 1) 连接测试
    try:
        ok, message = provider.test_connection()
        if ok:
            _status("OK", f"OpenD 连接通过：{message}")
        else:
            _status("FAIL", f"OpenD 连接失败：{message}")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        _status("FAIL", f"OpenD 连接异常：{exc}")
        failures += 1

    # 2) 账户资金
    try:
        info = provider.get_account_info(market=args.market, trd_env=args.env, acc_id=args.acc_id)
        if info:
            _status(
                "OK",
                f"账户资金：总资产={info.get('total_assets')}, 现金={info.get('cash')}, 购买力={info.get('buying_power')}",
            )
        else:
            _status("FAIL", "账户资金返回为空")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        _status("FAIL", f"账户资金读取失败：{exc}")
        failures += 1

    # 3) 持仓列表
    try:
        positions = provider.get_positions(market=args.market, trd_env=args.env, acc_id=args.acc_id)
        _status("OK", f"持仓行数：{len(positions)}")
        if not positions.empty:
            _status("INFO", f"列：{list(positions.columns)}")
            _status("INFO", "前 5 条：")
            for _, row in positions.head(5).iterrows():
                print(f"    {dict(row)}")
    except Exception as exc:  # noqa: BLE001
        _status("FAIL", f"持仓读取失败：{exc}")
        failures += 1

    print()
    if failures == 0:
        _status("OK", "账户验收冒烟测试全部通过。可手动到 Streamlit 页面继续完整回归。")
        return 0
    _status("FAIL", f"共 {failures} 项失败，请先排查 OpenD 登录态和账户权限。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
