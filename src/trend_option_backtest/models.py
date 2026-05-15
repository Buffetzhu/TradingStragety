from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategyConfig:
    strategy_name: str
    default_pool: list[str]
    default_backtest_symbols: list[str]
    start_date: str
    backtest_years: float = 2.0
    indicator_warmup_days: int = 120
    ma_short: int = 20
    ma_long: int = 50
    volume_ma: int = 20
    volume_multiplier: float = 1.3
    breakout_days: int = 20
    overheat_distance: float = 0.15
    entry_position_pct: float = 0.5
    add_position_pct: float = 0.25
    reduce_position_pct: float = 0.5
    min_trade_amount: float = 100.0
    use_sector_filter: bool = True
    sector_symbol: str = "SOXX"
    initial_capital: float = 100000.0
    risk_free_rate: float = 0.04
    commission_rate: float = 0.0
    slippage_rate: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StrategyConfig":
        return cls(
            strategy_name=str(payload["strategy_name"]),
            default_pool=list(payload["default_pool"]),
            default_backtest_symbols=list(payload["default_backtest_symbols"]),
            start_date=str(payload["start_date"]),
            backtest_years=float(payload.get("backtest_years", 2.0)),
            indicator_warmup_days=int(payload.get("indicator_warmup_days", 120)),
            ma_short=int(payload.get("ma_short", 20)),
            ma_long=int(payload.get("ma_long", 50)),
            volume_ma=int(payload.get("volume_ma", 20)),
            volume_multiplier=float(payload.get("volume_multiplier", 1.3)),
            breakout_days=int(payload.get("breakout_days", 20)),
            overheat_distance=float(payload.get("overheat_distance", 0.15)),
            entry_position_pct=float(payload.get("entry_position_pct", 0.5)),
            add_position_pct=float(payload.get("add_position_pct", 0.25)),
            reduce_position_pct=float(payload.get("reduce_position_pct", 0.5)),
            min_trade_amount=float(payload.get("min_trade_amount", 100.0)),
            use_sector_filter=bool(payload.get("use_sector_filter", True)),
            sector_symbol=str(payload.get("sector_symbol", "SOXX")),
            initial_capital=float(payload.get("initial_capital", 100000)),
            risk_free_rate=float(payload.get("risk_free_rate", 0.04)),
            commission_rate=float(payload.get("commission_rate", 0.0)),
            slippage_rate=float(payload.get("slippage_rate", 0.0)),
        )

    @classmethod
    def from_json(cls, path: Path) -> "StrategyConfig":
        with path.open("r", encoding="utf-8") as file:
            return cls.from_dict(json.load(file))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "default_pool": self.default_pool,
            "default_backtest_symbols": self.default_backtest_symbols,
            "start_date": self.start_date,
            "backtest_years": self.backtest_years,
            "indicator_warmup_days": self.indicator_warmup_days,
            "ma_short": self.ma_short,
            "ma_long": self.ma_long,
            "volume_ma": self.volume_ma,
            "volume_multiplier": self.volume_multiplier,
            "breakout_days": self.breakout_days,
            "overheat_distance": self.overheat_distance,
            "entry_position_pct": self.entry_position_pct,
            "add_position_pct": self.add_position_pct,
            "reduce_position_pct": self.reduce_position_pct,
            "min_trade_amount": self.min_trade_amount,
            "use_sector_filter": self.use_sector_filter,
            "sector_symbol": self.sector_symbol,
            "initial_capital": self.initial_capital,
            "risk_free_rate": self.risk_free_rate,
            "commission_rate": self.commission_rate,
            "slippage_rate": self.slippage_rate,
        }


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict[str, float | int | str]
    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    symbol_equity_curve: list[dict[str, Any]]