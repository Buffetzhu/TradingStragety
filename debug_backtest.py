import sys
import os
sys.path.append(os.path.abspath("src"))

try:
    from trend_option_backtest.models import StrategyConfig
    from trend_option_backtest.services.backtest_service import BacktestService
    from trend_option_backtest.demo_data import make_demo_market_data

    cfg = StrategyConfig()
    cfg.default_backtest_symbols = ["AMD", "NVDA"]
    cfg.backtest_years = 0.5
    market = make_demo_market_data(cfg.default_backtest_symbols, sector_symbol=cfg.sector_symbol, years=cfg.backtest_years, warmup_days=cfg.indicator_warmup_days)
    result = BacktestService(cfg).run(market)
    print("config symbols:", cfg.default_backtest_symbols)
    print("trade count:", len(result.trades))
    if result.trades:
        print("first trade keys:", list(result.trades[0].keys()))
        print("unique symbols in trades:", sorted({t['symbol'] for t in result.trades}))
        print("unique actions:", sorted({t['action'] for t in result.trades}))
        print("first trade sample:", {k: str(result.trades[0][k]) for k in ('symbol','date','action','price','reason')})
except Exception as e:
    import traceback
    traceback.print_exc()
