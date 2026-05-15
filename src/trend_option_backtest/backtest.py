from __future__ import annotations

from typing import Any
from datetime import timedelta

import pandas as pd

from trend_option_backtest.metrics import calculate_metrics
from trend_option_backtest.models import BacktestResult, StrategyConfig


class BacktestEngine:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def run(self, signal_data: dict[str, pd.DataFrame]) -> BacktestResult:
        symbols = [symbol for symbol in self.config.default_backtest_symbols if symbol in signal_data]
        if not symbols:
            raise ValueError("没有可回测的标的数据")

        capital_per_symbol = self.config.initial_capital / len(symbols)
        trade_start_date = self._trade_start_date([signal_data[symbol] for symbol in symbols])
        all_trades: list[dict[str, Any]] = []
        equity_frames: list[pd.DataFrame] = []

        for symbol in symbols:
            trades, equity = self._run_single_symbol(symbol, signal_data[symbol], capital_per_symbol, trade_start_date)
            all_trades.extend(trades)
            equity_frames.append(equity.rename(columns={"equity": symbol}))

        merged = equity_frames[0]
        for frame in equity_frames[1:]:
            merged = merged.merge(frame, on="date", how="outer")
        merged = merged.sort_values("date").ffill().fillna(capital_per_symbol)
        value_columns = [column for column in merged.columns if column != "date"]
        merged["equity"] = merged[value_columns].sum(axis=1)
        equity_curve = merged[["date", "equity"]]
        symbol_equity_curve = merged[["date", *value_columns, "equity"]].rename(columns={"equity": "组合"})

        metrics = calculate_metrics(
            equity_curve,
            all_trades,
            initial_capital=self.config.initial_capital,
            risk_free_rate=self.config.risk_free_rate,
        )
        return BacktestResult(
            metrics=metrics,
            trades=all_trades,
            equity_curve=equity_curve.to_dict("records"),
            symbol_equity_curve=symbol_equity_curve.to_dict("records"),
        )

    def _run_single_symbol(
        self,
        symbol: str,
        frame: pd.DataFrame,
        initial_capital: float,
        trade_start_date: pd.Timestamp,
    ) -> tuple[list[dict[str, Any]], pd.DataFrame]:
        cash = initial_capital
        shares = 0.0
        cost_basis = 0.0
        previous_reduce_signal = False
        trades: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []

        def append_execution(
            *,
            action: str,
            date: pd.Timestamp,
            price: float,
            execution_shares: float,
            amount: float,
            close: float,
            reason: str,
            return_pct: float | None = None,
            realized_pnl: float | None = None,
        ) -> None:
            position_value_after = shares * close
            symbol_equity_after = cash + position_value_after
            trades.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "action": action,
                    "price": price,
                    "shares": execution_shares,
                    "amount": amount,
                    "amount_pct": amount / self.config.initial_capital if self.config.initial_capital else 0.0,
                    "position_shares_after": shares,
                    "position_value_after": position_value_after,
                    "position_pct_after": position_value_after / self.config.initial_capital if self.config.initial_capital else 0.0,
                    "cash_after": cash,
                    "symbol_equity_after": symbol_equity_after,
                    "avg_cost_after": cost_basis / shares if shares else 0.0,
                    "return_pct": return_pct,
                    "realized_pnl": realized_pnl,
                    "reason": reason,
                }
            )

        def buy(action: str, row: Any, amount: float, reason: str) -> None:
            nonlocal cash, shares, cost_basis
            if amount <= 0:
                return
            close = float(row.close)
            date = pd.Timestamp(row.date)
            fill_price = close * (1 + self.config.slippage_rate)
            execution_amount = min(cash, amount)
            if execution_amount < self.config.min_trade_amount:
                return
            execution_shares = execution_amount / fill_price
            cash -= execution_amount
            shares += execution_shares
            cost_basis += execution_amount
            append_execution(
                action=action,
                date=date,
                price=fill_price,
                execution_shares=execution_shares,
                amount=execution_amount,
                close=close,
                reason=reason,
            )

        def sell(action: str, row: Any, sell_pct: float, reason: str) -> None:
            nonlocal cash, shares, cost_basis
            if shares <= 0:
                return
            close = float(row.close)
            date = pd.Timestamp(row.date)
            fill_price = close * (1 - self.config.slippage_rate)
            execution_shares = min(shares, shares * sell_pct)
            avg_cost = cost_basis / shares if shares else 0.0
            amount = execution_shares * fill_price
            if action == "减仓" and amount < self.config.min_trade_amount:
                return
            realized_cost = execution_shares * avg_cost
            realized_pnl = amount - realized_cost
            return_pct = fill_price / avg_cost - 1 if avg_cost else 0.0
            cash += amount
            shares -= execution_shares
            cost_basis -= realized_cost
            if shares < 1e-9:
                shares = 0.0
                cost_basis = 0.0
            append_execution(
                action=action,
                date=date,
                price=fill_price,
                execution_shares=execution_shares,
                amount=amount,
                close=close,
                return_pct=return_pct,
                realized_pnl=realized_pnl,
                reason=reason,
            )

        for row in frame.sort_values("date").itertuples(index=False):
            close = float(row.close)
            date = pd.Timestamp(row.date)
            current_reduce_signal = bool(row.reduce_signal)

            if date < trade_start_date:
                previous_reduce_signal = current_reduce_signal
                continue

            sold_today = False
            if shares > 0 and bool(row.exit_signal):
                sell("清仓", row, 1.0, self._exit_reason(row))
                sold_today = True
            elif shares > 0 and current_reduce_signal and not previous_reduce_signal:
                sell("减仓", row, self.config.reduce_position_pct, self._reduce_reason(row))
                sold_today = True

            symbol_equity = cash + shares * close
            if not sold_today and shares == 0 and bool(row.entry_signal):
                buy("买入", row, symbol_equity * self.config.entry_position_pct, self._entry_reason(row))
            elif not sold_today and shares > 0 and bool(row.add_signal) and cash > 0:
                buy("加仓", row, symbol_equity * self.config.add_position_pct, self._add_reason(row))

            equity_rows.append({"date": date, "equity": cash + shares * close})
            previous_reduce_signal = current_reduce_signal

        return trades, pd.DataFrame(equity_rows)

    def _trade_start_date(self, frames: list[pd.DataFrame]) -> pd.Timestamp:
        latest_date = max(pd.Timestamp(frame["date"].max()) for frame in frames)
        lookback_days = int(round(self.config.backtest_years * 365.25))
        return latest_date - timedelta(days=lookback_days)

    def _entry_reason(self, row: Any) -> str:
        parts = [
            f"收盘价 {float(row.close):.2f} > MA{self.config.ma_short} {float(row.ma_short):.2f}",
            f"MA{self.config.ma_short} {float(row.ma_short):.2f} > MA{self.config.ma_long} {float(row.ma_long):.2f}",
            f"突破 {self.config.breakout_days} 日前高 {float(row.prior_high):.2f}",
            f"成交量 {float(row.volume):,.0f} > {self.config.volume_multiplier:g} 倍均量 {float(row.volume_ma):,.0f}",
        ]
        if self.config.use_sector_filter:
            parts.append(f"板块过滤通过：{self.config.sector_symbol} > MA{self.config.ma_short}")
        return "入场：" + "；".join(parts)

    def _add_reason(self, row: Any) -> str:
        return (
            f"加仓：盘中触及 MA{self.config.ma_short} {float(row.ma_short):.2f} 后收回，"
            f"收盘价 {float(row.close):.2f} 仍在短均线上方"
        )

    def _reduce_reason(self, row: Any) -> str:
        return (
            f"减仓：收盘价距离 MA{self.config.ma_short} 过热 "
            f"{float(row.distance_to_ma_short) * 100:.2f}% > {self.config.overheat_distance * 100:.2f}%"
        )

    def _exit_reason(self, row: Any) -> str:
        return f"清仓：收盘价 {float(row.close):.2f} 跌破 MA{self.config.ma_long} {float(row.ma_long):.2f}"