from __future__ import annotations

import json

import pandas as pd

from .models import StrategyConfig


def _date_range_from_equity(equity_df: pd.DataFrame) -> tuple[str, str]:
    if equity_df.empty or "date" not in equity_df.columns:
        return "", ""
    dates = pd.to_datetime(equity_df["date"], errors="coerce").dropna()
    if dates.empty:
        return "", ""
    return str(dates.min().date()), str(dates.max().date())


def build_strategy_plan_export_frame(
    plan_df: pd.DataFrame,
    *,
    config: StrategyConfig,
    data_source: str,
    equity_df: pd.DataFrame,
    capital_source: str,
    capital_value: float,
    position_source: str,
    app_version: str,
    account_info: dict[str, object] | None = None,
    generated_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    export_df = plan_df.drop(columns=["优先级排序"], errors="ignore").copy()
    start_date, end_date = _date_range_from_equity(equity_df)
    timestamp = generated_at or pd.Timestamp.now()
    account_info = account_info or {}
    snapshot = {
        "导出时间": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "应用版本": app_version,
        "数据源": data_source,
        "行情开始日期": start_date,
        "行情结束日期": end_date,
        "参与标的": ",".join(config.default_backtest_symbols),
        "资金来源": capital_source,
        "计划资金基准": float(capital_value),
        "持仓来源": position_source,
        "账户市场": str(account_info.get("market", "")),
        "账户环境": str(account_info.get("trd_env", "")),
        "账户币种": str(account_info.get("currency", "")),
        "策略参数快照": json.dumps(
            {
                "ma_short": config.ma_short,
                "ma_long": config.ma_long,
                "breakout_days": config.breakout_days,
                "volume_multiplier": config.volume_multiplier,
                "overheat_distance": config.overheat_distance,
                "entry_position_pct": config.entry_position_pct,
                "add_position_pct": config.add_position_pct,
                "reduce_position_pct": config.reduce_position_pct,
                "min_trade_amount": config.min_trade_amount,
                "use_sector_filter": config.use_sector_filter,
                "sector_symbol": config.sector_symbol,
                "backtest_years": config.backtest_years,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    for column, value in reversed(list(snapshot.items())):
        export_df.insert(0, column, value)
    return export_df