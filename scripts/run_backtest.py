#!/usr/bin/env python
# 用途：运行 V1 默认趋势回测
# 参数：--demo 使用内置演示数据；--config 指定配置文件；--period-years 指定回测年数
# 输出：核心回测指标
# 退出码：0=成功，1=执行出错
# Known Issues: 未接入真实行情时只能使用 --demo 验证引擎。

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trend_option_backtest.demo_data import make_demo_market_data
from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.services.backtest_service import BacktestService


def main() -> int:
    parser = argparse.ArgumentParser(description="运行趋势策略回测")
    parser.add_argument("--config", default="config/default_config.json")
    parser.add_argument("--demo", action="store_true", help="使用内置演示数据")
    parser.add_argument("--period-years", type=float, default=None, help="覆盖配置中的回测年数")
    args = parser.parse_args()

    try:
        config = StrategyConfig.from_json(Path(args.config))
        if not args.demo:
            print("ERROR 当前首版命令行入口请先使用 --demo；真实行情接入将在数据层完成后启用。")
            return 1

        period_years = args.period_years if args.period_years is not None else config.backtest_years
        market_data = make_demo_market_data(
            config.default_backtest_symbols,
            sector_symbol=config.sector_symbol,
            years=period_years,
            warmup_days=config.indicator_warmup_days,
        )
        result = BacktestService(config).run(market_data)
        print(json.dumps(result.metrics, ensure_ascii=False, indent=2))
        print(f"TRADES {len(result.trades)}")
        return 0
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())