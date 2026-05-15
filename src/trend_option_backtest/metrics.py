from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    drawdown = equity / peak - 1
    return float(drawdown.min())


def calculate_metrics(
    equity_curve: pd.DataFrame,
    trades: list[dict[str, Any]],
    *,
    initial_capital: float,
    risk_free_rate: float,
) -> dict[str, float | int | str]:
    if equity_curve.empty:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "trade_count": 0,
            "closed_trade_count": 0,
        }

    equity = equity_curve["equity"]
    total_return = float(equity.iloc[-1] / initial_capital - 1)
    daily_returns = equity.pct_change().dropna()
    if daily_returns.std() > 0:
        sharpe = float(((daily_returns.mean() * 252) - risk_free_rate) / (daily_returns.std() * math.sqrt(252)))
    else:
        sharpe = 0.0

    trade_returns = [float(trade["return_pct"]) for trade in trades if trade.get("return_pct") is not None]
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "total_return": total_return,
        "max_drawdown": _max_drawdown(equity),
        "sharpe": sharpe,
        "win_rate": float(len(wins) / len(trade_returns)) if trade_returns else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else float("inf") if gross_profit else 0.0,
        "trade_count": len(trades),
        "closed_trade_count": len(trade_returns),
    }