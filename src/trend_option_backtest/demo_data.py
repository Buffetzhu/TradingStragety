from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd


def _make_symbol_frame(symbol: str, periods: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp(date.today()), periods=periods)
    base = 70 + (seed % 30) * 3
    trend = np.linspace(0, 80 + seed % 40, periods)
    cycle = np.array([math.sin(idx / 17) * 5 for idx in range(periods)])
    noise = rng.normal(0, 1.8, periods).cumsum() * 0.35
    close = np.maximum(base + trend + cycle + noise, 5)
    open_price = close * (1 + rng.normal(0, 0.006, periods))
    high = np.maximum(open_price, close) * (1 + rng.uniform(0.002, 0.018, periods))
    low = np.minimum(open_price, close) * (1 - rng.uniform(0.002, 0.018, periods))
    volume = rng.integers(2_000_000, 8_000_000, periods).astype(float)

    for idx in range(80, periods, 55):
        close[idx : idx + 8] *= np.linspace(1.01, 1.08, min(8, periods - idx))
        volume[idx : idx + 8] *= 1.8

    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def years_to_business_days(years: float) -> int:
    return max(80, int(round(years * 252)))


def make_demo_market_data(
    symbols: list[str],
    *,
    sector_symbol: str,
    years: float = 2.0,
    warmup_days: int = 120,
) -> dict[str, pd.DataFrame]:
    all_symbols = list(dict.fromkeys([*symbols, sector_symbol]))
    periods = years_to_business_days(years) + max(warmup_days, 0)
    return {
        symbol: _make_symbol_frame(symbol, periods=periods, seed=sum(ord(char) for char in symbol))
        for symbol in all_symbols
    }