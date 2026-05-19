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

from trend_option_backtest.cockpit import (
    build_cockpit_overview,
    build_cockpit_risk_budget,
    build_cockpit_sections,
    build_cockpit_snapshot_row,
    build_regression_check_rows,
    build_regression_check_summary,
    build_review_trend,
    build_weekly_review_summary,
)
from trend_option_backtest.demo_data import make_demo_market_data
from trend_option_backtest.exporting import build_strategy_plan_export_frame
from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.planning import (
    POSITION_COLUMNS,
    build_current_positions_map,
    build_option_combo_summary,
    build_option_overlay_summary,
    build_position_editor_frame,
    build_strategy_plan,
    build_strategy_watchlist,
    filter_unmatched_option_legs,
    get_option_position_symbols,
    get_position_symbols,
    normalize_app_symbol,
    normalize_app_symbols,
)
from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider
from trend_option_backtest.services.backtest_service import BacktestService
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy


DEFAULT_CONFIG_PATH = ROOT / "config" / "default_config.json"
BACKTEST_HISTORY_PATH = ROOT / "data" / "backtest_run_history.csv"
STRATEGY_PRESETS_PATH = ROOT / "data" / "strategy_presets.json"
CURRENT_POSITIONS_PATH = ROOT / "data" / "current_positions.csv"
COCKPIT_SNAPSHOT_PATH = ROOT / "data" / "cockpit_snapshots.csv"
COCKPIT_REVIEW_PATH = ROOT / "data" / "cockpit_reviews.csv"
COCKPIT_REGRESSION_PATH = ROOT / "data" / "cockpit_regression_checks.csv"
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "dev"

BACKTEST_HISTORY_LIMIT = 200
COCKPIT_SNAPSHOT_LIMIT = 200
COCKPIT_REVIEW_LIMIT = 200
COCKPIT_REGRESSION_LIMIT = 500
BACKTEST_PERIOD_OPTIONS = {"1 个月": 1 / 12, "3 个月": 0.25, "6 个月": 0.5, "1 年": 1.0, "2 年": 2.0, "3 年": 3.0, "5 年": 5.0}
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
REGRESSION_CHECK_ITEMS = [
    "OpenD 连接正常",
    "持仓读取正常",
    "账户资金读取正常",
    "股票和期权隔离正确",
    "期权组合识别合理",
    "默认回测可完成",
    "策略计划动作合理",
    "Cockpit 风险预算方向正确",
    "任务状态和备注可保存",
    "今日复盘和周度摘要可更新",
]
ACTION_PLAN_DISPLAY_COLUMNS = [
    "市场",
    "标的",
    "状态",
    "计划动作",
    "优先级",
    "建议股数",
    "参考交易金额",
    "金额说明",
    "收盘价",
    "触发依据",
    "计划说明",
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


def format_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${float(value):,.2f}"


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def select_existing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame[[column for column in columns if column in frame.columns]].copy()


def get_portfolio_equity_column(equity_df: pd.DataFrame) -> str | None:
    for column in ("组合", "portfolio", "equity"):
        if column in equity_df.columns:
            return column
    return None


def parse_symbols(text: str) -> list[str]:
    parts = re.split(r"[\s,，;；]+", text.upper().strip())
    return [part for part in dict.fromkeys(parts) if part]


def is_default_strategy_params(current_payload: dict, default_payload: dict) -> bool:
    return all(current_payload.get(key) == default_payload.get(key) for key in STRATEGY_PARAM_KEYS)


def add_symbols_to_payload(payload: dict, symbols: list[str], *, participate: bool) -> dict:
    normalized_symbols = normalize_app_symbols(symbols)
    updated_payload = payload.copy()
    updated_payload["default_pool"] = normalize_app_symbols([*payload.get("default_pool", []), *normalized_symbols])
    if participate:
        updated_payload["default_backtest_symbols"] = normalize_app_symbols([*payload.get("default_backtest_symbols", []), *normalized_symbols])
    return updated_payload


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
    normalized = normalized[(normalized["标的"] != "") & (normalized["持仓股数"].abs() > 1e-12)]
    if not normalized.empty:
        normalized["持仓成本"] = normalized["持仓股数"].abs() * normalized["成本价"]
        normalized = normalized.groupby("标的", as_index=False).agg({"持仓股数": "sum", "持仓成本": "sum"})
        normalized = normalized[normalized["持仓股数"].abs() > 1e-12]
        normalized["成本价"] = normalized["持仓成本"] / normalized["持仓股数"].abs()
        normalized = normalized[POSITION_COLUMNS]
    normalized.to_csv(CURRENT_POSITIONS_PATH, index=False, encoding="utf-8-sig")


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


def load_limited_csv(path: Path, limit: int) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    return frame.tail(limit).reset_index(drop=True)


def append_limited_csv(path: Path, rows: pd.DataFrame, limit: int) -> pd.DataFrame:
    existing = load_limited_csv(path, limit)
    updated = pd.concat([existing, rows], ignore_index=True).tail(limit)
    path.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(path, index=False, encoding="utf-8-sig")
    return updated.reset_index(drop=True)


def load_cockpit_snapshots() -> pd.DataFrame:
    return load_limited_csv(COCKPIT_SNAPSHOT_PATH, COCKPIT_SNAPSHOT_LIMIT)


def append_cockpit_snapshot(row: dict[str, object]) -> pd.DataFrame:
    return append_limited_csv(COCKPIT_SNAPSHOT_PATH, pd.DataFrame([row]), COCKPIT_SNAPSHOT_LIMIT)


def load_cockpit_reviews() -> pd.DataFrame:
    return load_limited_csv(COCKPIT_REVIEW_PATH, COCKPIT_REVIEW_LIMIT)


def append_cockpit_review(row: dict[str, object]) -> pd.DataFrame:
    return append_limited_csv(COCKPIT_REVIEW_PATH, pd.DataFrame([row]), COCKPIT_REVIEW_LIMIT)


def load_cockpit_regressions() -> pd.DataFrame:
    return load_limited_csv(COCKPIT_REGRESSION_PATH, COCKPIT_REGRESSION_LIMIT)


def append_cockpit_regression(rows: pd.DataFrame) -> pd.DataFrame:
    return append_limited_csv(COCKPIT_REGRESSION_PATH, rows, COCKPIT_REGRESSION_LIMIT)


def build_backtest_history_row(config: StrategyConfig, data_source: str, result, equity_df: pd.DataFrame, run_mode: str) -> dict:
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
    }


def build_strategy_summary(config: StrategyConfig, data_source: str) -> str:
    symbols = "、".join(config.default_backtest_symbols)
    sector_filter = f"启用 {config.sector_symbol} 板块共振过滤。" if config.use_sector_filter else "不启用板块共振过滤。"
    return f"""
**策略定位**：趋势跟随 + 突破确认 + 分批仓位管理。

**当前回测对象**：{symbols}。数据源为 {data_source}，回测周期约 {config.backtest_years:g} 年，模拟初始资金为 {format_money(config.initial_capital)}。

**核心逻辑**：站上 MA{config.ma_short}、MA{config.ma_short} 高于 MA{config.ma_long}、突破过去 {config.breakout_days} 日前高，并结合成交量确认。{sector_filter}

**风控逻辑**：跌破 MA{config.ma_long} 清仓，距离 MA{config.ma_short} 超过 {format_pct(config.overheat_distance)} 视为过热并减仓。
"""


def build_symbol_performance_summary(equity_df: pd.DataFrame, trades: list[dict], symbols: list[str], initial_capital: float) -> pd.DataFrame:
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
        drawdown = values / values.cummax() - 1
        symbol_trades = [trade for trade in trades if trade["symbol"] == symbol]
        rows.append(
            {
                "标的": symbol,
                "总收益率": last_value / first_value - 1 if first_value else 0.0,
                "最大回撤": float(drawdown.min()),
                "交易动作": len(symbol_trades),
                "最后动作": str(symbol_trades[-1]["action"]) if symbol_trades else "无交易",
                "期末权益": last_value,
                "期末资金占比": last_value / initial_capital if initial_capital else 0.0,
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(page_title="趋势策略工作台", layout="wide")
st.title("AI 趋势交易策略工作台")
st.caption("本地只读策略工具。富途真实账户默认只读取持仓、资金和行情，不解锁交易，不自动下单。")

default_payload = load_default_config()
if "backtest_history" not in st.session_state:
    st.session_state["backtest_history"] = load_backtest_history()

with st.sidebar:
    st.header("策略参数")
    if st.button("恢复 GPT 默认参数", use_container_width=True):
        st.session_state["config_payload"] = default_payload.copy()
        st.session_state["selected_backtest_symbols"] = []

    payload = st.session_state.get("config_payload", default_payload.copy())
    manual_symbols = normalize_app_symbols(parse_symbols(st.text_area("手动输入额外股票代码", placeholder="例如：US.TSLA, US.META\nAVGO")))
    symbol_pool = normalize_app_symbols([*payload["default_pool"], *manual_symbols])
    pending_selected_symbols = st.session_state.pop("pending_selected_backtest_symbols", None)
    if pending_selected_symbols is not None:
        st.session_state["selected_backtest_symbols"] = [symbol for symbol in normalize_app_symbols(pending_selected_symbols) if symbol in symbol_pool]
    elif "selected_backtest_symbols" not in st.session_state:
        st.session_state["selected_backtest_symbols"] = []
    else:
        st.session_state["selected_backtest_symbols"] = [symbol for symbol in normalize_app_symbols(st.session_state["selected_backtest_symbols"]) if symbol in symbol_pool]
    selected_symbols = st.multiselect("参与回测标的", options=symbol_pool, key="selected_backtest_symbols")

    use_manual_positions = False
    current_positions = {}
    account_plan_capital = None
    account_info = st.session_state.get("account_info")
    with st.expander("当前持仓（手动 / 富途只读）", expanded=False):
        if "positions_import_message" in st.session_state:
            st.success(st.session_state.pop("positions_import_message"))
        if "account_import_message" in st.session_state:
            st.success(st.session_state.pop("account_import_message"))
        import_col1, import_col2 = st.columns(2)
        position_futu_host = import_col1.text_input("持仓 OpenD 地址", value="127.0.0.1", key="position_futu_host")
        position_futu_port = int(import_col2.number_input("持仓 OpenD 端口", min_value=1, max_value=65535, value=11111, key="position_futu_port"))
        import_col3, import_col4 = st.columns(2)
        position_market_label = import_col3.selectbox("持仓市场", options=["美股 US", "港股 HK", "A股 CN", "新加坡 SG"], key="position_market_label")
        position_env_label = import_col4.selectbox("交易环境", options=["模拟账户", "真实账户（只读）"], index=1, key="position_env_label")
        position_acc_id_text = st.text_input("账户 ID（可选）", placeholder="不填则使用 OpenD 默认账户")
        position_market = {"美股 US": "US", "港股 HK": "HK", "A股 CN": "CN", "新加坡 SG": "SG"}[position_market_label]
        position_env = "REAL" if position_env_label == "真实账户（只读）" else "SIMULATE"

        if st.button("从富途读取持仓", use_container_width=True):
            try:
                acc_id = int(position_acc_id_text.strip()) if position_acc_id_text.strip() else None
                provider = FutuHistoricalDataProvider(FutuDataConfig(host=position_futu_host, port=position_futu_port, cache_dir=ROOT / "data" / "cache"))
                futu_positions_df = provider.get_positions(market=position_market, trd_env=position_env, acc_id=acc_id)
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

        if st.button("读取账户资金", use_container_width=True):
            try:
                acc_id = int(position_acc_id_text.strip()) if position_acc_id_text.strip() else None
                provider = FutuHistoricalDataProvider(FutuDataConfig(host=position_futu_host, port=position_futu_port, cache_dir=ROOT / "data" / "cache"))
                st.session_state["account_info"] = provider.get_account_info(market=position_market, trd_env=position_env, acc_id=acc_id)
                st.session_state["account_import_message"] = "已读取富途账户资金。"
                st.rerun()
            except ValueError:
                st.error("账户 ID 必须是数字；不确定时可以留空。")
            except Exception as exc:
                st.error(f"富途资金读取失败：{exc}")

        account_info = st.session_state.get("account_info")
        if account_info:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"项目": "总资产", "金额": format_money(account_info.get("total_assets"))},
                        {"项目": "现金", "金额": format_money(account_info.get("cash"))},
                        {"项目": "购买力", "金额": format_money(account_info.get("buying_power"))},
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            if st.checkbox("用账户资金估算策略计划", value=True):
                account_plan_capital = float(account_info.get("plan_capital") or 0.0)

        use_manual_positions = st.checkbox("用当前持仓表生成观察清单和策略计划", value=False)
        edited_positions_df = st.data_editor(
            build_position_editor_frame(selected_symbols, load_current_positions()),
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            disabled=["市场", "类型", "正股标的"],
            key="current_positions_editor",
        )
        position_symbols = get_position_symbols(edited_positions_df)
        option_position_symbols = get_option_position_symbols(edited_positions_df)
        if option_position_symbols:
            st.caption(f"识别到 {len(option_position_symbols)} 个期权持仓：{', '.join(option_position_symbols)}。")
        missing_position_symbols = [symbol for symbol in position_symbols if symbol not in selected_symbols]
        if missing_position_symbols:
            st.warning(f"持仓中有 {len(missing_position_symbols)} 个标的尚未参与当前回测：{', '.join(missing_position_symbols)}")
            add_pool_col1, add_pool_col2 = st.columns(2)
            if add_pool_col1.button("加入股票池并参与回测", use_container_width=True):
                updated_payload = add_symbols_to_payload(payload, missing_position_symbols, participate=True)
                updated_selected_symbols = normalize_app_symbols([*selected_symbols, *missing_position_symbols])
                updated_payload["default_backtest_symbols"] = updated_selected_symbols
                st.session_state["pending_selected_backtest_symbols"] = updated_selected_symbols
                st.session_state["config_payload"] = updated_payload
                st.rerun()
            if add_pool_col2.button("仅加入股票池", use_container_width=True):
                st.session_state["config_payload"] = add_symbols_to_payload(payload, missing_position_symbols, participate=False)
                st.rerun()
        elif position_symbols:
            st.caption("当前持仓标的已在本次回测选择范围内。")
        save_col1, save_col2 = st.columns(2)
        if save_col1.button("保存持仓", use_container_width=True):
            save_current_positions(edited_positions_df)
            st.success("已保存当前持仓。")
        if save_col2.button("清空持仓", use_container_width=True):
            save_current_positions(pd.DataFrame(columns=POSITION_COLUMNS))
            st.rerun()
        if use_manual_positions:
            current_positions = build_current_positions_map(edited_positions_df)

    default_period_label = next((label for label, years in BACKTEST_PERIOD_OPTIONS.items() if years == float(payload.get("backtest_years", 0.5))), "6 个月")
    period_label = st.selectbox("回测周期", options=list(BACKTEST_PERIOD_OPTIONS.keys()), index=list(BACKTEST_PERIOD_OPTIONS.keys()).index(default_period_label))
    backtest_years = BACKTEST_PERIOD_OPTIONS[period_label]
    initial_capital = st.number_input("模拟初始资金 ($)", min_value=1000.0, max_value=100000000.0, value=float(payload.get("initial_capital", 100000.0)), step=1000.0)
    data_source = st.radio("数据源", options=["演示数据", "富途真实行情"], index=1, horizontal=True)
    futu_host = "127.0.0.1"
    futu_port = 11111
    futu_provider = None
    refresh_futu_cache = False
    if data_source == "富途真实行情":
        futu_host = st.text_input("OpenD 地址", value="127.0.0.1")
        futu_port = int(st.number_input("OpenD 端口", min_value=1, max_value=65535, value=11111))
        refresh_futu_cache = st.checkbox("本次运行强制刷新行情缓存", value=False)
        futu_provider = FutuHistoricalDataProvider(FutuDataConfig(host=futu_host, port=futu_port, cache_dir=ROOT / "data" / "cache"))
        if st.button("测试 OpenD 连接", use_container_width=True):
            ok, message = futu_provider.test_connection()
            if ok:
                st.success(message)
            else:
                st.error(message)

    ma_short = st.number_input("MA 短周期", min_value=5, max_value=100, value=int(payload["ma_short"]))
    ma_long = st.number_input("MA 长周期", min_value=10, max_value=250, value=int(payload["ma_long"]))
    breakout_days = st.number_input("突破新高回溯天数", min_value=5, max_value=120, value=int(payload["breakout_days"]))
    volume_multiplier = st.number_input("成交量倍数", min_value=0.5, max_value=5.0, value=float(payload["volume_multiplier"]), step=0.1)
    overheat_pct = st.number_input("过热距离 MA 短线 (%)", min_value=1.0, max_value=50.0, value=float(payload["overheat_distance"] * 100), step=1.0)
    entry_position_pct = st.number_input("首次建仓比例 (%)", min_value=5.0, max_value=100.0, value=float(payload.get("entry_position_pct", 0.5) * 100), step=5.0)
    add_position_pct = st.number_input("单次加仓比例 (%)", min_value=5.0, max_value=100.0, value=float(payload.get("add_position_pct", 0.25) * 100), step=5.0)
    reduce_position_pct = st.number_input("单次减仓比例 (%)", min_value=5.0, max_value=100.0, value=float(payload.get("reduce_position_pct", 0.5) * 100), step=5.0)
    min_trade_amount = st.number_input("最小成交金额 ($)", min_value=0.0, max_value=10000.0, value=float(payload.get("min_trade_amount", 100.0)), step=50.0)
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
    if is_default_strategy_params(current_payload, default_payload):
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
                st.session_state["pending_selected_backtest_symbols"] = presets[selected_preset_name].get("default_backtest_symbols", [])
                st.rerun()
            if preset_col2.button("删除预设", use_container_width=True):
                presets.pop(selected_preset_name, None)
                save_strategy_presets(presets)
                st.rerun()
        else:
            st.caption("还没有保存过参数预设。")
        preset_name = st.text_input("保存当前参数为", placeholder="例如：半导体趋势默认")
        if st.button("保存当前预设", use_container_width=True):
            if preset_name.strip():
                presets[preset_name.strip()] = current_payload.copy()
                save_strategy_presets(presets)
                st.success(f"已保存预设：{preset_name.strip()}")
            else:
                st.warning("请先填写预设名称。")

run_default = st.button("运行默认回测", type="primary")
run_current = st.button("运行当前参数回测")
run_requested = run_default or run_current

if run_default:
    config = build_config({**default_payload, "default_pool": symbol_pool, "default_backtest_symbols": selected_symbols, "backtest_years": backtest_years, "initial_capital": float(initial_capital)})
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
    st.write("请选择参与回测标的，然后运行回测。")
    st.stop()

if not config.default_backtest_symbols:
    st.warning("请至少选择一个参与回测标的。")
    st.stop()

if run_requested:
    if data_source == "富途真实行情":
        with st.spinner("正在从富途 OpenD 拉取/读取缓存历史行情..."):
            provider = futu_provider or FutuHistoricalDataProvider(FutuDataConfig(host=futu_host, port=futu_port, cache_dir=ROOT / "data" / "cache"))
            market_data, data_errors = provider.get_market_data_with_errors(
                config.default_backtest_symbols,
                sector_symbol=config.sector_symbol,
                years=config.backtest_years,
                warmup_days=config.indicator_warmup_days,
                use_cache=not refresh_futu_cache,
            )
            if data_errors:
                st.warning("部分标的行情获取失败，已跳过可选失败标的。")
                st.dataframe(pd.DataFrame([{"标的": symbol, "错误": error} for symbol, error in data_errors.items()]), use_container_width=True, hide_index=True)
            available_symbols = [symbol for symbol in config.default_backtest_symbols if symbol in market_data]
            if config.use_sector_filter and config.sector_symbol not in market_data:
                st.error(f"板块过滤标的 {config.sector_symbol} 行情不可用，无法执行当前策略。")
                st.stop()
            if not available_symbols:
                st.error("没有任何参与回测标的成功获取行情。")
                st.stop()
            if len(available_symbols) != len(config.default_backtest_symbols):
                config = build_config({**config.to_dict(), "default_backtest_symbols": available_symbols})
    else:
        market_data = make_demo_market_data(config.default_backtest_symbols, sector_symbol=config.sector_symbol, years=config.backtest_years, warmup_days=config.indicator_warmup_days)
    result = BacktestService(config).run(market_data)
    st.session_state["last_backtest"] = {"config": config, "market_data": market_data, "result": result, "data_source": data_source}

with st.expander("当前策略摘要", expanded=True):
    st.markdown(build_strategy_summary(config, data_source))

st.subheader("回测结果")
st.caption(f"当前回测周期：约 {config.backtest_years:g} 年")
st.caption(f"当前数据源：{data_source}")
equity_df = pd.DataFrame(result.symbol_equity_curve)
if run_requested:
    history = st.session_state.setdefault("backtest_history", load_backtest_history())
    history.append(build_backtest_history_row(config, data_source, result, equity_df, "默认参数" if run_default else "当前参数"))
    st.session_state["backtest_history"] = history[-BACKTEST_HISTORY_LIMIT:]
    save_backtest_history(st.session_state["backtest_history"])

closed_trade_count = int(result.metrics.get("closed_trade_count", 0))
metric_cols = st.columns(6)
metric_cols[0].metric("总收益率", format_pct(float(result.metrics["total_return"])))
metric_cols[1].metric("最大回撤", format_pct(float(result.metrics["max_drawdown"])))
metric_cols[2].metric("Sharpe", f"{float(result.metrics['sharpe']):.2f}")
metric_cols[3].metric("已实现胜率", "N/A" if closed_trade_count == 0 else format_pct(float(result.metrics["win_rate"])))
metric_cols[4].metric("已实现 PF", format_profit_factor(result.metrics["profit_factor"], closed_trade_count))
metric_cols[5].metric("交易动作", f"{result.metrics['trade_count']} / 已实现 {closed_trade_count}")

portfolio_equity_column = get_portfolio_equity_column(equity_df)
if not equity_df.empty and portfolio_equity_column is not None:
    equity_fig = px.line(equity_df, x="date", y=[portfolio_equity_column], title="组合权益曲线")
    equity_fig.update_layout(height=320, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(equity_fig, use_container_width=True)
elif not equity_df.empty:
    st.warning("权益曲线缺少组合权益列，已跳过组合权益图。")

watchlist_df = pd.DataFrame()
strategy_plan_df = pd.DataFrame()
option_overlay_df = pd.DataFrame()
option_combo_df = pd.DataFrame()
capital_source = "富途账户资金" if account_plan_capital else "模拟初始资金"
capital_value = account_plan_capital if account_plan_capital else config.initial_capital
if not equity_df.empty:
    watchlist_df = build_strategy_watchlist(config, market_data, result.trades, equity_df, current_positions)
    if not watchlist_df.empty:
        strategy_plan_df = build_strategy_plan(watchlist_df, config, account_plan_capital)
        option_overlay_df = build_option_overlay_summary(edited_positions_df, strategy_plan_df)
        option_combo_df = build_option_combo_summary(option_overlay_df)

st.subheader("策略 Cockpit")
if strategy_plan_df.empty:
    st.info("运行回测并生成观察清单后，这里会汇总当前动作、风险队列、接近触发和期权关注。")
else:
    cockpit_metrics, cockpit_tasks_df = build_cockpit_overview(strategy_plan_df, option_overlay_df)
    cockpit_sections = build_cockpit_sections(strategy_plan_df, option_overlay_df)
    cockpit_risk_budget = build_cockpit_risk_budget(strategy_plan_df, option_overlay_df, capital_value=float(capital_value))
    metric_cols = st.columns(4)
    for column, name in zip(metric_cols, ["当前动作", "降低风险", "接近触发", "期权关注"]):
        column.metric(name, cockpit_metrics[name])
    st.caption(f"计划资金基准：{capital_source} {format_money(capital_value)}。Cockpit 只做开盘前观察汇总，不自动下单。")
    st.markdown("#### 风险预算")
    budget_cols = st.columns(5)
    budget_cols[0].metric("增风险金额", format_money(cockpit_risk_budget["增风险金额"]))
    budget_cols[1].metric("降风险金额", format_money(cockpit_risk_budget["降风险金额"]))
    budget_cols[2].metric("净风险变化", format_money(cockpit_risk_budget["净风险变化"]))
    budget_cols[3].metric("动作资金占比", format_pct(cockpit_risk_budget["今日动作资金占比"]))
    budget_cols[4].metric("潜在接股金额", format_money(cockpit_risk_budget["潜在接股金额"]))

    edited_cockpit_tasks_df = pd.DataFrame(columns=["状态", "备注", *cockpit_tasks_df.columns.tolist()])
    if cockpit_tasks_df.empty:
        st.success("当前没有已触发动作、临近触发或需要优先复核的期权持仓。")
    else:
        editable_tasks_df = cockpit_tasks_df.copy()
        editable_tasks_df.insert(0, "状态", "未处理")
        editable_tasks_df.insert(1, "备注", "")
        edited_cockpit_tasks_df = st.data_editor(
            editable_tasks_df,
            use_container_width=True,
            hide_index=True,
            column_config={"状态": st.column_config.SelectboxColumn("状态", options=["未处理", "已处理", "跳过", "等待"]), "备注": st.column_config.TextColumn("备注")},
            key="cockpit_task_status_editor",
        )

    focus_symbols = sorted({symbol for symbol in strategy_plan_df.get("标的", pd.Series(dtype=str)).dropna().map(str).tolist() if symbol in config.default_backtest_symbols})
    if focus_symbols:
        focused_symbol = st.selectbox("Cockpit 聚焦标的", options=focus_symbols, key="cockpit_focus_symbol")
        focus_plan_df = strategy_plan_df[strategy_plan_df["标的"] == focused_symbol].copy()
        focus_combo_df = option_combo_df[option_combo_df["正股标的"] == focused_symbol].copy() if not option_combo_df.empty else pd.DataFrame()
        with st.expander(f"{focused_symbol} 聚焦摘要", expanded=True):
            if not focus_plan_df.empty:
                row = focus_plan_df.iloc[0]
                focus_cols = st.columns(4)
                focus_cols[0].metric("计划动作", str(row.get("计划动作", "")))
                focus_cols[1].metric("优先级", str(row.get("优先级", "")))
                focus_cols[2].metric("距关键价位", f"{float(row.get('距关键价位', 0.0)) * 100:+.2f}%")
                focus_cols[3].metric("参考金额", "暂不交易" if pd.isna(row.get("参考交易金额")) else format_money(row.get("参考交易金额")))
                st.caption(str(row.get("触发依据", "")))
                st.caption(str(row.get("计划说明", "")))
            if not focus_combo_df.empty:
                st.dataframe(focus_combo_df[["到期日", "组合类型", "组合方向", "期权腿数", "行权价区间", "组合说明", "风险提示"]], use_container_width=True, hide_index=True)

    risk_tab, option_tab, capital_tab, observe_tab = st.tabs(["风险持仓", "期权到期", "资金动作", "今日只观察"])
    with risk_tab:
        frame = cockpit_sections["risk_positions"]
        if frame.empty:
            st.info("当前没有触发清仓/减仓，或贴近关键风控线的持仓。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)
    with option_tab:
        frame = cockpit_sections["option_expiry"]
        if frame.empty:
            st.info("未来 30 天内没有需要特别提醒的期权到期。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)
    with capital_tab:
        frame = cockpit_sections["capital_actions"].copy()
        if frame.empty:
            st.info("当前没有已触发动作对应的参考交易金额。")
        else:
            frame["参考金额合计"] = frame["参考金额合计"].map(lambda value: f"${float(value):,.2f}")
            st.dataframe(frame, use_container_width=True, hide_index=True)
    with observe_tab:
        frame = cockpit_sections["observe_only"]
        if frame.empty:
            st.info("当前没有可归入只观察队列的标的。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)

    snapshot_row = build_cockpit_snapshot_row(cockpit_metrics, cockpit_tasks_df, cockpit_sections, data_source=data_source, capital_source=capital_source, capital_value=float(capital_value), symbols=config.default_backtest_symbols, app_version=APP_VERSION)
    snapshot_col1, snapshot_col2 = st.columns(2)
    if snapshot_col1.button("保存 Cockpit 快照", use_container_width=True):
        snapshots_df = append_cockpit_snapshot(snapshot_row)
        st.success(f"已保存 Cockpit 快照，共 {len(snapshots_df)} 条。")
    snapshots_df = load_cockpit_snapshots()
    if not snapshots_df.empty:
        snapshot_col2.download_button("下载 Cockpit 快照 CSV", data=dataframe_to_csv_bytes(snapshots_df), file_name="cockpit_snapshots.csv", mime="text/csv", use_container_width=True)

    with st.expander("今日复盘", expanded=False):
        review_date = st.date_input("复盘日期", value=pd.Timestamp.today().date(), key="cockpit_review_date")
        review_summary = st.text_area("今日总结", key="cockpit_review_summary")
        review_done = st.text_area("已处理事项", key="cockpit_review_done")
        review_follow_up = st.text_area("待跟进事项", key="cockpit_review_follow_up")
        status_counts = edited_cockpit_tasks_df["状态"].value_counts() if "状态" in edited_cockpit_tasks_df.columns else pd.Series(dtype=int)
        review_col1, review_col2 = st.columns(2)
        if review_col1.button("保存今日复盘", use_container_width=True):
            review_row = {
                "复盘时间": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "复盘日期": str(review_date),
                "应用版本": APP_VERSION,
                "数据源": data_source,
                "任务数": int(len(edited_cockpit_tasks_df)),
                "已处理": int(status_counts.get("已处理", 0)),
                "跳过": int(status_counts.get("跳过", 0)),
                "等待": int(status_counts.get("等待", 0)),
                "未处理": int(status_counts.get("未处理", 0)),
                "当前动作": int(cockpit_metrics["当前动作"]),
                "降低风险": int(cockpit_metrics["降低风险"]),
                "接近触发": int(cockpit_metrics["接近触发"]),
                "期权关注": int(cockpit_metrics["期权关注"]),
                "净风险变化": float(cockpit_risk_budget["净风险变化"]),
                "今日总结": review_summary,
                "已处理事项": review_done,
                "待跟进事项": review_follow_up,
            }
            reviews_df = append_cockpit_review(review_row)
            st.success(f"已保存今日复盘，共 {len(reviews_df)} 条。")
        reviews_df = load_cockpit_reviews()
        if not reviews_df.empty:
            review_col2.download_button("下载 Cockpit 复盘 CSV", data=dataframe_to_csv_bytes(reviews_df), file_name="cockpit_reviews.csv", mime="text/csv", use_container_width=True)
            trend_df = build_review_trend(reviews_df)
            if not trend_df.empty:
                st.dataframe(trend_df, use_container_width=True, hide_index=True)
            weekly_summary_df = build_weekly_review_summary(reviews_df)
            if not weekly_summary_df.empty:
                st.dataframe(weekly_summary_df.tail(8).sort_values("周开始", ascending=False), use_container_width=True, hide_index=True)

    with st.expander("真实账户检查清单", expanded=False):
        st.caption("用真实账户只读数据跑完页面后，在这里逐项记录是否正常。这里不会自动下单，也不会自动判断交易建议。")
        regression_date = st.date_input("检查日期", value=pd.Timestamp.today().date(), key="cockpit_regression_date")
        regression_default_df = pd.DataFrame({"检查项": REGRESSION_CHECK_ITEMS, "结果": ["未检查"] * len(REGRESSION_CHECK_ITEMS), "备注": [""] * len(REGRESSION_CHECK_ITEMS)})
        edited_regression_df = st.data_editor(
            regression_default_df,
            use_container_width=True,
            hide_index=True,
            column_config={"检查项": st.column_config.TextColumn("检查项"), "结果": st.column_config.SelectboxColumn("结果", options=["未检查", "通过", "需复核", "失败"]), "备注": st.column_config.TextColumn("备注")},
            disabled=["检查项"],
            key="cockpit_regression_check_editor",
        )
        regression_col1, regression_col2 = st.columns(2)
        if regression_col1.button("保存检查清单", use_container_width=True):
            rows = build_regression_check_rows(
                edited_regression_df,
                {
                    "检查日期": str(regression_date),
                    "应用版本": APP_VERSION,
                    "数据源": data_source,
                    "交易环境": position_env_label,
                    "持仓行数": len(edited_positions_df),
                    "期权行数": len(option_position_symbols),
                    "任务数": len(edited_cockpit_tasks_df),
                },
            )
            regression_history_df = append_cockpit_regression(rows)
            st.success(f"已保存检查清单，共 {len(regression_history_df)} 条明细。")
        regression_history_df = load_cockpit_regressions()
        if not regression_history_df.empty:
            regression_col2.download_button("下载真实账户检查 CSV", data=dataframe_to_csv_bytes(regression_history_df), file_name="cockpit_regression_checks.csv", mime="text/csv", use_container_width=True)
            summary = build_regression_check_summary(regression_history_df)
            summary_cols = st.columns(4)
            summary_cols[0].metric("最近检查项", int(summary["检查项"]))
            summary_cols[1].metric("通过", int(summary["通过"]))
            summary_cols[2].metric("需复核/失败", int(summary["需复核"]) + int(summary["失败"]))
            summary_cols[3].metric("通过率", format_pct(float(summary["通过率"])))
            st.dataframe(regression_history_df.tail(30).sort_values("检查时间", ascending=False), use_container_width=True, hide_index=True)

st.subheader("今日行动计划")
if strategy_plan_df.empty:
    st.info("运行回测后会生成今日行动计划。")
else:
    action_plan_display_df = select_existing_columns(strategy_plan_df.drop(columns=["优先级排序"], errors="ignore"), ACTION_PLAN_DISPLAY_COLUMNS)
    st.dataframe(action_plan_display_df, use_container_width=True, hide_index=True)
    export_df = build_strategy_plan_export_frame(strategy_plan_df, config=config, data_source=data_source, equity_df=equity_df, capital_source=capital_source, capital_value=float(capital_value), position_source="当前持仓表" if current_positions else "回测模拟", app_version=APP_VERSION, account_info=account_info)
    st.download_button("下载今日行动计划 CSV", data=dataframe_to_csv_bytes(export_df), file_name="strategy_action_plan.csv", mime="text/csv", use_container_width=True)

if not watchlist_df.empty:
    with st.expander("策略观察清单", expanded=False):
        st.dataframe(watchlist_df, use_container_width=True, hide_index=True)

if not watchlist_df.empty:
    if not option_overlay_df.empty:
        st.subheader("期权持仓关联")
        unmatched_option_legs_df = filter_unmatched_option_legs(option_overlay_df, option_combo_df)
        if not option_combo_df.empty:
            st.markdown("#### 期权组合识别")
            st.dataframe(option_combo_df, use_container_width=True, hide_index=True)
            st.download_button("下载期权组合识别 CSV", data=dataframe_to_csv_bytes(option_combo_df), file_name="option_combo_summary.csv", mime="text/csv", use_container_width=True)
        else:
            st.info("当前没有识别出常见期权组合；可继续查看下方单腿关联明细。")
        st.markdown("#### 未归入组合的单腿关联")
        if unmatched_option_legs_df.empty:
            st.info("当前期权腿已全部归入上方组合识别，单腿区不重复展示。")
        else:
            st.dataframe(unmatched_option_legs_df, use_container_width=True, hide_index=True)
        st.download_button("下载全部期权单腿明细 CSV", data=dataframe_to_csv_bytes(option_overlay_df), file_name="option_overlay_summary.csv", mime="text/csv", use_container_width=True)

st.subheader("单标的价格与仓位")
chart_options = config.default_backtest_symbols
focused_symbol = st.session_state.get("cockpit_focus_symbol")
if focused_symbol in chart_options:
    st.session_state["chart_symbol_select"] = focused_symbol
chart_symbol = st.selectbox("查看标的", options=chart_options, key="chart_symbol_select")
if chart_symbol not in market_data:
    st.warning(f"{chart_symbol} 没有可用行情数据。")
else:
    strategy = TrendFollowingStrategy(config)
    chart_df = strategy.prepare_with_signals(market_data[chart_symbol], market_data.get(config.sector_symbol))
    if not equity_df.empty:
        chart_start = pd.Timestamp(equity_df["date"].min())
        chart_df = chart_df[pd.to_datetime(chart_df["date"]) >= chart_start]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["close"], mode="lines", name="收盘价"))
    if "ma_short" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["ma_short"], mode="lines", name=f"MA{config.ma_short}"))
    if "ma_long" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["ma_long"], mode="lines", name=f"MA{config.ma_long}"))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.subheader("回测运行历史")
history_rows = st.session_state.get("backtest_history", [])
if not history_rows:
    st.info("当前会话还没有历史记录。")
else:
    st.dataframe(pd.DataFrame(history_rows).tail(20).sort_values("运行时间", ascending=False), use_container_width=True, hide_index=True)