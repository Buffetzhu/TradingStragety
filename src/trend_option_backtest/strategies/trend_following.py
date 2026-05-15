from __future__ import annotations

import pandas as pd

from trend_option_backtest.models import StrategyConfig


class TrendFollowingStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def prepare_data(self, data: pd.DataFrame, sector_data: pd.DataFrame | None = None) -> pd.DataFrame:
        frame = data.copy().sort_values("date").reset_index(drop=True)
        frame["ma_short"] = frame["close"].rolling(self.config.ma_short).mean()
        frame["ma_long"] = frame["close"].rolling(self.config.ma_long).mean()
        frame["volume_ma"] = frame["volume"].rolling(self.config.volume_ma).mean()
        frame["prior_high"] = frame["close"].shift(1).rolling(self.config.breakout_days).max()
        frame["distance_to_ma_short"] = (frame["close"] / frame["ma_short"]) - 1

        if self.config.use_sector_filter and sector_data is not None:
            sector = sector_data.copy().sort_values("date")
            sector["sector_ma_short"] = sector["close"].rolling(self.config.ma_short).mean()
            sector["sector_ok"] = sector["close"] > sector["sector_ma_short"]
            frame = frame.merge(sector[["date", "sector_ok"]], on="date", how="left")
            frame["sector_ok"] = frame["sector_ok"].fillna(False)
        else:
            frame["sector_ok"] = True

        return frame

    def generate_signals(self, prepared: pd.DataFrame) -> pd.DataFrame:
        frame = prepared.copy()
        frame["entry_signal"] = (
            (frame["close"] > frame["ma_short"])
            & (frame["ma_short"] > frame["ma_long"])
            & (frame["close"] > frame["prior_high"])
            & (frame["volume"] > frame["volume_ma"] * self.config.volume_multiplier)
            & frame["sector_ok"]
        )
        frame["add_signal"] = (
            (frame["low"] <= frame["ma_short"])
            & (frame["close"] > frame["ma_short"])
            & (frame["ma_short"] > frame["ma_long"])
            & frame["sector_ok"]
        )
        frame["reduce_signal"] = frame["distance_to_ma_short"] > self.config.overheat_distance
        frame["exit_signal"] = frame["close"] < frame["ma_long"]
        return frame

    def prepare_with_signals(self, data: pd.DataFrame, sector_data: pd.DataFrame | None = None) -> pd.DataFrame:
        return self.generate_signals(self.prepare_data(data, sector_data))