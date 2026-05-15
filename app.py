from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trend_option_backtest.demo_data import make_demo_market_data
from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider, normalize_symbol
from trend_option_backtest.services.backtest_service import BacktestService
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy


DEFAULT_CONFIG_PATH = ROOT / "config" / "default_config.json"
BACKTEST_HISTORY_PATH = ROOT / "data" / "backtest_run_history.csv"
STRATEGY_PRESETS_PATH = ROOT / "data" / "strategy_presets.json"
CURRENT_POSITIONS_PATH = ROOT / "data" / "current_positions.csv"
BACKTEST_HISTORY_LIMIT = 200
POSITION_COLUMNS = ["标的", "持仓股数", "成本价"]
BACKTEST_PERIOD_OPTIONS = {
    "1 个月": 1 / 12,
    "3 个月": 0.25,
    "6 个月": 0.5,
    "1 年": 1.0,
    "2 年": 2.0,
    "3 年": 3.0,
    "5 年": 5.0,
}
STRATEGY_PARAM_KEYS = [
    "ma_short",
    "ma_long",
    "breakout_days",
    "volume_multiplier",
    "overheat_distance",
    "entry_position_pct",
    "add_position_pct",
    "reduce_position_pct",
    "min_trade_amount",
    "use_sector_filter",
]


@st.cache_data(show_spinner=False)
def load_default_config() -> dict:
    return StrategyConfig.from_json(DEFAULT_CONFIG_PATH).to_dict()


def build_config(payload: dict) -> StrategyConfig:
    return StrategyConfig.from_dict(payload)


def format_pct(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value * 100:.2f}%"


def format_profit_factor(value: float | int | str, closed_trade_count: int) -> str:
    if closed_trade_count == 0:
        return "N/A"
    if value == float("inf"):
        return "∞"
    return f"{float(value):.2f}"


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


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


def load_backtest_history() -> list[dict]:
    if not BACKTEST_HISTORY_PATH.exists():
        return []
    frame = pd.read_csv(BACKTEST_HISTORY_PATH)
    if frame.empty:
        return []
    return frame.tail(BACKTEST_HISTORY_LIMIT).to_dict("records")


def save_backtest_history(rows: list[dict]) -> None:
    BACKTEST_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows[-BACKTEST_HISTORY_LIMIT:]).to_csv(BACKTEST_HISTORY_PATH, index=False, encoding="utf-8-sig")


def clear_backtest_history() -> None:
    if BACKTEST_HISTORY_PATH.exists():
        BACKTEST_HISTORY_PATH.unlink()


def load_strategy_presets() -> dict[str, dict]:
    if not STRATEGY_PRESETS_PATH.exists():
        return {}
    with STRATEGY_PRESETS_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        return {}
    return {str(name): dict(value) for name, value in payload.items() if isinstance(value, dict)}


def save_strategy_presets(presets: dict[str, dict]) -> None:
    STRATEGY_PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STRATEGY_PRESETS_PATH.open("w", encoding="utf-8") as file:
        json.dump(presets, file, ensure_ascii=False, indent=2)


def load_current_positions() -> pd.DataFrame:
    if not CURRENT_POSITIONS_PATH.exists():
        return pd.DataFrame(columns=POSITION_COLUMNS)
    frame = pd.read_csv(CURRENT_POSITIONS_PATH)
    for column in POSITION_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0 if column != "标的" else ""
    frame = frame[POSITION_COLUMNS].copy()
    frame["标的"] = frame["标的"].map(normalize_app_symbol)
    frame["持仓股数"] = pd.to_numeric(frame["持仓股数"], errors="coerce").fillna(0.0)
    frame["成本价"] = pd.to_numeric(frame["成本价"], errors="coerce").fillna(0.0)
    return frame[frame["标的"] != ""].reset_index(drop=True)


def save_current_positions(frame: pd.DataFrame) -> None:
    CURRENT_POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = frame.copy()
    for column in POSITION_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = 0.0 if column != "标的" else ""
    normalized = normalized[POSITION_COLUMNS].copy()
    normalized["标的"] = normalized["标的"].map(normalize_app_symbol)
    normalized["持仓股数"] = pd.to_numeric(normalized["持仓股数"], errors="coerce").fillna(0.0)
    normalized["成本价"] = pd.to_numeric(normalized["成本价"], errors="coerce").fillna(0.0)
    normalized = normalized[(normalized["标的"] != "") & (normalized["持仓股数"] > 0)]
    if not normalized.empty:
        normalized["持仓成本"] = normalized["持仓股数"] * normalized["成本价"]
        normalized = normalized.groupby("标的", as_index=False).agg({"持仓股数": "sum", "持仓成本": "sum"})
        normalized["成本价"] = normalized["持仓成本"] / normalized["持仓股数"]
        normalized = normalized[POSITION_COLUMNS]
    normalized.to_csv(CURRENT_POSITIONS_PATH, index=False, encoding="utf-8-sig")


def build_position_editor_frame(symbols: list[str], saved_positions: pd.DataFrame) -> pd.DataFrame:
    saved_by_symbol = {
        normalize_app_symbol(row["标的"]): row
        for _, row in saved_positions.iterrows()
        if str(row["标的"]).strip()
    }
    editor_symbols = normalize_app_symbols([*symbols, *saved_by_symbol.keys()])
    rows = []
    for symbol in editor_symbols:
        saved_row = saved_by_symbol.get(symbol)
        rows.append(
            {
                "标的": symbol,
                "持仓股数": float(saved_row["持仓股数"]) if saved_row is not None else 0.0,
                "成本价": float(saved_row["成本价"]) if saved_row is not None else 0.0,
            }
        )
    return pd.DataFrame(rows, columns=POSITION_COLUMNS)


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
        if symbol and shares > 0:
            positions[symbol] = {
                "shares": shares,
                "avg_cost": max(0.0, float(row["成本价"])),
            }
    return positions


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


def build_backtest_history_row(
    config: StrategyConfig,
    data_source: str,
    result,
    equity_df: pd.DataFrame,
    run_mode: str,
) -> dict:
    closed_trade_count = int(result.metrics.get("closed_trade_count", 0))
    start_date = pd.Timestamp(equity_df["date"].min()).date().isoformat() if not equity_df.empty else ""
    end_date = pd.Timestamp(equity_df["date"].max()).date().isoformat() if not equity_df.empty else ""
    return {
        "运行时间": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "运行模式": run_mode,
        "数据源": data_source,
        "标的数": len(config.default_backtest_symbols),
        "标的": "、".join(config.default_backtest_symbols),
        "区间": f"{start_date} 至 {end_date}" if start_date and end_date else "",
        "周期年": config.backtest_years,
        "本金": config.initial_capital,
        "总收益率": float(result.metrics["total_return"]),
        "最大回撤": float(result.metrics["max_drawdown"]),
        "Sharpe": float(result.metrics["sharpe"]),
        "已实现胜率": None if closed_trade_count == 0 else float(result.metrics["win_rate"]),
        "已实现PF": None if closed_trade_count == 0 else result.metrics["profit_factor"],
        "交易动作": int(result.metrics["trade_count"]),
        "已实现动作": closed_trade_count,
        "MA短": config.ma_short,
        "MA长": config.ma_long,
        "突破天数": config.breakout_days,
        "量能倍数": config.volume_multiplier,
        "过热距离": config.overheat_distance,
        "首次建仓": config.entry_position_pct,
        "单次加仓": config.add_position_pct,
        "单次减仓": config.reduce_position_pct,
        "最小成交额": config.min_trade_amount,
    }


def build_strategy_summary(config: StrategyConfig, data_source: str) -> str:
    symbols = "、".join(config.default_backtest_symbols)
    sector_filter = (
        f"启用 {config.sector_symbol} 板块共振过滤，只有板块站上 MA{config.ma_short} 时才允许入场/加仓。"
        if config.use_sector_filter
        else "不启用板块共振过滤，个股信号独立生效。"
    )
    symbol_capital = config.initial_capital / len(config.default_backtest_symbols) if config.default_backtest_symbols else 0.0
    return f"""
**策略定位**：趋势跟随 + 突破确认 + 分批仓位管理。它试图在趋势已经走强时介入，回踩不破短均线时继续加仓，涨得过快时先释放一部分风险，跌破长趋势线时退出。

**当前回测对象**：{symbols}。数据源为 {data_source}，模拟初始资金为 ${config.initial_capital:,.0f}，每个标的初始分配约 ${symbol_capital:,.0f}。

**入场逻辑**：收盘价站上 MA{config.ma_short}，MA{config.ma_short} 高于 MA{config.ma_long}，收盘价突破过去 {config.breakout_days} 日前高，并且成交量大于 {config.volume_multiplier:g} 倍均量。{sector_filter}

**加仓逻辑**：已持仓后，如果盘中回踩 MA{config.ma_short} 且收盘重新站上短均线，同时趋势结构仍然有效，则按单次加仓比例继续加仓。

**减仓逻辑**：如果收盘价距离 MA{config.ma_short} 超过 {format_pct(config.overheat_distance)}，视为短线过热，减掉当前持仓的 {format_pct(config.reduce_position_pct)}。同一轮连续过热只触发一次，冷却后再次过热才会再次减仓。

**清仓逻辑**：如果收盘价跌破 MA{config.ma_long}，认为中期趋势失效，清掉该标的剩余持仓。

**仓位执行**：首次建仓使用该标的权益的 {format_pct(config.entry_position_pct)}，单次加仓使用该标的权益的 {format_pct(config.add_position_pct)}，单次减仓卖出当前持仓的 {format_pct(config.reduce_position_pct)}。低于 ${config.min_trade_amount:,.0f} 的加仓/减仓会跳过，避免碎片交易。
"""


def build_symbol_performance_summary(
    equity_df: pd.DataFrame,
    trades: list[dict],
    symbols: list[str],
    initial_capital: float,
) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        if symbol not in equity_df.columns:
            continue

        equity = equity_df[["date", symbol]].dropna().copy()
        if equity.empty:
            continue

        values = equity[symbol].astype(float)
        first_value = float(values.iloc[0])
        last_value = float(values.iloc[-1])
        total_return = last_value / first_value - 1 if first_value else 0.0
        drawdown = values / values.cummax() - 1
        symbol_trades = [trade for trade in trades if trade["symbol"] == symbol]
        latest_trade = symbol_trades[-1] if symbol_trades else None
        current_position_value = 0.0
        if latest_trade and latest_trade["action"] not in {"清仓", "期末平仓"}:
            current_position_value = max(0.0, last_value - float(latest_trade["cash_after"]))
        current_position_pct = current_position_value / initial_capital if initial_capital else 0.0
        current_status = "持仓" if current_position_pct > 0 else "空仓"
        realized_pnl = sum(
            float(trade["realized_pnl"])
            for trade in symbol_trades
            if trade.get("realized_pnl") is not None and not pd.isna(trade["realized_pnl"])
        )

        rows.append(
            {
                "标的": symbol,
                "当前状态": current_status,
                "总收益率": total_return,
                "最大回撤": float(drawdown.min()),
                "期末权益": last_value,
                "已实现盈亏": realized_pnl,
                "当前持仓市值": current_position_value,
                "当前持仓占比": current_position_pct,
                "交易动作": len(symbol_trades),
                "买入": sum(1 for trade in symbol_trades if trade["action"] == "买入"),
                "加仓": sum(1 for trade in symbol_trades if trade["action"] == "加仓"),
                "减仓": sum(1 for trade in symbol_trades if trade["action"] == "减仓"),
                "清仓": sum(1 for trade in symbol_trades if trade["action"] == "清仓"),
                "最后动作": str(latest_trade["action"]) if latest_trade else "无交易",
            }
        )
    return pd.DataFrame(rows)


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
        if manual_position and float(manual_position.get("shares", 0.0)) > 0:
            current_position_source = "手动持仓"
            current_position_shares = float(manual_position.get("shares", 0.0))
            current_position_cost = float(manual_position.get("avg_cost", 0.0))
            current_position_value = current_position_shares * close
        elif latest_trade and latest_trade["action"] != "清仓" and symbol in equity_df.columns:
            last_symbol_equity = float(equity_df[symbol].dropna().iloc[-1])
            current_position_value = max(0.0, last_symbol_equity - float(latest_trade["cash_after"]))
            current_position_shares = max(0.0, float(latest_trade.get("position_shares_after", 0.0)))
            current_position_cost = max(0.0, float(latest_trade.get("avg_cost_after", 0.0)))
        current_position_pct = current_position_value / config.initial_capital if config.initial_capital else 0.0
        unrealized_pnl = (
            current_position_value - current_position_shares * current_position_cost
            if current_position_shares > 0 and current_position_cost > 0
            else 0.0
        )
        status = "持仓" if current_position_pct > 0 else "空仓"

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
                next_action = f"处于过热区：关注是否减仓或等待冷却"
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
    return pd.DataFrame(rows)


def build_strategy_plan(watchlist_df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    if watchlist_df.empty:
        return pd.DataFrame()

    rows = []
    symbol_capital = config.initial_capital / len(config.default_backtest_symbols) if config.default_backtest_symbols else 0.0
    for _, row in watchlist_df.iterrows():
        status = str(row["状态"])
        signals = str(row["当前信号"])
        close = float(row["收盘价"])
        position_value = float(row.get("当前持仓市值", 0.0))
        distance_to_key = float(row["距关键价位"])
        priority_rank = 5
        priority = "观察等待"
        plan_action = "等待"
        reference_amount = None
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
                amount_note = "当前清仓参考"
                note = "趋势防线失效，优先保护本金和已有利润。"
            elif "减仓" in signals:
                priority_rank = 2
                priority = "降低风险"
                plan_action = "减仓"
                reference_amount = position_value * config.reduce_position_pct
                amount_note = "当前减仓参考"
                risk_control = "短线过热区"
                note = f"按当前规则先减掉约 {format_pct(config.reduce_position_pct)} 持仓，等待冷却。"
            elif "加仓" in signals:
                priority_rank = 3
                priority = "顺势加仓"
                plan_action = "加仓"
                reference_amount = symbol_capital * config.add_position_pct
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
                amount_note = "当前建仓参考"
                note = f"突破和量能条件满足，按首次建仓比例 {format_pct(config.entry_position_pct)} 执行。"
            else:
                priority_rank = 5 if distance_to_key < -0.03 else 4
                priority = "观察等待" if priority_rank == 5 else "接近触发"
                plan_action = "等待触发"
                reference_amount = symbol_capital * config.entry_position_pct
                amount_note = "触发后建仓参考"
                note = "未满足完整入场条件，先放入观察队列。"

        rows.append(
            {
                "优先级排序": priority_rank,
                "标的": row["标的"],
                "状态": status,
                "计划动作": plan_action,
                "优先级": priority,
                "参考交易金额": reference_amount,
                "金额说明": amount_note,
                "收盘价": close,
                "距关键价位": distance_to_key,
                "触发依据": trigger,
                "风控关注": risk_control,
                "计划说明": note,
            }
        )

    plan_df = pd.DataFrame(rows)
    return plan_df.sort_values(["优先级排序", "距关键价位"], ascending=[True, False]).reset_index(drop=True)


def parse_symbols(text: str) -> list[str]:
    parts = re.split(r"[\s,，;；]+", text.upper().strip())
    return [part for part in dict.fromkeys(parts) if part]


def is_default_strategy_params(current_payload: dict, default_payload: dict) -> bool:
    return all(current_payload.get(key) == default_payload.get(key) for key in STRATEGY_PARAM_KEYS)


st.set_page_config(page_title="趋势策略工作台", layout="wide")
st.title("AI 趋势交易策略工作台")
st.caption("V1 默认策略：GPT_Trend_Default_v1。当前版本先用演示行情验证回测流程，真实富途行情会作为下一步数据层接入。")

default_payload = load_default_config()
if "backtest_history" not in st.session_state:
    st.session_state["backtest_history"] = load_backtest_history()

with st.sidebar:
    st.header("策略参数")
    if st.button("恢复 GPT 默认参数", use_container_width=True):
        st.session_state["config_payload"] = default_payload.copy()

    payload = st.session_state.get("config_payload", default_payload.copy())
    manual_symbols = parse_symbols(
        st.text_area(
            "手动输入额外股票代码",
            placeholder="例如：US.TSLA, US.META\nAVGO",
            help="支持逗号、空格或换行分隔。当前 demo 模式会自动生成这些标的的演示行情；后续接入富途后会改为拉取真实行情。",
        )
    )
    manual_symbols = normalize_app_symbols(manual_symbols)
    symbol_pool = normalize_app_symbols([*payload["default_pool"], *manual_symbols])
    default_selected_symbols = normalize_app_symbols([*payload["default_backtest_symbols"], *manual_symbols])
    selected_symbols = st.multiselect(
        "参与回测标的",
        options=symbol_pool,
        default=[symbol for symbol in default_selected_symbols if symbol in symbol_pool],
    )
    use_manual_positions = False
    current_positions = {}
    with st.expander("当前持仓（手动）", expanded=False):
        st.caption("可以手动录入，也可以从富途 OpenD 只读导入。导入持仓不会下单，也不会解锁交易。")
        if "positions_import_message" in st.session_state:
            st.success(st.session_state.pop("positions_import_message"))

        import_col1, import_col2 = st.columns(2)
        position_futu_host = import_col1.text_input("持仓 OpenD 地址", value="127.0.0.1", key="position_futu_host")
        position_futu_port = int(
            import_col2.number_input(
                "持仓 OpenD 端口",
                min_value=1,
                max_value=65535,
                value=11111,
                key="position_futu_port",
            )
        )
        import_col3, import_col4 = st.columns(2)
        position_market_label = import_col3.selectbox(
            "持仓市场",
            options=["美股 US", "港股 HK", "A股 CN", "新加坡 SG"],
            key="position_market_label",
        )
        position_env_label = import_col4.selectbox(
            "交易环境",
            options=["模拟账户", "真实账户（只读）"],
            key="position_env_label",
        )
        position_acc_id_text = st.text_input("账户 ID（可选）", placeholder="不填则使用 OpenD 默认账户")
        if st.button("从富途读取持仓", use_container_width=True):
            position_market = {
                "美股 US": "US",
                "港股 HK": "HK",
                "A股 CN": "CN",
                "新加坡 SG": "SG",
            }[position_market_label]
            position_env = "REAL" if position_env_label == "真实账户（只读）" else "SIMULATE"
            try:
                acc_id = int(position_acc_id_text.strip()) if position_acc_id_text.strip() else None
                position_provider = FutuHistoricalDataProvider(
                    FutuDataConfig(host=position_futu_host, port=position_futu_port, cache_dir=ROOT / "data" / "cache")
                )
                futu_positions_df = position_provider.get_positions(
                    market=position_market,
                    trd_env=position_env,
                    acc_id=acc_id,
                )
                if futu_positions_df.empty:
                    st.warning("富途返回的当前持仓为空。")
                else:
                    save_current_positions(futu_positions_df)
                    st.session_state["positions_import_message"] = f"已从富途读取并保存 {len(futu_positions_df)} 条持仓。"
                    st.rerun()
            except ValueError:
                st.error("账户 ID 必须是数字；不确定时可以留空。")
            except Exception as exc:
                st.error(f"富途持仓读取失败：{exc}")

        use_manual_positions = st.checkbox("用当前持仓表生成观察清单和策略计划", value=False)
        saved_positions_df = load_current_positions()
        position_editor_df = build_position_editor_frame(selected_symbols, saved_positions_df)
        edited_positions_df = st.data_editor(
            position_editor_df,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "标的": st.column_config.TextColumn("标的", help="例如 US.AMD、US.NVDA；裸代码会自动补 US."),
                "持仓股数": st.column_config.NumberColumn("持仓股数", min_value=0.0, step=1.0, format="%.4f"),
                "成本价": st.column_config.NumberColumn("成本价", min_value=0.0, step=0.01, format="%.2f"),
            },
            key="current_positions_editor",
        )
        position_col1, position_col2 = st.columns(2)
        if position_col1.button("保存持仓", use_container_width=True):
            save_current_positions(edited_positions_df)
            st.success("已保存当前持仓。")
        if position_col2.button("清空持仓", use_container_width=True):
            save_current_positions(pd.DataFrame(columns=POSITION_COLUMNS))
            st.rerun()
        if use_manual_positions:
            current_positions = build_current_positions_map(edited_positions_df)
            st.caption(f"已启用手动持仓：{len(current_positions)} 个标的。")
    default_period_label = next(
        (label for label, years in BACKTEST_PERIOD_OPTIONS.items() if years == float(payload.get("backtest_years", 2.0))),
        "2 年",
    )
    period_label = st.selectbox(
        "回测周期",
        options=list(BACKTEST_PERIOD_OPTIONS.keys()),
        index=list(BACKTEST_PERIOD_OPTIONS.keys()).index(default_period_label),
    )
    backtest_years = BACKTEST_PERIOD_OPTIONS[period_label]
    initial_capital = st.number_input(
        "模拟初始资金 ($)",
        min_value=1000.0,
        max_value=100000000.0,
        value=float(payload.get("initial_capital", 100000.0)),
        step=1000.0,
    )
    data_source = st.radio("数据源", options=["演示数据", "富途真实行情"], horizontal=True)
    futu_host = "127.0.0.1"
    futu_port = 11111
    futu_provider = None
    refresh_futu_cache = False
    if data_source == "富途真实行情":
        futu_host = st.text_input("OpenD 地址", value="127.0.0.1")
        futu_port = int(st.number_input("OpenD 端口", min_value=1, max_value=65535, value=11111))
        refresh_futu_cache = st.checkbox(
            "本次运行强制刷新行情缓存",
            value=False,
            help="勾选后，下一次运行回测会跳过本地 CSV 缓存，重新从富途 OpenD 拉取历史 K 线。",
        )
        futu_provider = FutuHistoricalDataProvider(
            FutuDataConfig(host=futu_host, port=futu_port, cache_dir=ROOT / "data" / "cache")
        )
        if st.button("测试 OpenD 连接", use_container_width=True):
            ok, message = futu_provider.test_connection()
            if ok:
                st.success(message)
            else:
                st.error(message)
        with st.expander("行情缓存状态", expanded=False):
            cache_symbols = list(dict.fromkeys([*selected_symbols, payload.get("sector_symbol", "SOXX")]))
            cache_rows = [futu_provider.get_cache_info(symbol) for symbol in cache_symbols]
            st.dataframe(pd.DataFrame(cache_rows), use_container_width=True, hide_index=True)
    ma_short = st.number_input("MA 短周期", min_value=5, max_value=100, value=int(payload["ma_short"]))
    ma_long = st.number_input("MA 长周期", min_value=10, max_value=250, value=int(payload["ma_long"]))
    breakout_days = st.number_input("突破新高回溯天数", min_value=5, max_value=120, value=int(payload["breakout_days"]))
    volume_multiplier = st.number_input("成交量倍数", min_value=0.5, max_value=5.0, value=float(payload["volume_multiplier"]), step=0.1)
    overheat_pct = st.number_input("过热距离 MA 短线 (%)", min_value=1.0, max_value=50.0, value=float(payload["overheat_distance"] * 100), step=1.0)
    entry_position_pct = st.number_input(
        "首次建仓比例 (%)",
        min_value=5.0,
        max_value=100.0,
        value=float(payload.get("entry_position_pct", 0.5) * 100),
        step=5.0,
    )
    add_position_pct = st.number_input(
        "单次加仓比例 (%)",
        min_value=5.0,
        max_value=100.0,
        value=float(payload.get("add_position_pct", 0.25) * 100),
        step=5.0,
    )
    reduce_position_pct = st.number_input(
        "单次减仓比例 (%)",
        min_value=5.0,
        max_value=100.0,
        value=float(payload.get("reduce_position_pct", 0.5) * 100),
        step=5.0,
    )
    min_trade_amount = st.number_input(
        "最小成交金额 ($)",
        min_value=0.0,
        max_value=10000.0,
        value=float(payload.get("min_trade_amount", 100.0)),
        step=50.0,
    )
    use_sector_filter = st.checkbox("启用 SOXX 板块共振过滤", value=bool(payload["use_sector_filter"]))

    current_payload = {
        **payload,
        "default_pool": symbol_pool,
        "default_backtest_symbols": selected_symbols,
        "backtest_years": backtest_years,
        "initial_capital": float(initial_capital),
        "ma_short": int(ma_short),
        "ma_long": int(ma_long),
        "breakout_days": int(breakout_days),
        "volume_multiplier": float(volume_multiplier),
        "overheat_distance": float(overheat_pct) / 100,
        "entry_position_pct": float(entry_position_pct) / 100,
        "add_position_pct": float(add_position_pct) / 100,
        "reduce_position_pct": float(reduce_position_pct) / 100,
        "min_trade_amount": float(min_trade_amount),
        "use_sector_filter": bool(use_sector_filter),
    }
    is_default = is_default_strategy_params(current_payload, default_payload)
    if is_default:
        st.info("策略规则使用 GPT 默认参数")
    else:
        st.warning("策略规则已调整，不再是 GPT 默认参数")

    with st.expander("策略参数预设", expanded=False):
        presets = load_strategy_presets()
        if presets:
            selected_preset_name = st.selectbox("选择预设", options=sorted(presets.keys()))
            preset_col1, preset_col2 = st.columns(2)
            if preset_col1.button("加载预设", use_container_width=True):
                st.session_state["config_payload"] = presets[selected_preset_name].copy()
                st.rerun()
            if preset_col2.button("删除预设", use_container_width=True):
                presets.pop(selected_preset_name, None)
                save_strategy_presets(presets)
                st.rerun()
        else:
            st.caption("还没有保存过参数预设。")

        preset_name = st.text_input("保存当前参数为", placeholder="例如：半导体趋势默认")
        if st.button("保存当前预设", use_container_width=True):
            normalized_name = preset_name.strip()
            if not normalized_name:
                st.warning("请先填写预设名称。")
            else:
                presets[normalized_name] = current_payload.copy()
                save_strategy_presets(presets)
                st.success(f"已保存预设：{normalized_name}")

run_default = st.button("运行默认回测", type="primary")
run_current = st.button("运行当前参数回测")
run_requested = run_default or run_current

if run_default:
    config = build_config(
        {
            **default_payload,
            "default_pool": symbol_pool,
            "default_backtest_symbols": selected_symbols,
            "backtest_years": backtest_years,
            "initial_capital": float(initial_capital),
        }
    )
elif run_current:
    config = build_config(current_payload)
elif "last_backtest" in st.session_state:
    saved_backtest = st.session_state["last_backtest"]
    config = saved_backtest["config"]
    market_data = saved_backtest["market_data"]
    result = saved_backtest["result"]
    data_source = saved_backtest["data_source"]
else:
    st.subheader("准备就绪")
    st.write("点击“运行默认回测”即可使用内置默认参数启动第一版回测。")
    st.stop()

if not config.default_backtest_symbols:
    st.warning("请至少选择一个参与回测标的。")
    st.stop()

if run_requested:
    if data_source == "富途真实行情":
        with st.spinner("正在从富途 OpenD 拉取/读取缓存历史行情..."):
            provider = futu_provider or FutuHistoricalDataProvider(
                FutuDataConfig(host=futu_host, port=futu_port, cache_dir=ROOT / "data" / "cache")
            )
            market_data, data_errors = provider.get_market_data_with_errors(
                config.default_backtest_symbols,
                sector_symbol=config.sector_symbol,
                years=config.backtest_years,
                warmup_days=config.indicator_warmup_days,
                use_cache=not refresh_futu_cache,
            )
            if data_errors:
                st.warning("部分标的行情获取失败，已跳过可选失败标的。")
                st.dataframe(
                    pd.DataFrame([{"标的": symbol, "错误": error} for symbol, error in data_errors.items()]),
                    use_container_width=True,
                    hide_index=True,
                )

            available_symbols = [symbol for symbol in config.default_backtest_symbols if symbol in market_data]
            if config.use_sector_filter and config.sector_symbol not in market_data:
                st.error(f"板块过滤标的 {config.sector_symbol} 行情不可用，无法执行当前策略。")
                st.info("可以先检查 OpenD，或临时关闭 SOXX 板块共振过滤。")
                st.stop()
            if not available_symbols:
                st.error("没有任何参与回测标的成功获取行情。")
                st.info("请确认 OpenD 已启动并监听 127.0.0.1:11111；也可以先切回“演示数据”。")
                st.stop()
            if len(available_symbols) != len(config.default_backtest_symbols):
                config = build_config({**config.to_dict(), "default_backtest_symbols": available_symbols})
    else:
        market_data = make_demo_market_data(
            config.default_backtest_symbols,
            sector_symbol=config.sector_symbol,
            years=config.backtest_years,
            warmup_days=config.indicator_warmup_days,
        )
    result = BacktestService(config).run(market_data)
    st.session_state["last_backtest"] = {
        "config": config,
        "market_data": market_data,
        "result": result,
        "data_source": data_source,
    }

with st.expander("当前策略摘要", expanded=True):
    st.markdown(build_strategy_summary(config, data_source))

st.subheader("回测结果")
st.caption(f"当前回测周期：约 {config.backtest_years:g} 年")
st.caption(f"当前数据源：{data_source}")
equity_df = pd.DataFrame(result.symbol_equity_curve)
if run_requested:
    run_mode = "默认参数" if run_default else "当前参数"
    history = st.session_state.setdefault("backtest_history", load_backtest_history())
    history.append(build_backtest_history_row(config, data_source, result, equity_df, run_mode))
    st.session_state["backtest_history"] = history[-BACKTEST_HISTORY_LIMIT:]
    save_backtest_history(st.session_state["backtest_history"])
if not equity_df.empty:
    st.caption(
        f"实际回测区间：{pd.Timestamp(equity_df['date'].min()).date()} 至 {pd.Timestamp(equity_df['date'].max()).date()}"
    )
col1, col2, col3, col4, col5, col6 = st.columns(6)
closed_trade_count = int(result.metrics.get("closed_trade_count", 0))
col1.metric("总收益率", format_pct(float(result.metrics["total_return"])))
col2.metric("最大回撤", format_pct(float(result.metrics["max_drawdown"])))
col3.metric("Sharpe", f"{float(result.metrics['sharpe']):.2f}")
col4.metric("已实现胜率", "N/A" if closed_trade_count == 0 else format_pct(float(result.metrics["win_rate"])))
col5.metric("已实现 PF", format_profit_factor(result.metrics["profit_factor"], closed_trade_count))
col6.metric("交易动作", f"{result.metrics['trade_count']} / 已实现 {closed_trade_count}")
if closed_trade_count == 0 and int(result.metrics["trade_count"]) > 0:
    st.caption("当前收益主要来自未平仓持仓的浮盈/浮亏；已实现胜率和 PF 需要出现减仓或清仓后才有统计意义。")

st.subheader("回测运行历史")
st.caption(f"运行历史会保存到本地 {BACKTEST_HISTORY_PATH.relative_to(ROOT)}，最多保留最近 {BACKTEST_HISTORY_LIMIT} 条。")
history_rows = st.session_state.get("backtest_history", [])
if not history_rows:
    st.info("当前会话还没有历史记录。每次点击运行回测后，这里会追加一条参数和结果快照。")
else:
    history_df = pd.DataFrame(history_rows).copy()
    history_df.insert(0, "运行序号", range(1, len(history_df) + 1))
    best_return_row = history_df.loc[history_df["总收益率"].astype(float).idxmax()]
    best_drawdown_row = history_df.loc[history_df["最大回撤"].astype(float).idxmax()]
    best_sharpe_row = history_df.loc[history_df["Sharpe"].astype(float).idxmax()]
    best_col1, best_col2, best_col3 = st.columns(3)
    best_col1.metric(
        "最高收益版本",
        f"#{int(best_return_row['运行序号'])}",
        format_pct(float(best_return_row["总收益率"])),
    )
    best_col2.metric(
        "最小回撤版本",
        f"#{int(best_drawdown_row['运行序号'])}",
        format_pct(float(best_drawdown_row["最大回撤"])),
    )
    best_col3.metric(
        "最高 Sharpe 版本",
        f"#{int(best_sharpe_row['运行序号'])}",
        f"{float(best_sharpe_row['Sharpe']):.2f}",
    )
    st.caption(
        f"优先复盘建议：#{int(best_sharpe_row['运行序号'])}，"
        f"Sharpe {float(best_sharpe_row['Sharpe']):.2f}，"
        f"收益 {format_pct(float(best_sharpe_row['总收益率']))}，"
        f"回撤 {format_pct(float(best_sharpe_row['最大回撤']))}。"
    )
    chart_col1, chart_col2 = st.columns(2)
    risk_return_df = history_df[["运行序号", "总收益率", "最大回撤", "Sharpe"]].copy()
    risk_return_df["回撤幅度"] = risk_return_df["最大回撤"].astype(float).abs()
    risk_return_df["运行标签"] = risk_return_df["运行序号"].map(lambda value: f"#{int(value)}")
    x_min = float(risk_return_df["回撤幅度"].min())
    x_max = float(risk_return_df["回撤幅度"].max())
    x_padding = max((x_max - x_min) * 0.15, 0.005)
    return_drawdown_fig = go.Figure()
    return_drawdown_fig.add_trace(
        go.Scatter(
            x=risk_return_df["回撤幅度"],
            y=risk_return_df["总收益率"],
            mode="markers+text",
            text=risk_return_df["运行标签"],
            textposition="top center",
            marker=dict(
                size=15,
                color=risk_return_df["Sharpe"].astype(float),
                colorscale="Tealrose",
                showscale=True,
                colorbar=dict(title="Sharpe", thickness=10),
                line=dict(width=1.5, color="rgba(255,255,255,0.95)"),
            ),
            customdata=risk_return_df[["运行序号", "最大回撤", "Sharpe"]],
            hovertemplate=(
                "运行 #%{customdata[0]}<br>"
                "总收益率：%{y:.2%}<br>"
                "最大回撤：%{customdata[1]:.2%}<br>"
                "Sharpe：%{customdata[2]:.2f}<extra></extra>"
            ),
        )
    )
    return_drawdown_fig.update_layout(
        title="风险收益分布",
        height=320,
        margin=dict(l=10, r=10, t=50, b=56),
        template="plotly_white",
        xaxis_title="最大回撤幅度",
        yaxis_title="总收益率",
        font=dict(color="#303647"),
        plot_bgcolor="rgba(248,250,252,0.75)",
    )
    return_drawdown_fig.update_xaxes(
        tickformat=".1%",
        nticks=5,
        range=[max(0, x_min - x_padding), x_max + x_padding],
        gridcolor="#E6EBF2",
        zeroline=False,
        automargin=True,
        title_standoff=12,
    )
    return_drawdown_fig.update_yaxes(
        tickformat=".0%",
        gridcolor="#E6EBF2",
        zerolinecolor="#AAB4C4",
        automargin=True,
        title_standoff=10,
    )
    chart_col1.plotly_chart(return_drawdown_fig, use_container_width=True)

    sharpe_fig = px.line(history_df, x="运行序号", y="Sharpe", markers=True, title="Sharpe 对比")
    sharpe_fig.update_layout(height=300, margin=dict(l=10, r=10, t=50, b=10))
    chart_col2.plotly_chart(sharpe_fig, use_container_width=True)

    display_history_df = history_df.sort_values("运行序号", ascending=False).copy()
    display_history_df["本金"] = display_history_df["本金"].map(lambda value: f"${value:,.0f}")
    for column in ["总收益率", "最大回撤", "已实现胜率", "过热距离", "首次建仓", "单次加仓", "单次减仓"]:
        display_history_df[column] = display_history_df[column].map(
            lambda value: "N/A" if pd.isna(value) else f"{float(value) * 100:.2f}%"
        )
    display_history_df["已实现PF"] = display_history_df["已实现PF"].map(
        lambda value: "N/A" if pd.isna(value) else "∞" if value == float("inf") else f"{float(value):.2f}"
    )
    display_history_df["最小成交额"] = display_history_df["最小成交额"].map(lambda value: f"${value:,.0f}")
    st.dataframe(display_history_df, use_container_width=True, hide_index=True)
    action_col1, action_col2 = st.columns(2)
    action_col1.download_button(
        "下载运行历史 CSV",
        data=dataframe_to_csv_bytes(history_df),
        file_name="backtest_run_history.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if action_col2.button("清空运行历史", use_container_width=True):
        st.session_state["backtest_history"] = []
        clear_backtest_history()
        st.rerun()

if not equity_df.empty:
    line_columns = [column for column in equity_df.columns if column != "date"]
    normalized_df = equity_df.copy()
    for column in line_columns:
        first_value = float(normalized_df[column].iloc[0])
        if first_value:
            normalized_df[column] = normalized_df[column] / first_value - 1
    fig = px.line(normalized_df, x="date", y=line_columns, title="权益曲线（组合 + 单标的）")
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("标的表现概览")
    symbol_summary_df = build_symbol_performance_summary(
        equity_df,
        result.trades,
        config.default_backtest_symbols,
        config.initial_capital,
    )
    if symbol_summary_df.empty:
        st.info("当前回测没有可展示的单标的表现。")
    else:
        display_symbol_summary_df = symbol_summary_df.copy()
        display_symbol_summary_df["总收益率"] = display_symbol_summary_df["总收益率"].map(lambda value: f"{value * 100:.2f}%")
        display_symbol_summary_df["最大回撤"] = display_symbol_summary_df["最大回撤"].map(lambda value: f"{value * 100:.2f}%")
        display_symbol_summary_df["期末权益"] = display_symbol_summary_df["期末权益"].map(lambda value: f"${value:,.2f}")
        display_symbol_summary_df["已实现盈亏"] = display_symbol_summary_df["已实现盈亏"].map(lambda value: f"${value:,.2f}")
        display_symbol_summary_df["当前持仓市值"] = display_symbol_summary_df["当前持仓市值"].map(lambda value: f"${value:,.2f}")
        display_symbol_summary_df["当前持仓占比"] = display_symbol_summary_df["当前持仓占比"].map(lambda value: f"{value * 100:.1f}%")
        st.dataframe(display_symbol_summary_df, use_container_width=True, hide_index=True)
        st.download_button(
            "下载标的表现概览 CSV",
            data=dataframe_to_csv_bytes(symbol_summary_df),
            file_name="symbol_performance_summary.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.subheader("当前策略观察清单")
    watchlist_df = build_strategy_watchlist(config, market_data, result.trades, equity_df, current_positions)
    if watchlist_df.empty:
        st.info("当前回测没有可展示的观察清单。")
    else:
        if current_positions:
            st.caption("已启用手动当前持仓：观察清单和策略计划会优先按手动持仓判断持仓/空仓状态。")
        display_watchlist_df = watchlist_df.copy()
        price_columns = [
            "收盘价",
            f"MA{config.ma_short}",
            f"MA{config.ma_long}",
            f"{config.breakout_days}日前高",
            "过热价",
        ]
        for column in price_columns:
            display_watchlist_df[column] = display_watchlist_df[column].map(lambda value: f"{value:.2f}")
        display_watchlist_df["当前持仓股数"] = display_watchlist_df["当前持仓股数"].map(lambda value: f"{value:,.4f}")
        display_watchlist_df["成本价"] = display_watchlist_df["成本价"].map(lambda value: "" if value == 0 else f"{value:.2f}")
        display_watchlist_df["当前持仓市值"] = display_watchlist_df["当前持仓市值"].map(lambda value: f"${value:,.2f}")
        display_watchlist_df["持仓浮盈亏"] = display_watchlist_df["持仓浮盈亏"].map(lambda value: f"${value:,.2f}")
        display_watchlist_df["当前持仓占比"] = display_watchlist_df["当前持仓占比"].map(lambda value: f"{value * 100:.1f}%")
        display_watchlist_df["距关键价位"] = display_watchlist_df["距关键价位"].map(lambda value: f"{value * 100:+.2f}%")
        st.dataframe(display_watchlist_df, use_container_width=True, hide_index=True)
        st.download_button(
            "下载当前策略观察清单 CSV",
            data=dataframe_to_csv_bytes(watchlist_df),
            file_name="strategy_watchlist.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.subheader("策略计划明细")
        strategy_plan_df = build_strategy_plan(watchlist_df, config)
        if strategy_plan_df.empty:
            st.info("当前没有可生成的策略计划。")
        else:
            action_counts = strategy_plan_df["计划动作"].value_counts()
            plan_col1, plan_col2, plan_col3, plan_col4 = st.columns(4)
            plan_col1.metric("待处理标的", len(strategy_plan_df))
            plan_col2.metric("建仓/加仓", int(action_counts.get("建仓", 0) + action_counts.get("加仓", 0)))
            plan_col3.metric("减仓/清仓", int(action_counts.get("减仓", 0) + action_counts.get("清仓", 0)))
            plan_col4.metric("继续观察", int(action_counts.get("等待触发", 0) + action_counts.get("等待", 0)))
            st.caption("优先级按处理紧迫度排序：立即处理、降低风险、准备入场、顺势加仓、持仓跟踪、接近触发、观察等待。")
            st.caption("参考交易金额：已触发动作显示当前执行参考；等待触发显示触发后的建仓参考；继续持仓则显示暂不交易。")

            display_strategy_plan_df = strategy_plan_df.drop(columns=["优先级排序"]).copy()
            display_strategy_plan_df["参考交易金额"] = display_strategy_plan_df["参考交易金额"].map(
                lambda value: "暂不交易" if pd.isna(value) else f"${float(value):,.2f}"
            )
            display_strategy_plan_df["收盘价"] = display_strategy_plan_df["收盘价"].map(lambda value: f"{value:.2f}")
            display_strategy_plan_df["距关键价位"] = display_strategy_plan_df["距关键价位"].map(
                lambda value: f"{value * 100:+.2f}%"
            )
            st.dataframe(display_strategy_plan_df, use_container_width=True, hide_index=True)
            st.download_button(
                "下载策略计划明细 CSV",
                data=dataframe_to_csv_bytes(strategy_plan_df.drop(columns=["优先级排序"])),
                file_name="strategy_action_plan.csv",
                mime="text/csv",
                use_container_width=True,
            )

st.subheader("单标的价格与仓位")
chart_symbol = st.selectbox("查看标的", options=config.default_backtest_symbols)
if chart_symbol not in market_data:
    st.warning(f"{chart_symbol} 没有可用行情数据。")
else:
    strategy = TrendFollowingStrategy(config)
    chart_df = strategy.prepare_with_signals(market_data[chart_symbol], market_data.get(config.sector_symbol))
    if not equity_df.empty:
        chart_start = pd.Timestamp(equity_df["date"].min())
        chart_df = chart_df[pd.to_datetime(chart_df["date"]) >= chart_start]

    symbol_trades = [trade for trade in result.trades if trade["symbol"] == chart_symbol]
    signal_col1, signal_col2, signal_col3, signal_col4 = st.columns(4)
    signal_col1.metric("入场信号", int(chart_df["entry_signal"].sum()))
    signal_col2.metric("加仓信号", int(chart_df["add_signal"].sum()))
    signal_col3.metric("减仓信号", int(chart_df["reduce_signal"].sum()))
    signal_col4.metric("清仓信号", int(chart_df["exit_signal"].sum()))

    price_fig = go.Figure()
    price_fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["close"],
            mode="lines",
            name="收盘价",
            line=dict(color="#2563eb", width=2),
        )
    )
    price_fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["ma_short"],
            mode="lines",
            name=f"MA{config.ma_short}",
            line=dict(color="#16a34a", width=1.5),
        )
    )
    price_fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["ma_long"],
            mode="lines",
            name=f"MA{config.ma_long}",
            line=dict(color="#f97316", width=1.5),
        )
    )

    if symbol_trades:
        buy_df = pd.DataFrame(
            [
                {"date": trade["date"], "price": trade["price"], "reason": trade["reason"], "action": trade["action"]}
                for trade in symbol_trades
                if trade["action"] in {"买入", "加仓"}
            ]
        )
        sell_df = pd.DataFrame(
            [
                {"date": trade["date"], "price": trade["price"], "reason": trade["reason"], "action": trade["action"]}
                for trade in symbol_trades
                if trade["action"] in {"减仓", "清仓", "期末平仓"}
            ]
        )
        if not buy_df.empty:
            price_fig.add_trace(
                go.Scatter(
                    x=buy_df["date"],
                    y=buy_df["price"],
                    mode="markers",
                    name="买入/加仓",
                    marker=dict(color="#16a34a", size=11, symbol="triangle-up"),
                    customdata=buy_df[["action", "reason"]],
                    hovertemplate="%{customdata[0]}价 %{y:.2f}<br>%{customdata[1]}<extra></extra>",
                )
            )
        if not sell_df.empty:
            price_fig.add_trace(
                go.Scatter(
                    x=sell_df["date"],
                    y=sell_df["price"],
                    mode="markers",
                    name="减仓/清仓",
                    marker=dict(color="#dc2626", size=11, symbol="triangle-down"),
                    customdata=sell_df[["action", "reason"]],
                    hovertemplate="%{customdata[0]}价 %{y:.2f}<br>%{customdata[1]}<extra></extra>",
                )
            )
    else:
        st.info(f"{chart_symbol} 在当前回测区间内没有产生交易动作。")

    price_fig.update_layout(
        title=f"{chart_symbol} 价格走势与买卖点",
        height=480,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(price_fig, use_container_width=True)

    if symbol_trades and not chart_df.empty:
        sorted_symbol_trades = sorted(symbol_trades, key=lambda trade: pd.Timestamp(trade["date"]))
        position_rows = [
            {
                "date": pd.Timestamp(chart_df["date"].min()),
                "position_pct": 0.0,
                "action": "起始",
                "amount": 0.0,
                "reason": "回测区间开始，未持仓",
            }
        ]
        position_rows.extend(
            [
                {
                    "date": pd.Timestamp(trade["date"]),
                    "position_pct": float(trade["position_pct_after"]),
                    "action": str(trade["action"]),
                    "amount": float(trade["amount"]),
                    "reason": str(trade["reason"]),
                }
                for trade in sorted_symbol_trades
            ]
        )
        last_chart_date = pd.Timestamp(chart_df["date"].max())
        if pd.Timestamp(position_rows[-1]["date"]) < last_chart_date:
            last_symbol_equity = float(equity_df[chart_symbol].dropna().iloc[-1]) if chart_symbol in equity_df.columns else 0.0
            latest_trade = sorted_symbol_trades[-1]
            current_position_value = 0.0
            if latest_trade["action"] != "清仓":
                current_position_value = max(0.0, last_symbol_equity - float(latest_trade["cash_after"]))
            position_rows.append(
                {
                    "date": last_chart_date,
                    "position_pct": current_position_value / config.initial_capital if config.initial_capital else 0.0,
                    "action": "区间结束",
                    "amount": 0.0,
                    "reason": "延续最后一次交易后的持仓状态",
                }
            )

        position_df = pd.DataFrame(position_rows)
        position_col1, position_col2, position_col3, position_col4 = st.columns(4)
        position_col1.metric("买入次数", sum(1 for trade in symbol_trades if trade["action"] == "买入"))
        position_col2.metric("加仓次数", sum(1 for trade in symbol_trades if trade["action"] == "加仓"))
        position_col3.metric("减仓次数", sum(1 for trade in symbol_trades if trade["action"] == "减仓"))
        position_col4.metric("最大持仓占比", f"{position_df['position_pct'].max() * 100:.1f}%")

        position_fig = go.Figure()
        position_fig.add_trace(
            go.Scatter(
                x=position_df["date"],
                y=position_df["position_pct"],
                mode="lines+markers",
                name="交易后持仓占比",
                line=dict(color="#7c3aed", width=2, shape="hv"),
                marker=dict(size=8),
                customdata=position_df[["action", "amount", "reason"]],
                hovertemplate="%{customdata[0]}后持仓 %{y:.1%}<br>成交金额 $%{customdata[1]:,.2f}<br>%{customdata[2]}<extra></extra>",
            )
        )
        position_fig.update_yaxes(tickformat=".0%")
        position_fig.update_layout(
            title=f"{chart_symbol} 仓位变化",
            height=300,
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(position_fig, use_container_width=True)

st.subheader("交易流水")
trades_df = pd.DataFrame(result.trades)
if trades_df.empty:
    st.warning("当前参数没有产生交易。")
else:
    filter_col1, filter_col2 = st.columns(2)
    selected_trade_symbols = filter_col1.multiselect(
        "筛选标的",
        options=sorted(trades_df["symbol"].unique()),
        default=sorted(trades_df["symbol"].unique()),
    )
    selected_trade_actions = filter_col2.multiselect(
        "筛选动作",
        options=sorted(trades_df["action"].unique()),
        default=sorted(trades_df["action"].unique()),
    )
    filtered_trades_df = trades_df[
        trades_df["symbol"].isin(selected_trade_symbols) & trades_df["action"].isin(selected_trade_actions)
    ].copy()
    if filtered_trades_df.empty:
        st.info("当前筛选条件下没有交易流水。")
    else:
        display_trades_df = filtered_trades_df.copy()
        display_trades_df["return_pct"] = display_trades_df["return_pct"].map(lambda value: "" if pd.isna(value) else f"{value * 100:.2f}%")
        display_trades_df["realized_pnl"] = display_trades_df["realized_pnl"].map(lambda value: "" if pd.isna(value) else f"${value:,.2f}")
        display_trades_df["shares"] = display_trades_df["shares"].map(lambda value: f"{value:.2f}")
        display_trades_df["amount"] = display_trades_df["amount"].map(lambda value: f"${value:,.2f}")
        display_trades_df["amount_pct"] = display_trades_df["amount_pct"].map(lambda value: f"{value * 100:.1f}%")
        display_trades_df["position_shares_after"] = display_trades_df["position_shares_after"].map(lambda value: f"{value:.2f}")
        display_trades_df["position_value_after"] = display_trades_df["position_value_after"].map(lambda value: f"${value:,.2f}")
        display_trades_df["position_pct_after"] = display_trades_df["position_pct_after"].map(lambda value: f"{value * 100:.1f}%")
        display_trades_df["cash_after"] = display_trades_df["cash_after"].map(lambda value: f"${value:,.2f}")
        display_trades_df = display_trades_df.rename(
        columns={
            "symbol": "标的",
            "date": "日期",
            "action": "动作",
            "price": "成交价",
            "shares": "成交股数",
            "amount": "成交金额",
            "amount_pct": "成交资金占比",
            "position_shares_after": "持仓股数",
            "position_value_after": "持仓市值",
            "position_pct_after": "组合持仓占比",
            "cash_after": "标的现金余额",
            "return_pct": "实现收益率",
            "realized_pnl": "实现盈亏",
            "reason": "交易理由",
        }
    )
        display_columns = [
            "标的",
            "日期",
            "动作",
            "成交价",
            "成交股数",
            "成交金额",
            "成交资金占比",
            "持仓股数",
            "持仓市值",
            "组合持仓占比",
            "标的现金余额",
            "实现收益率",
            "实现盈亏",
            "交易理由",
        ]
        display_trades_df = display_trades_df[display_columns]
        st.dataframe(display_trades_df, use_container_width=True, hide_index=True)
        st.download_button(
            "下载筛选后的交易流水 CSV",
            data=dataframe_to_csv_bytes(filtered_trades_df),
            file_name="filtered_trade_ledger.csv",
            mime="text/csv",
            use_container_width=True,
        )