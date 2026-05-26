from __future__ import annotations

import pandas as pd

from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.planning import get_symbol_market_label, is_stock_like_symbol, normalize_app_symbol, symbol_market_sort_key
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy

DISCOVERY_COLUMNS = [
    "分组",
    "市场",
    "标的",
    "状态",
    "综合评分",
    "接近程度",
    "收盘价",
    "入场参考价",
    "止损参考价",
    "止盈参考价",
    "首仓参考金额",
    "建议股数",
    "距入场参考",
    "转入场条件",
    "提前关注点",
    "均线趋势",
    "价格突破",
    "成交量确认",
    "行业共振",
    "未过热",
]

_SIGNAL_LABELS = {
    "trend_ok": "均线趋势",
    "breakout_ok": "价格突破",
    "volume_ok": "成交量确认",
    "sector_ok": "行业共振",
    "temperature_ok": "未过热",
}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(parsed):
        return default
    return parsed


def score_symbol_signals(last_row: pd.Series, config: StrategyConfig) -> dict[str, object]:
    close = _safe_float(last_row.get("close"))
    ma_short = _safe_float(last_row.get("ma_short"))
    ma_long = _safe_float(last_row.get("ma_long"))
    prior_high = _safe_float(last_row.get("prior_high"))
    volume = _safe_float(last_row.get("volume"))
    volume_ma = _safe_float(last_row.get("volume_ma"))
    distance_to_ma_short = _safe_float(last_row.get("distance_to_ma_short"), float("inf"))
    sector_ok = bool(last_row.get("sector_ok", True))

    signals = {
        "trend_ok": close > ma_short > ma_long > 0,
        "breakout_ok": close > prior_high > 0,
        "volume_ok": volume_ma > 0 and volume > volume_ma * config.volume_multiplier,
        "sector_ok": sector_ok,
        "temperature_ok": distance_to_ma_short < config.overheat_distance,
    }
    score = sum(1 for value in signals.values() if value)
    missing = [_SIGNAL_LABELS[key] for key, value in signals.items() if not value]
    return {"score": score, "signals": signals, "missing": missing}


def _build_entry_condition(row: pd.Series, config: StrategyConfig, scoring: dict[str, object], entry_price: float) -> str:
    missing = list(scoring["missing"])
    if not missing:
        return "已满足入场条件"
    if "价格突破" in missing:
        return f"站上 {entry_price:,.2f} 后转入场候选"
    if "成交量确认" in missing:
        return f"放量超过均量 {config.volume_multiplier:g}x 后转入场候选"
    if "均线趋势" in missing:
        return f"MA{config.ma_short} 重新高于 MA{config.ma_long} 后再看突破"
    if "行业共振" in missing:
        return f"{config.sector_symbol} 站上 MA{config.ma_short} 后再看入场"
    if "未过热" in missing:
        return f"等待价格回到 MA{config.ma_short} 附近后再入场"
    return "等待缺失条件修复"


def _build_watch_note(scoring: dict[str, object]) -> str:
    missing = list(scoring["missing"])
    if not missing:
        return "完整满足趋势、突破、量能和风控条件，可放入命中区。"
    if missing == ["价格突破"]:
        return "趋势、量能和行业共振已到位，只差价格确认，优先盯盘。"
    if missing == ["成交量确认"]:
        return "形态已接近，只差成交确认，放量时优先复核。"
    if "均线趋势" in missing:
        return "趋势还没修复，先降低关注频率。"
    if "行业共振" in missing:
        return "个股条件接近，但板块未共振，避免过早入场。"
    if "未过热" in missing:
        return "信号偏强但价格偏热，等待冷却比追高更重要。"
    return "继续观察缺失条件是否改善。"


def _closeness_label(score: int, distance_to_entry: float) -> str:
    if score >= 4:
        return "建议入场"
    if score == 3 and distance_to_entry >= -0.05:
        return "最接近"
    if score == 3:
        return "很接近"
    if score == 2:
        return "可跟踪"
    return "低优先"


def build_discovery_frame(
    watchlist_groups: dict[str, list[str]],
    market_data: dict[str, pd.DataFrame],
    config: StrategyConfig,
    *,
    plan_capital: float | None = None,
) -> pd.DataFrame:
    if not watchlist_groups:
        return pd.DataFrame(columns=DISCOVERY_COLUMNS)

    unique_symbols = []
    for symbols in watchlist_groups.values():
        for symbol in symbols:
            normalized = normalize_app_symbol(symbol)
            if normalized and normalized not in unique_symbols and is_stock_like_symbol(normalized):
                unique_symbols.append(normalized)
    if not unique_symbols:
        return pd.DataFrame(columns=DISCOVERY_COLUMNS)

    capital_base = float(plan_capital) if plan_capital and plan_capital > 0 else config.initial_capital
    symbol_capital = capital_base / len(unique_symbols) if unique_symbols else 0.0
    reference_amount = symbol_capital * config.entry_position_pct
    strategy = TrendFollowingStrategy(config)
    sector_data = market_data.get(config.sector_symbol)
    if sector_data is None:
        sector_data = market_data.get(normalize_app_symbol(config.sector_symbol))
    rows: list[dict[str, object]] = []

    for group_name, symbols in watchlist_groups.items():
        for raw_symbol in symbols:
            symbol = normalize_app_symbol(raw_symbol)
            if not symbol or not is_stock_like_symbol(symbol) or symbol not in market_data:
                continue
            signal_df = strategy.prepare_with_signals(market_data[symbol], sector_data)
            signal_df = signal_df.dropna(subset=["close", "ma_short", "ma_long", "prior_high", "volume_ma"])
            if signal_df.empty:
                continue

            last_row = signal_df.iloc[-1]
            scoring = score_symbol_signals(last_row, config)
            score = int(scoring["score"])
            close = _safe_float(last_row.get("close"))
            ma_short = _safe_float(last_row.get("ma_short"))
            ma_long = _safe_float(last_row.get("ma_long"))
            prior_high = _safe_float(last_row.get("prior_high"))
            entry_price = max(ma_short, prior_high)
            stop_price = ma_long
            take_profit_price = ma_short * (1 + config.overheat_distance)
            distance_to_entry = close / entry_price - 1 if entry_price > 0 else 0.0
            suggested_shares = reference_amount / close if close > 0 and score >= 3 else None
            signals = dict(scoring["signals"])

            rows.append(
                {
                    "分组": str(group_name),
                    "市场": get_symbol_market_label(symbol),
                    "标的": symbol,
                    "状态": "符合入场" if score >= 4 else "观察",
                    "综合评分": score,
                    "接近程度": _closeness_label(score, distance_to_entry),
                    "收盘价": close,
                    "入场参考价": entry_price,
                    "止损参考价": stop_price,
                    "止盈参考价": take_profit_price,
                    "首仓参考金额": reference_amount if score >= 4 else None,
                    "建议股数": suggested_shares,
                    "距入场参考": distance_to_entry,
                    "转入场条件": _build_entry_condition(last_row, config, scoring, entry_price),
                    "提前关注点": _build_watch_note(scoring),
                    "均线趋势": bool(signals["trend_ok"]),
                    "价格突破": bool(signals["breakout_ok"]),
                    "成交量确认": bool(signals["volume_ok"]),
                    "行业共振": bool(signals["sector_ok"]),
                    "未过热": bool(signals["temperature_ok"]),
                }
            )

    if not rows:
        return pd.DataFrame(columns=DISCOVERY_COLUMNS)
    frame = pd.DataFrame(rows, columns=DISCOVERY_COLUMNS)
    frame["_market_sort"] = frame["标的"].map(lambda symbol: symbol_market_sort_key(str(symbol))[0])
    frame["_distance_abs"] = frame["距入场参考"].abs()
    return frame.sort_values(
        ["_market_sort", "分组", "综合评分", "_distance_abs", "标的"],
        ascending=[True, True, False, True, True],
    ).drop(columns=["_market_sort", "_distance_abs"]).reset_index(drop=True)


def split_discovery_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), frame.copy()
    hits = frame[frame["综合评分"] >= 4].sort_values(["综合评分", "距入场参考", "标的"], ascending=[False, False, True])
    others = frame[frame["综合评分"] < 4].sort_values(["分组", "综合评分", "距入场参考", "标的"], ascending=[True, False, False, True])
    return hits.reset_index(drop=True), others.reset_index(drop=True)
