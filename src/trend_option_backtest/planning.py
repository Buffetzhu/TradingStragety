from __future__ import annotations

import re

import pandas as pd

from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.providers.futu_provider import normalize_symbol
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy

POSITION_COLUMNS = ["标的", "持仓股数", "成本价"]
POSITION_EDITOR_COLUMNS = ["市场", "类型", "正股标的", *POSITION_COLUMNS]
OPTION_SYMBOL_RE = re.compile(r"^(?P<market>[A-Z]+)\.(?P<underlying>[A-Z]{1,10})(?P<expiry>\d{6})(?P<option_type>[CP])(?P<strike>\d+)$")
MARKET_LABELS = {
    "HK": "港股",
    "US": "美股",
    "SH": "A股",
    "SZ": "A股",
    "CN": "A股",
    "SG": "新加坡",
    "HKCC": "港股通",
}
MARKET_SORT_ORDER = {
    "HK": 1,
    "HKCC": 1,
    "US": 2,
    "SH": 3,
    "SZ": 3,
    "CN": 3,
    "SG": 4,
}


def _format_pct(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value * 100:.2f}%"


def _format_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${float(value):,.2f}"


def normalize_app_symbol(symbol: str) -> str:
    if pd.isna(symbol):
        return ""
    clean = str(symbol).upper().strip()
    if not clean or clean == "NAN":
        return ""
    return normalize_symbol(clean).upper().strip()


def normalize_app_symbols(symbols: list[str]) -> list[str]:
    normalized_symbols = []
    for symbol in symbols:
        clean = str(symbol).strip()
        if not clean:
            continue
        normalized_symbols.append(normalize_app_symbol(clean))
    return list(dict.fromkeys(normalized_symbols))


def get_symbol_market(symbol: str) -> str:
    normalized = normalize_app_symbol(symbol)
    if "." not in normalized:
        return "US"
    return normalized.split(".", 1)[0]


def get_symbol_market_label(symbol: str) -> str:
    market = get_symbol_market(symbol)
    return MARKET_LABELS.get(market, market or "其他")


def symbol_market_sort_key(symbol: str) -> tuple[int, str]:
    market = get_symbol_market(symbol)
    return (MARKET_SORT_ORDER.get(market, 99), normalize_app_symbol(symbol))


def parse_option_symbol(symbol: str) -> dict[str, str | float] | None:
    normalized = normalize_app_symbol(symbol)
    match = OPTION_SYMBOL_RE.match(normalized)
    if not match:
        return None
    market = match.group("market")
    underlying = match.group("underlying")
    option_type = "Call" if match.group("option_type") == "C" else "Put"
    expiry = match.group("expiry")
    strike = int(match.group("strike")) / 1000
    return {
        "market": market,
        "underlying": f"{market}.{underlying}",
        "expiry": f"20{expiry[:2]}-{expiry[2:4]}-{expiry[4:6]}",
        "option_type": option_type,
        "strike": strike,
    }


def get_instrument_type(symbol: str) -> str:
    return "期权" if parse_option_symbol(symbol) else "正股/ETF"


def get_underlying_symbol(symbol: str) -> str:
    option_info = parse_option_symbol(symbol)
    return str(option_info["underlying"]) if option_info else normalize_app_symbol(symbol)


def is_stock_like_symbol(symbol: str) -> bool:
    return parse_option_symbol(symbol) is None


def build_position_editor_frame(symbols: list[str], saved_positions: pd.DataFrame) -> pd.DataFrame:
    saved_by_symbol = {
        normalize_app_symbol(row["标的"]): row
        for _, row in saved_positions.iterrows()
        if str(row["标的"]).strip()
    }
    editor_symbols = sorted(normalize_app_symbols([*symbols, *saved_by_symbol.keys()]), key=symbol_market_sort_key)
    rows = []
    for symbol in editor_symbols:
        saved_row = saved_by_symbol.get(symbol)
        rows.append(
            {
                "市场": get_symbol_market_label(symbol),
                "类型": get_instrument_type(symbol),
                "正股标的": get_underlying_symbol(symbol),
                "标的": symbol,
                "持仓股数": float(saved_row["持仓股数"]) if saved_row is not None else 0.0,
                "成本价": float(saved_row["成本价"]) if saved_row is not None else 0.0,
            }
        )
    return pd.DataFrame(rows, columns=POSITION_EDITOR_COLUMNS)


def build_current_positions_map(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    if frame.empty:
        return {}
    normalized = frame.copy()
    normalized["标的"] = normalized["标的"].map(normalize_app_symbol)
    normalized["持仓股数"] = pd.to_numeric(normalized["持仓股数"], errors="coerce").fillna(0.0)
    normalized["成本价"] = pd.to_numeric(normalized["成本价"], errors="coerce").fillna(0.0)
    positions = {}
    for _, row in normalized.iterrows():
        symbol = normalize_app_symbol(row["标的"])
        shares = float(row["持仓股数"])
        if symbol and abs(shares) > 1e-12:
            positions[symbol] = {
                "shares": shares,
                "avg_cost": max(0.0, float(row["成本价"])),
            }
    return positions


def get_position_symbols(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "标的" not in frame.columns:
        return []
    normalized = frame.copy()
    normalized["标的"] = normalized["标的"].map(normalize_app_symbol)
    if "持仓股数" in normalized.columns:
        normalized["持仓股数"] = pd.to_numeric(normalized["持仓股数"], errors="coerce").fillna(0.0)
        normalized = normalized[normalized["持仓股数"].abs() > 1e-12]
    stock_symbols = [symbol for symbol in normalized["标的"].tolist() if is_stock_like_symbol(symbol)]
    return normalize_app_symbols(stock_symbols)


def get_option_position_symbols(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "标的" not in frame.columns:
        return []
    normalized = frame.copy()
    normalized["标的"] = normalized["标的"].map(normalize_app_symbol)
    if "持仓股数" in normalized.columns:
        normalized["持仓股数"] = pd.to_numeric(normalized["持仓股数"], errors="coerce").fillna(0.0)
        normalized = normalized[normalized["持仓股数"].abs() > 1e-12]
    option_symbols = [symbol for symbol in normalized["标的"].tolist() if not is_stock_like_symbol(symbol)]
    return normalize_app_symbols(option_symbols)


def get_current_position(symbol: str, current_positions: dict[str, dict[str, float]]) -> dict[str, float] | None:
    symbol_key = symbol.upper().strip()
    normalized_key = normalize_symbol(symbol_key)
    lookup_keys = [symbol_key, normalized_key]
    if "." in normalized_key:
        lookup_keys.append(normalized_key.split(".", 1)[1])
    for key in lookup_keys:
        if key in current_positions:
            return current_positions[key]
    return None


def build_strategy_watchlist(
    config: StrategyConfig,
    market_data: dict[str, pd.DataFrame],
    trades: list[dict],
    equity_df: pd.DataFrame,
    current_positions: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    rows = []
    strategy = TrendFollowingStrategy(config)
    chart_start = pd.Timestamp(equity_df["date"].min()) if not equity_df.empty else None
    sector_data = market_data.get(config.sector_symbol)
    current_positions = current_positions or {}

    for symbol in config.default_backtest_symbols:
        if symbol not in market_data:
            continue

        signal_df = strategy.prepare_with_signals(market_data[symbol], sector_data)
        if chart_start is not None:
            signal_df = signal_df[pd.to_datetime(signal_df["date"]) >= chart_start]
        signal_df = signal_df.dropna(subset=["close", "ma_short", "ma_long", "prior_high", "volume_ma"])
        if signal_df.empty:
            continue

        last_row = signal_df.iloc[-1]
        close = float(last_row["close"])
        ma_short = float(last_row["ma_short"])
        ma_long = float(last_row["ma_long"])
        prior_high = float(last_row["prior_high"])
        reduce_price = ma_short * (1 + config.overheat_distance)
        entry_watch_price = max(ma_short, prior_high)
        symbol_trades = [trade for trade in trades if trade["symbol"] == symbol]
        latest_trade = symbol_trades[-1] if symbol_trades else None

        current_position_value = 0.0
        current_position_shares = 0.0
        current_position_cost = 0.0
        current_position_source = "回测模拟"
        manual_position = get_current_position(symbol, current_positions)
        if manual_position and abs(float(manual_position.get("shares", 0.0))) > 1e-12:
            current_position_source = "手动持仓"
            current_position_shares = float(manual_position.get("shares", 0.0))
            current_position_cost = float(manual_position.get("avg_cost", 0.0))
            current_position_value = abs(current_position_shares) * close
        elif latest_trade and latest_trade["action"] != "清仓" and symbol in equity_df.columns:
            last_symbol_equity = float(equity_df[symbol].dropna().iloc[-1])
            current_position_value = max(0.0, last_symbol_equity - float(latest_trade["cash_after"]))
            current_position_shares = max(0.0, float(latest_trade.get("position_shares_after", 0.0)))
            current_position_cost = max(0.0, float(latest_trade.get("avg_cost_after", 0.0)))
        current_position_pct = current_position_value / config.initial_capital if config.initial_capital else 0.0
        unrealized_pnl = (
            current_position_shares * (close - current_position_cost)
            if abs(current_position_shares) > 1e-12 and current_position_cost > 0
            else 0.0
        )
        status = "持仓" if abs(current_position_shares) > 1e-12 or current_position_pct > 0 else "空仓"

        trend_ok = ma_short > ma_long
        sector_ok = bool(last_row["sector_ok"])
        volume_ok = float(last_row["volume"]) > float(last_row["volume_ma"]) * config.volume_multiplier
        entry_signal = bool(last_row["entry_signal"])
        add_signal = bool(last_row["add_signal"])
        reduce_signal = bool(last_row["reduce_signal"])
        exit_signal = bool(last_row["exit_signal"])

        if status == "持仓":
            if exit_signal:
                next_action = f"触发清仓：收盘价低于 MA{config.ma_long}"
            elif reduce_signal:
                next_action = "处于过热区：关注是否减仓或等待冷却"
            elif add_signal:
                next_action = f"触发加仓：回踩 MA{config.ma_short} 后收回"
            else:
                next_action = f"继续持仓：关注 MA{config.ma_short} 回踩和 MA{config.ma_long} 防线"
            key_price = ma_long
            distance_to_key = close / key_price - 1 if key_price else 0.0
            key_label = f"清仓线 MA{config.ma_long}"
        else:
            if entry_signal:
                next_action = "触发入场：突破、量能、趋势条件已满足"
            elif not trend_ok:
                next_action = f"等待趋势修复：MA{config.ma_short} 重新高于 MA{config.ma_long}"
            elif config.use_sector_filter and not sector_ok:
                next_action = f"等待板块共振：{config.sector_symbol} 站上 MA{config.ma_short}"
            elif not volume_ok:
                next_action = "等待量能放大后突破"
            else:
                next_action = f"等待突破过去 {config.breakout_days} 日前高"
            key_price = entry_watch_price
            distance_to_key = close / key_price - 1 if key_price else 0.0
            key_label = "入场观察价"

        rows.append(
            {
                "市场": get_symbol_market_label(symbol),
                "标的": symbol,
                "状态": status,
                "收盘价": close,
                f"MA{config.ma_short}": ma_short,
                f"MA{config.ma_long}": ma_long,
                f"{config.breakout_days}日前高": prior_high,
                "过热价": reduce_price,
                "持仓来源": current_position_source,
                "当前持仓股数": current_position_shares,
                "成本价": current_position_cost,
                "当前持仓市值": current_position_value,
                "持仓浮盈亏": unrealized_pnl,
                "当前持仓占比": current_position_pct,
                "当前信号": " / ".join(
                    [
                        label
                        for label, active in [
                            ("入场", entry_signal),
                            ("加仓", add_signal),
                            ("减仓", reduce_signal),
                            ("清仓", exit_signal),
                        ]
                        if active
                    ]
                )
                or "无",
                "关键价位": key_label,
                "距关键价位": distance_to_key,
                "下一步关注": next_action,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["_market_sort"] = frame["标的"].map(lambda symbol: symbol_market_sort_key(symbol)[0])
    return frame.sort_values(["_market_sort", "标的"]).drop(columns=["_market_sort"]).reset_index(drop=True)


def build_strategy_plan(watchlist_df: pd.DataFrame, config: StrategyConfig, plan_capital: float | None = None) -> pd.DataFrame:
    if watchlist_df.empty:
        return pd.DataFrame()

    rows = []
    capital_base = float(plan_capital) if plan_capital and plan_capital > 0 else config.initial_capital
    symbol_capital = capital_base / len(config.default_backtest_symbols) if config.default_backtest_symbols else 0.0
    for _, row in watchlist_df.iterrows():
        status = str(row["状态"])
        signals = str(row["当前信号"])
        close = float(row["收盘价"])
        position_value = float(row.get("当前持仓市值", 0.0))
        position_shares = float(row.get("当前持仓股数", 0.0))
        distance_to_key = float(row["距关键价位"])
        priority_rank = 5
        priority = "观察等待"
        plan_action = "等待"
        reference_amount = None
        suggested_shares = None
        target_position_delta = 0.0
        amount_note = "暂不交易"
        trigger = str(row["下一步关注"])
        risk_control = str(row["关键价位"])
        note = "保持观察，等待下一次信号确认。"

        if status == "持仓":
            if "清仓" in signals:
                priority_rank = 1
                priority = "立即处理"
                plan_action = "清仓"
                reference_amount = position_value
                suggested_shares = position_shares
                target_position_delta = -position_value
                amount_note = "当前清仓参考"
                note = "趋势防线失效，优先保护本金和已有利润。"
            elif "减仓" in signals:
                priority_rank = 2
                priority = "降低风险"
                plan_action = "减仓"
                reference_amount = position_value * config.reduce_position_pct
                suggested_shares = position_shares * config.reduce_position_pct
                target_position_delta = -reference_amount
                amount_note = "当前减仓参考"
                risk_control = "短线过热区"
                note = f"按当前规则先减掉约 {_format_pct(config.reduce_position_pct)} 持仓，等待冷却。"
            elif "加仓" in signals:
                priority_rank = 3
                priority = "顺势加仓"
                plan_action = "加仓"
                reference_amount = symbol_capital * config.add_position_pct
                suggested_shares = reference_amount / close if close > 0 else None
                target_position_delta = reference_amount
                amount_note = "当前加仓参考"
                note = f"回踩 MA{config.ma_short} 后收回，适合小步顺势增加仓位。"
            else:
                priority_rank = 4
                priority = "持仓跟踪"
                plan_action = "继续持仓"
                note = f"未触发交易动作，重点看 MA{config.ma_long} 防线是否保持。"
        else:
            if "入场" in signals:
                priority_rank = 2
                priority = "准备入场"
                plan_action = "建仓"
                reference_amount = symbol_capital * config.entry_position_pct
                suggested_shares = reference_amount / close if close > 0 else None
                target_position_delta = reference_amount
                amount_note = "当前建仓参考"
                note = f"突破和量能条件满足，按首次建仓比例 {_format_pct(config.entry_position_pct)} 执行。"
            else:
                priority_rank = 5 if distance_to_key < -0.03 else 4
                priority = "观察等待" if priority_rank == 5 else "接近触发"
                plan_action = "等待触发"
                trigger_amount = symbol_capital * config.entry_position_pct
                trigger_shares = trigger_amount / close if close > 0 else 0.0
                amount_note = f"触发后参考 {_format_money(trigger_amount)} / {trigger_shares:,.4f} 股"
                note = "未满足完整入场条件，先放入观察队列。"

        rows.append(
            {
                "优先级排序": priority_rank,
                "市场": row.get("市场", get_symbol_market_label(row["标的"])),
                "标的": row["标的"],
                "状态": status,
                "计划动作": plan_action,
                "优先级": priority,
                "参考交易金额": reference_amount,
                "建议股数": suggested_shares,
                "目标仓位差额": target_position_delta,
                "金额说明": amount_note,
                "收盘价": close,
                "距关键价位": distance_to_key,
                "触发依据": trigger,
                "风控关注": risk_control,
                "计划说明": note,
            }
        )

    plan_df = pd.DataFrame(rows)
    plan_df["_market_sort"] = plan_df["标的"].map(lambda symbol: symbol_market_sort_key(symbol)[0])
    return plan_df.sort_values(["_market_sort", "优先级排序", "距关键价位"], ascending=[True, True, False]).drop(
        columns=["_market_sort"]
    ).reset_index(drop=True)


def assess_option_overlay(option_type: str, direction: str, underlying_plan: pd.Series | None) -> tuple[str, str, str]:
    if underlying_plan is None:
        return (
            "待关联正股",
            "先将正股加入股票池并运行回测，再判断这张期权是否服务于当前策略计划。",
            "缺少正股计划，暂不判断保护或增强收益效果。",
        )

    plan_action = str(underlying_plan["计划动作"])
    status = str(underlying_plan["状态"])
    reducing_risk = plan_action in {"清仓", "减仓"}
    increasing_exposure = plan_action in {"建仓", "加仓"}

    if option_type == "Put" and direction == "多头":
        if reducing_risk:
            return (
                "保护性 Put",
                "正股计划正在降风险，Put 可作为下行保护；若正股减掉较多，需同步评估是否止盈或降低保护仓。",
                "关注权利金回吐、到期时间和正股减仓后的保护比例是否过高。",
            )
        return (
            "保护性 Put",
            "正股仍在观察或持有，Put 可作为保险仓；先确认保护成本是否在可接受范围内。",
            "时间价值会持续衰减，正股不跌时保护仓可能拖累组合收益。",
        )

    if option_type == "Put" and direction == "空头":
        if reducing_risk:
            return (
                "卖出 Put 风险敞口",
                "正股计划偏降风险，但卖出 Put 会在下跌时增加接股义务；优先评估是否需要回补或降低张数。",
                "下跌、波动率上升或被指派时，组合风险会放大。",
            )
        return (
            "现金担保 Put",
            "若本来愿意低位接正股，可作为等待入场的增强收益仓；需要预留足额购买力。",
            "标的快速下跌时可能被动接股，需提前确认可承受的最大正股仓位。",
        )

    if option_type == "Call" and direction == "多头":
        if reducing_risk:
            return (
                "进攻性 Call",
                "正股计划偏降风险，Call 与当前风控方向不完全一致；只适合保留小额上行观察仓。",
                "到期前若趋势未恢复，权利金可能快速损耗。",
            )
        if increasing_exposure:
            return (
                "进攻性 Call",
                "正股计划偏建仓或加仓，Call 可作为有限亏损的上行替代；注意别和正股加仓重复放大风险。",
                "杠杆敞口高，需控制权利金占组合比例。",
            )
        return (
            "上行观察 Call",
            "正股未触发强动作，Call 适合按小仓位跟踪趋势恢复。",
            "时间价值衰减较快，等待信号时不宜让权利金暴露过大。",
        )

    if option_type == "Call" and direction == "空头":
        if status == "持仓" and not reducing_risk:
            return (
                "备兑 Call",
                "正股仍在持仓跟踪，卖出 Call 更偏增强收益；需要确认行权价不会过早限制核心持仓上涨空间。",
                "突破行情中可能被迫让渡上行收益。",
            )
        if reducing_risk:
            return (
                "卖出 Call 风险敞口",
                "正股计划若减仓或清仓，卖出 Call 可能从备兑变成裸露风险；先同步检查正股覆盖数量。",
                "正股强反弹时，裸卖 Call 风险不对称。",
            )
        return (
            "卖出 Call 增强收益",
            "正股尚未确认持仓覆盖，先确认是否有足够正股或组合对冲，再把它视为增强收益仓。",
            "缺少覆盖时，上涨风险可能超过已收权利金。",
        )

    return (
        "待复核",
        "期权方向无法归类到当前简化 Overlay 规则，先保留人工复核。",
        "检查期权代码、持仓方向和正股计划是否正确。",
    )


def get_option_days_to_expiry(expiry: str) -> int | None:
    expiry_date = pd.to_datetime(expiry, errors="coerce")
    if pd.isna(expiry_date):
        return None
    return int((expiry_date.normalize() - pd.Timestamp.today().normalize()).days)


def build_option_coverage(option_type: str, direction: str, contract_shares: float, underlying_shares: float) -> tuple[float | None, str]:
    if contract_shares <= 0:
        return None, "缺少合约数量"
    if abs(underlying_shares) <= 1e-12:
        if option_type == "Put" and direction == "空头":
            return None, "无正股，需用现金或购买力覆盖潜在接股"
        return None, "无对应正股持仓"

    if option_type == "Put" and direction == "多头":
        return contract_shares / abs(underlying_shares), "保护比例"
    if option_type == "Call" and direction == "空头":
        return abs(underlying_shares) / contract_shares, "备兑覆盖比例"
    if option_type == "Call" and direction == "多头":
        return contract_shares / abs(underlying_shares), "上行杠杆敞口比例"
    if option_type == "Put" and direction == "空头":
        return contract_shares / abs(underlying_shares), "潜在接股比例"
    return None, "待复核"


def build_option_overlay_summary(positions_df: pd.DataFrame, strategy_plan_df: pd.DataFrame) -> pd.DataFrame:
    if positions_df.empty:
        return pd.DataFrame()

    normalized = positions_df.copy()
    normalized["标的"] = normalized["标的"].map(normalize_app_symbol)
    normalized["持仓股数"] = pd.to_numeric(normalized["持仓股数"], errors="coerce").fillna(0.0)
    normalized["成本价"] = pd.to_numeric(normalized["成本价"], errors="coerce").fillna(0.0)
    underlying_positions = {
        normalize_app_symbol(row["标的"]): float(row["持仓股数"])
        for _, row in normalized.iterrows()
        if is_stock_like_symbol(str(row["标的"])) and abs(float(row["持仓股数"])) > 1e-12
    }
    plan_by_symbol = {
        normalize_app_symbol(row["标的"]): row
        for _, row in strategy_plan_df.iterrows()
        if str(row.get("标的", "")).strip()
    }

    rows = []
    for _, row in normalized.iterrows():
        symbol = normalize_app_symbol(row["标的"])
        option_info = parse_option_symbol(symbol)
        shares = float(row["持仓股数"])
        if option_info is None or abs(shares) <= 1e-12:
            continue

        underlying = str(option_info["underlying"])
        underlying_plan = plan_by_symbol.get(underlying)
        direction = "多头" if shares > 0 else "空头"
        role, overlay_note, risk_note = assess_option_overlay(str(option_info["option_type"]), direction, underlying_plan)
        contract_shares = abs(shares) * 100
        underlying_shares = float(underlying_positions.get(underlying, 0.0))
        coverage_ratio, coverage_label = build_option_coverage(
            str(option_info["option_type"]), direction, contract_shares, underlying_shares
        )
        rows.append(
            {
                "市场": get_symbol_market_label(symbol),
                "期权代码": symbol,
                "正股标的": underlying,
                "期权类型": option_info["option_type"],
                "到期日": option_info["expiry"],
                "到期天数": get_option_days_to_expiry(str(option_info["expiry"])),
                "行权价": option_info["strike"],
                "持仓方向": direction,
                "持仓数量": shares,
                "合约对应股数": contract_shares,
                "正股持仓股数": underlying_shares,
                "覆盖口径": coverage_label,
                "覆盖/保护比例": coverage_ratio,
                "成本价": float(row["成本价"]),
                "正股计划动作": str(underlying_plan["计划动作"]) if underlying_plan is not None else "未纳入回测",
                "正股优先级": str(underlying_plan["优先级"]) if underlying_plan is not None else "未纳入回测",
                "正股触发依据": str(underlying_plan["触发依据"]) if underlying_plan is not None else "请先将正股加入股票池并运行回测",
                "正股风控关注": str(underlying_plan["风控关注"]) if underlying_plan is not None else "未纳入回测",
                "Overlay角色": role,
                "观察建议": overlay_note,
                "风险提示": risk_note,
            }
        )

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        return summary_df
    summary_df["_market_sort"] = summary_df["期权代码"].map(lambda symbol: symbol_market_sort_key(symbol)[0])
    return summary_df.sort_values(["_market_sort", "正股标的", "到期日", "期权代码"]).drop(columns=["_market_sort"]).reset_index(drop=True)


def _format_strike_range(strikes: pd.Series) -> str:
    strike_values = pd.to_numeric(strikes, errors="coerce").dropna().sort_values().tolist()
    if not strike_values:
        return ""
    if len(set(strike_values)) == 1:
        return f"{strike_values[0]:,.2f}"
    return f"{strike_values[0]:,.2f} - {strike_values[-1]:,.2f}"


def _format_combo_contracts(contracts: pd.Series, *, paired: bool = False) -> float:
    contract_values = pd.to_numeric(contracts, errors="coerce").fillna(0.0).abs()
    contract_values = contract_values[contract_values > 1e-12]
    if contract_values.empty:
        return 0.0
    if paired:
        return float(contract_values.min())
    return float(contract_values.sum())


def _build_combo_row(
    group: pd.DataFrame,
    selected_legs: pd.DataFrame,
    *,
    combo_type: str,
    combo_direction: str,
    combo_note: str,
    risk_note: str,
    paired_contracts: bool = False,
) -> dict[str, object]:
    first_row = group.iloc[0]
    return {
        "市场": str(first_row.get("市场", "")),
        "正股标的": str(first_row.get("正股标的", "")),
        "到期日": str(first_row.get("到期日", "")),
        "组合类型": combo_type,
        "组合方向": combo_direction,
        "期权腿数": int(len(selected_legs)),
        "合约张数": _format_combo_contracts(selected_legs.get("持仓数量", pd.Series(dtype=float)), paired=paired_contracts),
        "行权价区间": _format_strike_range(selected_legs.get("行权价", pd.Series(dtype=float))),
        "涉及合约": "、".join(selected_legs["期权代码"].map(str).tolist()) if "期权代码" in selected_legs.columns else "",
        "组合说明": combo_note,
        "风险提示": risk_note,
    }


def _classify_vertical_spread(option_type: str, type_group: pd.DataFrame) -> tuple[str, str, str, str]:
    long_legs = type_group[type_group["持仓方向"].map(str) == "多头"]
    short_legs = type_group[type_group["持仓方向"].map(str) == "空头"]
    if long_legs.empty or short_legs.empty:
        return ("", "", "", "")

    long_strike = float(pd.to_numeric(long_legs["行权价"], errors="coerce").mean())
    short_strike = float(pd.to_numeric(short_legs["行权价"], errors="coerce").mean())
    if option_type == "Call":
        if long_strike < short_strike:
            return (
                "Bull Call Spread",
                "看涨价差",
                "用较低行权价多头 Call 搭配较高行权价空头 Call，限制成本并保留区间上行。",
                "最大收益通常受高行权价空头 Call 限制，若标的大跌，多头权利金仍可能损耗。",
            )
        return (
            "Bear Call Spread",
            "偏空/收权利金价差",
            "用较低行权价空头 Call 搭配较高行权价多头 Call，表达上行受限或偏空观点。",
            "标的突破低行权价后风险上升，需要关注保证金、波动率和到期前回补成本。",
        )
    if short_strike > long_strike:
        return (
            "Bull Put Spread",
            "偏多/收权利金价差",
            "用较高行权价空头 Put 搭配较低行权价多头 Put，表达不跌破支撑的观点。",
            "若标的跌破高行权价，组合亏损会扩大；低行权价 Put 只提供下方有限保护。",
        )
    return (
        "Bear Put Spread",
        "看跌价差",
        "用较高行权价多头 Put 搭配较低行权价空头 Put，保留区间下跌收益并降低权利金成本。",
        "最大收益通常受低行权价空头 Put 限制，若标的不跌，权利金仍可能损耗。",
    )


def build_option_combo_summary(option_overlay_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["市场", "正股标的", "到期日", "组合类型", "组合方向", "期权腿数", "合约张数", "行权价区间", "涉及合约", "组合说明", "风险提示"]
    if option_overlay_df.empty:
        return pd.DataFrame(columns=columns)
    required_columns = {"正股标的", "到期日", "期权类型", "持仓方向", "行权价", "期权代码", "持仓数量"}
    if not required_columns.issubset(option_overlay_df.columns):
        return pd.DataFrame(columns=columns)

    normalized = option_overlay_df.copy()
    normalized["行权价"] = pd.to_numeric(normalized["行权价"], errors="coerce")
    normalized["持仓数量"] = pd.to_numeric(normalized["持仓数量"], errors="coerce").fillna(0.0)
    if "正股持仓股数" not in normalized.columns:
        normalized["正股持仓股数"] = 0.0
    normalized["正股持仓股数"] = pd.to_numeric(normalized["正股持仓股数"], errors="coerce").fillna(0.0)
    normalized = normalized[(normalized["持仓数量"].abs() > 1e-12) & normalized["行权价"].notna()].copy()
    if normalized.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for _, group in normalized.groupby(["正股标的", "到期日"], sort=False):
        group = group.sort_values(["期权类型", "行权价", "期权代码"]).reset_index(drop=True)
        used_contracts: set[str] = set()

        for option_type, type_group in group.groupby("期权类型", sort=False):
            type_group = type_group[~type_group["期权代码"].map(str).isin(used_contracts)]
            directions = set(type_group["持仓方向"].map(str).tolist())
            if len(type_group) != 2 or not {"多头", "空头"}.issubset(directions):
                continue
            combo_type, combo_direction, combo_note, risk_note = _classify_vertical_spread(str(option_type), type_group)
            if combo_type:
                rows.append(
                    _build_combo_row(
                        group,
                        type_group,
                        combo_type=combo_type,
                        combo_direction=combo_direction,
                        combo_note=combo_note,
                        risk_note=risk_note,
                        paired_contracts=True,
                    )
                )
                used_contracts.update(type_group["期权代码"].map(str).tolist())

        for direction, combo_prefix in [("多头", "Long"), ("空头", "Short")]:
            available_group = group[~group["期权代码"].map(str).isin(used_contracts)]
            direction_calls = available_group[(available_group["期权类型"].map(str) == "Call") & (available_group["持仓方向"].map(str) == direction)]
            direction_puts = available_group[(available_group["期权类型"].map(str) == "Put") & (available_group["持仓方向"].map(str) == direction)]
            if len(direction_calls) != 1 or len(direction_puts) != 1:
                continue
            selected_legs = pd.concat([direction_calls, direction_puts]).sort_values(["期权类型", "行权价"])
            call_strike = float(pd.to_numeric(direction_calls["行权价"], errors="coerce").mean())
            put_strike = float(pd.to_numeric(direction_puts["行权价"], errors="coerce").mean())
            is_straddle = abs(call_strike - put_strike) < 1e-9
            combo_type = f"{combo_prefix} {'Straddle' if is_straddle else 'Strangle'}"
            combo_direction = "波动率多头" if direction == "多头" else "波动率空头"
            combo_note = "同时持有同向 Call 和 Put，主要表达波动率或大幅方向突破观点。" if direction == "多头" else "同时卖出 Call 和 Put，主要表达区间震荡和收取权利金观点。"
            risk_note = "若标的波动不足，双腿权利金可能同时衰减。" if direction == "多头" else "若标的大幅单边突破，裸卖一侧风险可能快速放大。"
            rows.append(
                _build_combo_row(
                    group,
                    selected_legs,
                    combo_type=combo_type,
                    combo_direction=combo_direction,
                    combo_note=combo_note,
                    risk_note=risk_note,
                    paired_contracts=True,
                )
            )
            used_contracts.update(selected_legs["期权代码"].map(str).tolist())

        available_group = group[~group["期权代码"].map(str).isin(used_contracts)]
        long_puts = available_group[(available_group["期权类型"].map(str) == "Put") & (available_group["持仓方向"].map(str) == "多头")]
        short_calls = available_group[(available_group["期权类型"].map(str) == "Call") & (available_group["持仓方向"].map(str) == "空头")]
        if len(long_puts) == 1 and len(short_calls) == 1:
            selected_legs = pd.concat([long_puts, short_calls]).sort_values(["期权类型", "行权价"])
            rows.append(
                _build_combo_row(
                    group,
                    selected_legs,
                    combo_type="Collar",
                    combo_direction="保护持仓",
                    combo_note="正股持仓搭配多头 Put 和空头 Call，用上行封顶换取下行保护成本降低。",
                    risk_note="上涨超过空头 Call 行权价时可能让渡收益；下跌保护主要取决于多头 Put 的行权价和到期时间。",
                    paired_contracts=True,
                )
            )
            used_contracts.update(selected_legs["期权代码"].map(str).tolist())

        group_has_summary = any(row["正股标的"] == str(group.iloc[0].get("正股标的", "")) and row["到期日"] == str(group.iloc[0].get("到期日", "")) for row in rows)
        if not group_has_summary and len(group) > 1:
            rows.append(
                _build_combo_row(
                    group,
                    group,
                    combo_type="待复核组合",
                    combo_direction="人工确认",
                    combo_note="同一正股和到期日存在多条期权腿，但当前规则无法可靠归类。",
                    risk_note="请检查是否为比例价差、蝶式、铁鹰、日历或其他复杂结构。",
                )
            )

    combo_df = pd.DataFrame(rows, columns=columns)
    if combo_df.empty:
        return combo_df
    combo_df["_market_sort"] = combo_df["正股标的"].map(lambda symbol: symbol_market_sort_key(symbol)[0])
    return combo_df.sort_values(["_market_sort", "正股标的", "到期日", "组合类型"]).drop(columns=["_market_sort"]).reset_index(drop=True)


def extract_combo_contract_symbols(option_combo_df: pd.DataFrame) -> set[str]:
    if option_combo_df.empty or "涉及合约" not in option_combo_df.columns:
        return set()
    contracts: set[str] = set()
    for value in option_combo_df["涉及合约"].dropna().map(str):
        contracts.update(contract.strip() for contract in value.split("、") if contract.strip())
    return contracts


def filter_unmatched_option_legs(option_overlay_df: pd.DataFrame, option_combo_df: pd.DataFrame) -> pd.DataFrame:
    if option_overlay_df.empty or "期权代码" not in option_overlay_df.columns:
        return option_overlay_df.copy()
    combo_contracts = extract_combo_contract_symbols(option_combo_df)
    if not combo_contracts:
        return option_overlay_df.copy()
    return option_overlay_df[~option_overlay_df["期权代码"].map(str).isin(combo_contracts)].reset_index(drop=True)
