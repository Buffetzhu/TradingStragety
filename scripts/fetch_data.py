#!/usr/bin/env python
# 用途：从富途 OpenD 拉取历史日 K 数据并缓存到本地
# 参数：--symbols 股票代码列表；--years 回溯年数；--host OpenD 地址；--port OpenD 端口
# 输出：逐行输出缓存结果
# 退出码：0=成功，1=执行出错
# Known Issues: 无市场前缀的代码默认按美股 `US.` 补全。

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider


def parse_symbols(text: str) -> list[str]:
    return [item.strip().upper() for item in text.replace("，", ",").split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="从富途 OpenD 拉取历史行情")
    parser.add_argument("--symbols", required=True, help="逗号分隔，例如 AMD,NVDA,SOXX")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--sector-symbol", default="SOXX")
    args = parser.parse_args()

    try:
        symbols = parse_symbols(args.symbols)
        provider = FutuHistoricalDataProvider(
            FutuDataConfig(host=args.host, port=args.port, cache_dir=ROOT / "data" / "cache")
        )
        market_data = provider.get_market_data(symbols, sector_symbol=args.sector_symbol, years=args.years, use_cache=False)
        for symbol, frame in market_data.items():
            print(f"CACHED {symbol} ROWS {len(frame)}")
        return 0
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())