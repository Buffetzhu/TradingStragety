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
    build_cockpit_risk_budget_detail,
    build_cockpit_risk_budget,
    build_cockpit_sections,
    build_cockpit_snapshot_row,
    build_regression_check_frame,
    build_regression_check_rows,
    build_regression_check_summary,
    build_review_trend,
    build_weekly_review_summary,
)
from trend_option_backtest.demo_data import make_demo_market_data
from trend_option_backtest.exporting import build_strategy_plan_export_frame
from trend_option_backtest.history import build_template_history_summary, filter_history_by_templates, normalize_backtest_history_frame
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
from trend_option_backtest.strategy_templates import STRATEGY_TEMPLATES, TEMPLATE_LABEL_TO_KEY, apply_strategy_template, build_template_diff_rows, get_template_label
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy
from trend_option_backtest.workspaces import (
    WorkspaceContext,
    render_account_workspace,
    render_simulation_workspace,
)


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
]
ACTION_PLAN_DETAIL_COLUMNS = [
    "市场",
    "标的",
    "收盘价",
    "距关键价位",
    "目标仓位差额",
    "风控关注",
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


def clean_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    for column in display.columns:
        if pd.api.types.is_numeric_dtype(display[column]):
            continue
        display[column] = display[column].fillna("")
    return display


def format_futu_exception(action: str, exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if any(keyword in lowered for keyword in ["connection", "connect", "refused", "timed out", "timeout", "10061"]):
        return f"{action}失败：OpenD 可能未启动或端口不可连接。请确认 OpenD 正在运行，地址和端口通常为 127.0.0.1:11111。原始错误：{message}"
    if any(keyword in message for keyword in ["账户", "acc", "trd_env", "交易环境"]):
        return f"{action}失败：请检查账户 ID、市场和交易环境。账户 ID 不确定时可以留空使用 OpenD 默认账户。原始错误：{message}"
    return f"{action}失败：{message}"


def count_position_rows(frame: pd.DataFrame) -> int:
    if frame.empty or "持仓股数" not in frame.columns:
        return 0
    quantities = pd.to_numeric(frame["持仓股数"], errors="coerce").fillna(0.0)
    return int((quantities.abs() > 1e-12).sum())


def render_daily_workflow_status(
    *,
    selected_symbols: list[str],
    positions_df: pd.DataFrame,
    account_info: dict | None,
    data_source: str,
    position_env_label: str,
    has_last_backtest: bool,
) -> None:
    position_count = count_position_rows(positions_df)
    option_count = len(get_option_position_symbols(positions_df)) if not positions_df.empty else 0
    stock_count = len(get_position_symbols(positions_df)) if not positions_df.empty else 0

    st.subheader("今日流程状态")
    status_cols = st.columns(6)
    status_cols[0].metric("回测标的", len(selected_symbols))
    status_cols[1].metric("持仓记录", position_count, f"正股 {stock_count} / 期权 {option_count}")
    status_cols[2].metric("账户资金", "已读取" if account_info else "未读取")
    status_cols[3].metric("行动计划", "已生成" if has_last_backtest else "未生成")
    status_cols[4].metric("数据源", data_source)
    status_cols[5].metric("账户模式", position_env_label)
    st.caption("安全边界：富途账户只用于读取持仓、资金和行情，不解锁交易，不自动下单。")

    if has_last_backtest:
        st.success("已生成今日行动计划，可继续查看 Cockpit、期权提示和复盘记录。")
    elif not selected_symbols and position_count > 0:
        st.warning("当前有持仓记录，但还没有选择参与回测标的。")
    elif not selected_symbols:
        st.info("请选择参与回测标的，或从富途读取持仓后加入回测。")
    elif data_source == "富途真实行情":
        st.info(f"回测标的已选择，当前为 {position_env_label} + 富途真实行情。确认 OpenD 可连接后运行回测。")
    else:
        st.info("回测标的已选择，可以运行回测。")


def build_position_participation_frame(position_symbols: list[str], symbol_pool: list[str], selected_symbols: list[str]) -> pd.DataFrame:
    rows = []
    pool_set = set(symbol_pool)
    selected_set = set(selected_symbols)
    for symbol in position_symbols:
        if symbol in selected_set:
            status = "已参与本次回测"
        elif symbol in pool_set:
            status = "在股票池，未参与回测"
        else:
            status = "未加入股票池"
        rows.append({"标的": symbol, "参与状态": status})
    return pd.DataFrame(rows)


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
        "策略模板": config.strategy_name,
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

**策略模板**：{config.strategy_name}。

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


st.set_page_config(
    page_title="趋势策略工作台",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "About": "AI 趋势交易策略工作台 · 本地只读，富途真账户仅查不下单。",
    },
)

# ===== 全局视觉打磨 =====
st.markdown(
    """
    <style>
    /* 隐藏 Streamlit 默认页脚 / 部署按钮，让页面更像产品 */
    #MainMenu, footer, [data-testid="stToolbar"] [data-testid="stDeployButton"] {visibility: hidden;}
    footer {display: none;}

    /* 主区收紧上边距 + 控制最大宽度，避免在 4K 屏被拉成大字报 */
    .block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 1400px;}

    /* 顶部品牌条：渐变 + 圆角 + 阴影 */
    .brand-hero {
        background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 60%, #38BDF8 100%);
        color: #FFFFFF;
        padding: 18px 24px;
        border-radius: 14px;
        box-shadow: 0 6px 24px rgba(37, 99, 235, 0.18);
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 12px;
    }
    .brand-hero h1 {
        margin: 0;
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: 0.5px;
    }
    .brand-hero .brand-sub {
        margin-top: 4px;
        font-size: 0.85rem;
        opacity: 0.85;
    }
    .brand-chips {display: flex; gap: 8px; flex-wrap: wrap;}
    .brand-chip {
        background: rgba(255, 255, 255, 0.18);
        color: #FFFFFF;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 500;
        backdrop-filter: blur(4px);
        border: 1px solid rgba(255, 255, 255, 0.25);
    }
    .brand-chip strong {font-weight: 600;}

    /* metric 卡片：柔和边框 + 浅底，凸显数据 */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        transition: box-shadow 0.15s ease, transform 0.15s ease;
    }
    [data-testid="stMetric"]:hover {
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.12);
        transform: translateY(-1px);
    }
    [data-testid="stMetricLabel"] {color: #64748B; font-size: 0.78rem; font-weight: 500;}
    [data-testid="stMetricValue"] {color: #0F172A; font-weight: 700;}

    /* expander 标题字号略大、深色 */
    .streamlit-expanderHeader, [data-testid="stExpander"] summary {
        font-weight: 600 !important;
        color: #1E293B;
    }
    [data-testid="stExpander"] {
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
        background: #FFFFFF;
    }

    /* 行动计划 / 风险卡片：让 container(border=True) 更有质感 */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid #E2E8F0 !important;
        background: #FFFFFF;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
        transition: box-shadow 0.18s ease, border-color 0.18s ease;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #BFDBFE !important;
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.10);
    }

    /* 主按钮（type=primary）：深一档蓝 + hover 抬升 */
    .stButton > button[kind="primary"] {
        background: linear-gradient(180deg, #2563EB 0%, #1D4ED8 100%);
        border: none;
        font-weight: 600;
        box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(180deg, #1D4ED8 0%, #1E40AF 100%);
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
    }
    .stButton > button {border-radius: 10px;}

    /* 侧栏：略深底色 + 更紧凑标题 */
    [data-testid="stSidebar"] {background: #F1F5F9;}
    [data-testid="stSidebar"] h2 {font-size: 1.05rem; color: #0F172A;}
    [data-testid="stSidebar"] [data-testid="stExpander"] {background: #FFFFFF;}

    /* tab 字号略大 */
    .stTabs [data-baseweb="tab"] {font-weight: 600; font-size: 0.92rem;}

    /* 工作模式 radio：横向更紧凑、更像 segmented control */
    div[role="radiogroup"][aria-label="工作模式"] {
        background: #FFFFFF;
        padding: 4px;
        border-radius: 10px;
        border: 1px solid #E2E8F0;
        display: inline-flex;
        gap: 4px;
    }
    div[role="radiogroup"][aria-label="工作模式"] label {
        margin: 0 !important;
        padding: 6px 14px !important;
        border-radius: 8px;
        transition: background 0.15s ease;
    }
    div[role="radiogroup"][aria-label="工作模式"] label:hover {background: #F1F5F9;}

    /* dataframe 角更圆 */
    [data-testid="stDataFrame"] {border-radius: 10px; overflow: hidden;}

    /* 全局主容器限宽居中（避免大屏下控件被无限拉伸） */
    .main .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 1200px !important;
        padding-top: 1.2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        margin: 0 auto !important;
    }

    /* 配置卡片：白底 + 圆角 + 阴影，让控件聚拢成"控制面板"质感 */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0 !important;
        border-radius: 14px !important;
        padding: 1.1rem 1.4rem !important;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.03);
        margin-bottom: 0.6rem;
    }
    [data-testid="stVerticalBlockBorderWrapper"] h4 {
        margin-top: 0 !important;
        margin-bottom: 0.5rem !important;
        color: #0F172A;
        font-size: 1.0rem;
    }
    /* 卡片内输入控件圆角 */
    [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="select"] > div,
    [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="input"] > div,
    [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="base-input"] {
        border-radius: 8px !important;
    }
    /* 卡片内 expander 改为轻量内嵌样式（去掉重复白底卡片感） */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stExpander"] {
        background: #F8FAFC;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px;
        margin-bottom: 6px;
        box-shadow: none;
    }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stExpander"] summary {
        padding: 6px 12px !important;
        font-size: 0.88rem;
    }
    [data-testid="stVerticalBlockBorderWrapper"] label p {
        font-size: 0.82rem !important;
        color: #475569;
    }

    /* 按钮：默认不再拉满，留 padding；primary 按钮稍大 */
    .stButton > button {
        border-radius: 8px;
        padding: 0.45rem 1.2rem;
        font-weight: 500;
    }
    .stButton > button[kind="primary"] {padding: 0.55rem 1.6rem; font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ===== 顶部品牌头 =====
_hero_env_chip = "真账户·只读" if st.session_state.get("position_env_label", "真实账户（只读）") == "真实账户（只读）" else "模拟账户"
_hero_market_chip = st.session_state.get("position_market_label", "美股 US")
st.markdown(
    f"""
    <div class="brand-hero">
        <div>
            <h1>📈 AI 趋势交易策略工作台</h1>
            <div class="brand-sub">本地只读 · 富途真账户默认不解锁、不自动下单</div>
        </div>
        <div class="brand-chips">
            <span class="brand-chip">版本 <strong>{APP_VERSION}</strong></span>
            <span class="brand-chip">市场 <strong>{_hero_market_chip}</strong></span>
            <span class="brand-chip">环境 <strong>{_hero_env_chip}</strong></span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

workspace_mode = st.radio(
    "工作模式",
    options=["模拟研究", "账户追踪"],
    horizontal=True,
    help="模拟研究：纯回测和参数调试，不读取账户。账户追踪：基于富途持仓和资金做今日策略追踪和复盘。",
    key="workspace_mode",
    label_visibility="collapsed",
)
show_account = workspace_mode == "账户追踪"
show_simulation = workspace_mode == "模拟研究"
st.markdown(
    f"<div style='color:#475569;font-size:0.85rem;margin:-4px 0 14px 2px;'>"
    f"当前视图：<strong style='color:#1E293B;'>{workspace_mode}</strong>"
    f" · {'纯回测与参数调试，不读取真实账户。' if show_simulation else '基于富途持仓与资金，生成今日行动计划。'}"
    f"</div>",
    unsafe_allow_html=True,
)

default_payload = load_default_config()
if "backtest_history" not in st.session_state:
    st.session_state["backtest_history"] = load_backtest_history()

# ===== 配置卡片：全宽容器，内部紧凑分栏 =====
_cfg_box = st.container(border=True)
if show_account:
    _acc_box = st.container(border=True)
else:
    _acc_box = None

# 账户相关变量默认值（必须在渲染前初始化，主区始终可用）
use_manual_positions = False
current_positions = {}
account_plan_capital = None
account_info = st.session_state.get("account_info")
edited_positions_df = pd.DataFrame(columns=POSITION_COLUMNS)
option_position_symbols = []
position_env_label = "模拟账户"

with _cfg_box:
    st.markdown("#### 🎯 策略配置")
    payload = st.session_state.get("config_payload", default_payload.copy())
    template_labels = [template.label for template in STRATEGY_TEMPLATES.values()]
    current_template_label = get_template_label(payload)
    default_period_label = next((label for label, years in BACKTEST_PERIOD_OPTIONS.items() if years == float(payload.get("backtest_years", 0.5))), "6 个月")

    # 顶部一行：模板 / 周期 / 资金 / 恢复默认
    top_col1, top_col2, top_col3, top_col4 = st.columns([3, 1.2, 1.4, 1.2])
    with top_col1:
        selected_template_label = st.selectbox(
            "策略模板",
            options=template_labels,
            index=template_labels.index(current_template_label) if current_template_label in template_labels else 0,
            help="模板只调整参数默认值；不会改变只读安全边界，也不会自动下单。",
        )
        selected_template = STRATEGY_TEMPLATES[TEMPLATE_LABEL_TO_KEY[selected_template_label]]
    with top_col2:
        if show_simulation:
            period_label = st.selectbox("回测周期", options=list(BACKTEST_PERIOD_OPTIONS.keys()), index=list(BACKTEST_PERIOD_OPTIONS.keys()).index(default_period_label))
            backtest_years = BACKTEST_PERIOD_OPTIONS[period_label]
        else:
            st.markdown("**回测周期**")
            st.caption(default_period_label)
            backtest_years = BACKTEST_PERIOD_OPTIONS[default_period_label]
    with top_col3:
        if show_simulation:
            initial_capital = st.number_input("初始资金 ($)", min_value=1000.0, max_value=100000000.0, value=float(payload.get("initial_capital", 100000.0)), step=1000.0, label_visibility="visible")
        else:
            st.markdown("**初始资金**")
            initial_capital = float(payload.get("initial_capital", 100000.0))
            st.caption(f"${initial_capital:,.0f}（账户模式优先取购买力）")
    with top_col4:
        st.markdown("<div style='height: 1.55rem;'></div>", unsafe_allow_html=True)  # 与左侧 label 对齐
        if st.button("🔄 恢复默认", width="stretch", key="reset_default_btn"):
            st.session_state["config_payload"] = default_payload.copy()
            st.session_state["selected_backtest_symbols"] = []
            st.rerun()

    # 模板说明 + (条件) 应用模板按钮
    st.caption(selected_template.description)
    template_diff_rows = build_template_diff_rows(payload, selected_template.key)
    if selected_template_label != current_template_label:
        diff_col1, diff_col2 = st.columns([4, 1])
        with diff_col1:
            if template_diff_rows:
                with st.expander("模板参数差异", expanded=False):
                    st.dataframe(pd.DataFrame(template_diff_rows), width="stretch", hide_index=True)
        with diff_col2:
            if st.button("应用模板", width="stretch", type="primary"):
                updated_payload = apply_strategy_template(payload, selected_template.key)
                updated_payload["default_pool"] = payload.get("default_pool", default_payload.get("default_pool", [])).copy()
                updated_payload["default_backtest_symbols"] = st.session_state.get("selected_backtest_symbols", payload.get("default_backtest_symbols", [])).copy()
                st.session_state["config_payload"] = updated_payload
                st.session_state["pending_selected_backtest_symbols"] = updated_payload["default_backtest_symbols"]
                st.rerun()

    # 标的选择（占满整行）
    manual_symbols_text = ""
    symbol_pool = normalize_app_symbols(list(payload["default_pool"]))
    pending_selected_symbols = st.session_state.pop("pending_selected_backtest_symbols", None)
    if pending_selected_symbols is not None:
        st.session_state["selected_backtest_symbols"] = [symbol for symbol in normalize_app_symbols(pending_selected_symbols) if symbol in symbol_pool]
    elif "selected_backtest_symbols" not in st.session_state:
        st.session_state["selected_backtest_symbols"] = []
    else:
        st.session_state["selected_backtest_symbols"] = [symbol for symbol in normalize_app_symbols(st.session_state["selected_backtest_symbols"]) if symbol in symbol_pool]
    selected_symbols = st.multiselect("参与回测标的", options=symbol_pool, key="selected_backtest_symbols")

    # 底部 4 列抽屉：扩展标的池 / 数据接入 / 策略规则 / 参数预设
    drawer_col1, drawer_col2, drawer_col3, drawer_col4 = st.columns(4)
    with drawer_col1:
        with st.expander("➕ 扩展标的池", expanded=False):
            manual_symbols_text = st.text_area("手动输入额外股票代码", placeholder="例如：US.TSLA, US.META\nAVGO", height=80, label_visibility="collapsed")
        manual_symbols = normalize_app_symbols(parse_symbols(manual_symbols_text))
        if manual_symbols:
            symbol_pool = normalize_app_symbols([*payload["default_pool"], *manual_symbols])
    with drawer_col2:
        with st.expander("📡 数据接入", expanded=False):
            data_source = st.radio("数据源", options=["演示数据", "富途真实行情"], index=1, horizontal=True)
            futu_host = "127.0.0.1"
            futu_port = 11111
            futu_provider = None
            refresh_futu_cache = False
            if data_source == "富途真实行情":
                futu_host = st.text_input("OpenD 地址", value="127.0.0.1")
                futu_port = int(st.number_input("OpenD 端口", min_value=1, max_value=65535, value=11111))
                refresh_futu_cache = st.checkbox("强制刷新行情缓存", value=False)
                futu_provider = FutuHistoricalDataProvider(FutuDataConfig(host=futu_host, port=futu_port, cache_dir=ROOT / "data" / "cache"))
                if st.button("测试 OpenD 连接", width="stretch"):
                    ok, message = futu_provider.test_connection()
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)
            if show_account:
                st.caption("账户模式下默认走富途行情。")
    with drawer_col3:
        with st.expander("⚙️ 策略规则参数", expanded=False):
            ma_short = st.number_input("MA 短周期", min_value=5, max_value=100, value=int(payload["ma_short"]))
            ma_long = st.number_input("MA 长周期", min_value=10, max_value=250, value=int(payload["ma_long"]))
            breakout_days = st.number_input("突破回溯天数", min_value=5, max_value=120, value=int(payload["breakout_days"]))
            volume_multiplier = st.number_input("成交量倍数", min_value=0.5, max_value=5.0, value=float(payload["volume_multiplier"]), step=0.1)
            overheat_pct = st.number_input("过热距离 MA 短线 (%)", min_value=1.0, max_value=50.0, value=float(payload["overheat_distance"] * 100), step=1.0)
            entry_position_pct = st.number_input("建仓 %", min_value=5.0, max_value=100.0, value=float(payload.get("entry_position_pct", 0.5) * 100), step=5.0)
            add_position_pct = st.number_input("加仓 %", min_value=5.0, max_value=100.0, value=float(payload.get("add_position_pct", 0.25) * 100), step=5.0)
            reduce_position_pct = st.number_input("减仓 %", min_value=5.0, max_value=100.0, value=float(payload.get("reduce_position_pct", 0.5) * 100), step=5.0)
            min_trade_amount = st.number_input("最小成交金额 ($)", min_value=0.0, max_value=10000.0, value=float(payload.get("min_trade_amount", 100.0)), step=50.0)
            use_sector_filter = st.checkbox("启用 SOXX 板块共振过滤", value=bool(payload["use_sector_filter"]))
    with drawer_col4:
        with st.expander("💾 参数预设", expanded=False):
            presets = load_strategy_presets()
            if presets:
                selected_preset_name = st.selectbox("选择预设", options=sorted(presets.keys()), label_visibility="collapsed")
                preset_col1, preset_col2 = st.columns(2)
                if preset_col1.button("加载", width="stretch"):
                    st.session_state["config_payload"] = presets[selected_preset_name].copy()
                    st.session_state["pending_selected_backtest_symbols"] = presets[selected_preset_name].get("default_backtest_symbols", [])
                    st.rerun()
                if preset_col2.button("删除", width="stretch"):
                    presets.pop(selected_preset_name, None)
                    save_strategy_presets(presets)
                    st.rerun()
            else:
                st.caption("还没有保存过参数预设。")
            preset_name = st.text_input("保存当前参数为", placeholder="例如：半导体趋势默认", label_visibility="collapsed")


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
    status_left, status_right = st.columns([3, 1])
    with status_left:
        if is_default_strategy_params(current_payload, default_payload):
            st.caption("✅ 当前使用 GPT 默认参数")
        else:
            st.caption(f"✏️ 参数已调整 · 当前模板：{get_template_label(current_payload)}")
    with status_right:
        if st.button("保存当前预设", width="stretch", key="save_preset_btn"):
            if preset_name.strip():
                presets[preset_name.strip()] = current_payload.copy()
                save_strategy_presets(presets)
                st.success(f"已保存预设：{preset_name.strip()}")
            else:
                st.warning("请先在右侧『参数预设』面板里填写预设名称。")

if show_account and _acc_box is not None:
    with _acc_box:
        st.markdown("#### 💼 账户与持仓")
        st.caption("日常流程：先读取持仓和账户资金，再把缺失标的加入回测，最后运行回测生成今日行动计划。")
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

        action_col1, action_col2 = st.columns(2)
        if action_col1.button("从富途读取持仓", width="stretch"):
            try:
                acc_id = int(position_acc_id_text.strip()) if position_acc_id_text.strip() else None
                provider = FutuHistoricalDataProvider(FutuDataConfig(host=position_futu_host, port=position_futu_port, cache_dir=ROOT / "data" / "cache"))
                futu_positions_df = provider.get_positions(market=position_market, trd_env=position_env, acc_id=acc_id)
                if futu_positions_df.empty:
                    st.warning("富途返回的当前持仓为空。")
                else:
                    save_current_positions(futu_positions_df)
                    st.session_state["use_current_positions_for_plan"] = True
                    st.session_state["positions_import_message"] = f"已从富途读取并保存 {len(futu_positions_df)} 条持仓。"
                    st.rerun()
            except ValueError:
                st.error("账户 ID 必须是数字；不确定时可以留空。")
            except Exception as exc:
                st.error(format_futu_exception("富途持仓读取", exc))

        if action_col2.button("读取账户资金", width="stretch"):
            try:
                acc_id = int(position_acc_id_text.strip()) if position_acc_id_text.strip() else None
                provider = FutuHistoricalDataProvider(FutuDataConfig(host=position_futu_host, port=position_futu_port, cache_dir=ROOT / "data" / "cache"))
                st.session_state["account_info"] = provider.get_account_info(market=position_market, trd_env=position_env, acc_id=acc_id)
                st.session_state["account_import_message"] = "已读取富途账户资金。"
                st.rerun()
            except ValueError:
                st.error("账户 ID 必须是数字；不确定时可以留空。")
            except Exception as exc:
                st.error(format_futu_exception("富途资金读取", exc))

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
                width="stretch",
                hide_index=True,
            )
            if st.checkbox("用账户资金估算策略计划", value=True):
                account_plan_capital = float(account_info.get("plan_capital") or 0.0)

        saved_positions_df = load_current_positions()
        edited_positions_df = st.data_editor(
            build_position_editor_frame(selected_symbols, saved_positions_df),
            hide_index=True,
            width="stretch",
            num_rows="dynamic",
            disabled=["市场", "类型", "正股标的"],
            key="current_positions_editor",
        )
        position_symbols = get_position_symbols(edited_positions_df)
        option_position_symbols = get_option_position_symbols(edited_positions_df)
        _pending_use = st.session_state.pop("_pending_use_current_positions", None)
        if _pending_use is not None:
            st.session_state["use_current_positions_for_plan"] = bool(_pending_use)
        if "use_current_positions_for_plan" not in st.session_state:
            st.session_state["use_current_positions_for_plan"] = count_position_rows(edited_positions_df) > 0
        use_manual_positions = st.checkbox(
            "用当前持仓生成今日行动计划",
            key="use_current_positions_for_plan",
            help="开启后，今日行动计划会优先使用当前持仓数量和成本，而不是只看回测模拟仓位。",
        )
        st.caption("正股/ETF 会用于今日行动计划；期权只做隔离识别和轻量风险提示。")
        if option_position_symbols:
            st.caption(f"识别到 {len(option_position_symbols)} 个期权持仓：{', '.join(option_position_symbols)}。")
        missing_position_symbols = [symbol for symbol in position_symbols if symbol not in selected_symbols]
        participation_df = build_position_participation_frame(position_symbols, symbol_pool, selected_symbols)
        if not participation_df.empty:
            with st.expander("持仓标的参与状态", expanded=bool(missing_position_symbols)):
                st.dataframe(participation_df, width="stretch", hide_index=True)
        if missing_position_symbols:
            st.warning(f"持仓中有 {len(missing_position_symbols)} 个标的尚未参与当前回测：{', '.join(missing_position_symbols)}")
            add_pool_col1, add_pool_col2 = st.columns(2)
            if add_pool_col1.button("加入股票池并参与回测", width="stretch"):
                updated_payload = add_symbols_to_payload(payload, missing_position_symbols, participate=True)
                updated_selected_symbols = normalize_app_symbols([*selected_symbols, *missing_position_symbols])
                updated_payload["default_backtest_symbols"] = updated_selected_symbols
                st.session_state["pending_selected_backtest_symbols"] = updated_selected_symbols
                st.session_state["config_payload"] = updated_payload
                st.rerun()
            if add_pool_col2.button("仅加入股票池", width="stretch"):
                st.session_state["config_payload"] = add_symbols_to_payload(payload, missing_position_symbols, participate=False)
                st.rerun()
        elif position_symbols:
            st.caption("当前持仓标的已在本次回测选择范围内。")
        save_col1, save_col2 = st.columns(2)
        if save_col1.button("保存持仓", width="stretch"):
            save_current_positions(edited_positions_df)
            if count_position_rows(edited_positions_df) > 0:
                st.session_state["_pending_use_current_positions"] = True
            else:
                st.session_state["_pending_use_current_positions"] = False
            st.session_state["positions_import_message"] = "已保存当前持仓。"
            st.rerun()
        if save_col2.button("清空持仓", width="stretch"):
            save_current_positions(pd.DataFrame(columns=POSITION_COLUMNS))
            st.session_state["_pending_use_current_positions"] = False
            st.rerun()
        if use_manual_positions:
            current_positions = build_current_positions_map(edited_positions_df)

if show_account:
    render_daily_workflow_status(
        selected_symbols=selected_symbols,
        positions_df=edited_positions_df,
        account_info=account_info,
        data_source=data_source,
        position_env_label=position_env_label,
        has_last_backtest="last_backtest" in st.session_state,
    )

if show_account:
    _pending_toast = st.session_state.pop("_refresh_toast", None)
    if _pending_toast:
        st.toast(_pending_toast["msg"], icon=_pending_toast.get("icon", "✅"))
    st.info(f"📌 当前策略来源：**{selected_template_label}**。切换模板请到左侧栏“策略参数”，参数细调在“策略规则参数”折叠面板里。")
    st.checkbox(
        "账户对齐回测（用真实持仓种子化）",
        value=st.session_state.get("align_backtest_with_account", False),
        key="align_backtest_with_account",
        help="开启后，回测起点会按你当前持仓（股数 × 成本价）种子化，模拟策略接管现有账户的表现。仅作参考，不改变历史信号。",
    )
    if st.button(
        "🔄 一键刷新持仓 + 重跑今日策略",
        type="primary",
        width="stretch",
        help="重新从富途读取持仓和账户资金，然后立即跑一次当前模板的回测，生成最新行动计划。",
    ):
        try:
            _refresh_host = st.session_state.get("position_futu_host", "127.0.0.1")
            _refresh_port = int(st.session_state.get("position_futu_port", 11111))
            _market_label = st.session_state.get("position_market_label", "美股 US")
            _env_label = st.session_state.get("position_env_label", "真实账户（只读）")
            _refresh_market = {"美股 US": "US", "港股 HK": "HK", "A股 CN": "CN", "新加坡 SG": "SG"}[_market_label]
            _refresh_env = "REAL" if _env_label == "真实账户（只读）" else "SIMULATE"
            _refresh_provider = FutuHistoricalDataProvider(FutuDataConfig(host=_refresh_host, port=_refresh_port, cache_dir=ROOT / "data" / "cache"))
            _refresh_positions = _refresh_provider.get_positions(market=_refresh_market, trd_env=_refresh_env)
            if not _refresh_positions.empty:
                save_current_positions(_refresh_positions)
                st.session_state["_pending_use_current_positions"] = True
            st.session_state["account_info"] = _refresh_provider.get_account_info(market=_refresh_market, trd_env=_refresh_env)
            st.session_state["auto_run_backtest"] = True
            st.session_state["_refresh_toast"] = {
                "msg": f"刷新成功：持仓 {len(_refresh_positions)} 条、资金已更新。回测重新跑中…",
                "icon": "🔄",
            }
            st.rerun()
        except Exception as exc:
            st.session_state["_refresh_toast"] = {
                "msg": f"刷新失败：{format_futu_exception('一键刷新', exc)}",
                "icon": "⚠️",
            }
            st.rerun()

_auto_run_backtest = st.session_state.pop("auto_run_backtest", False)
_, _run_box_col, _ = st.columns([1, 3, 1])
with _run_box_col:
    _run_c1, _run_c2 = st.columns(2)
    run_default = _run_c1.button("▶ 运行默认回测", type="primary", width="stretch") or _auto_run_backtest
    run_current = _run_c2.button("运行当前参数回测", width="stretch")
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
                st.warning("部分标的行情获取失败，系统会跳过失败标的并继续使用可用行情。若是富途真实行情，请先确认 OpenD、市场权限和代码格式。")
                st.dataframe(pd.DataFrame([{"标的": symbol, "错误": error} for symbol, error in data_errors.items()]), width="stretch", hide_index=True)
            available_symbols = [symbol for symbol in config.default_backtest_symbols if symbol in market_data]
            if config.use_sector_filter and config.sector_symbol not in market_data:
                st.error(f"板块过滤标的 {config.sector_symbol} 行情不可用，无法执行当前策略。")
                st.stop()
            if not available_symbols:
                st.error("没有任何参与回测标的成功获取行情。请确认 OpenD 已启动、行情权限可用，或切换到演示数据先检查流程。")
                st.stop()
            if len(available_symbols) != len(config.default_backtest_symbols):
                skipped_symbols = [symbol for symbol in config.default_backtest_symbols if symbol not in available_symbols]
                st.info(f"本次回测使用 {len(available_symbols)} 个可用标的，已跳过：{', '.join(skipped_symbols)}")
                config = build_config({**config.to_dict(), "default_backtest_symbols": available_symbols})
    else:
        market_data = make_demo_market_data(config.default_backtest_symbols, sector_symbol=config.sector_symbol, years=config.backtest_years, warmup_days=config.indicator_warmup_days)
    # 账户对齐：仅账户模式 + 用户开启时，把真实持仓种子化进回测引擎。
    _align_account = show_account and bool(st.session_state.get("align_backtest_with_account", False))
    _seed_positions: dict[str, dict[str, float]] | None = None
    if _align_account and current_positions:
        _seed_positions = {}
        for _sym, _info in current_positions.items():
            _shares = float(_info.get("shares", 0.0) or 0.0)
            _avg = float(_info.get("avg_cost", 0.0) or 0.0)
            if _sym in config.default_backtest_symbols and _shares > 0:
                _seed_positions[_sym] = {"shares": _shares, "cost_basis": _shares * _avg}
        if not _seed_positions:
            _seed_positions = None
    result = BacktestService(config).run(market_data, initial_positions=_seed_positions)
    st.session_state["last_backtest"] = {"config": config, "market_data": market_data, "result": result, "data_source": data_source, "account_aligned": bool(_seed_positions)}

_summary_label = "当前策略摘要" if show_simulation else "策略历史回测参考（与你账户无关）"
with st.expander(_summary_label, expanded=show_simulation):
    if show_account:
        st.caption("以下基于策略在默认资金 $10,000、约 6 个月窗口的历史回放，仅用于判断策略当下是否还在有效区间。你账户的真实情况请看下方“账户快照”。")
        if st.session_state.get("last_backtest", {}).get("account_aligned"):
            st.success("✅ 本次回测已按你当前真实持仓种子化（账户对齐模式）。")
    st.markdown(build_strategy_summary(config, data_source))

equity_df = pd.DataFrame(result.symbol_equity_curve)
if run_requested:
    history = st.session_state.setdefault("backtest_history", load_backtest_history())
    history.append(build_backtest_history_row(config, data_source, result, equity_df, "默认参数" if run_default else "当前参数"))
    st.session_state["backtest_history"] = history[-BACKTEST_HISTORY_LIMIT:]
    save_backtest_history(st.session_state["backtest_history"])

_result_label = "回测结果与权益曲线" if show_simulation else "策略历史回测结果（仅供参考）"
with st.expander(_result_label, expanded=show_simulation):
    if show_account:
        st.caption("以下指标由策略按默认资金 $10,000、历史价格穿越回放得到，与你账户的真实持仓、入场时间、成本无关。仅用于评估策略本身是否仍然健康。")
    st.caption(f"当前回测周期：约 {config.backtest_years:g} 年")
    st.caption(f"当前数据源：{data_source}")
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
        st.plotly_chart(equity_fig, width="stretch")
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


# ===== 工作区 dispatcher（使用 workspaces.WorkspaceContext） =====
ctx = WorkspaceContext(
    config=config,
    market_data=market_data,
    result=result,
    equity_df=equity_df,
    strategy_plan_df=strategy_plan_df,
    option_overlay_df=option_overlay_df,
    option_combo_df=option_combo_df,
    account_info=account_info,
    edited_positions_df=edited_positions_df,
    current_positions=current_positions,
    option_position_symbols=option_position_symbols,
    watchlist_df=watchlist_df,
    position_env_label=position_env_label,
    capital_source=capital_source,
    capital_value=float(capital_value),
    data_source=data_source,
    app_version=APP_VERSION,
    append_cockpit_snapshot=append_cockpit_snapshot,
    load_cockpit_snapshots=load_cockpit_snapshots,
    append_cockpit_review=append_cockpit_review,
    load_cockpit_reviews=load_cockpit_reviews,
    append_cockpit_regression=append_cockpit_regression,
    load_cockpit_regressions=load_cockpit_regressions,
)
if show_simulation:
    render_simulation_workspace(ctx)
else:
    render_account_workspace(ctx)
