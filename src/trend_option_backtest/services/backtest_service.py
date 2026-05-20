from __future__ import annotations

import pandas as pd

from trend_option_backtest.backtest import BacktestEngine
from trend_option_backtest.models import BacktestResult, StrategyConfig
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy


class BacktestService:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config
        self.strategy = TrendFollowingStrategy(config)

    def run(
        self,
        market_data: dict[str, pd.DataFrame],
        initial_positions: dict[str, dict[str, float]] | None = None,
    ) -> BacktestResult:
        sector_data = market_data.get(self.config.sector_symbol)
        signal_data = {}
        for symbol in self.config.default_backtest_symbols:
            if symbol not in market_data:
                continue
            signal_data[symbol] = self.strategy.prepare_with_signals(market_data[symbol], sector_data)
        return BacktestEngine(self.config, initial_positions=initial_positions).run(signal_data)