"""双工作区渲染：模拟研究 / 账户追踪。

把 app.py 中两个 render 函数搬到独立模块，避免单文件超长；
通过 WorkspaceContext 注入所有数据与持久化回调，保持与 Streamlit 解耦。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from trend_option_backtest.cockpit import (
    build_cockpit_overview,
    build_cockpit_risk_budget,
    build_cockpit_risk_budget_detail,
    build_cockpit_sections,
    build_cockpit_snapshot_row,
    build_regression_check_frame,
    build_regression_check_rows,
    build_regression_check_summary,
    build_review_trend,
    build_weekly_review_summary,
)
from trend_option_backtest.exporting import build_strategy_plan_export_frame
from trend_option_backtest.history import (
    build_template_history_summary,
    filter_history_by_templates,
    normalize_backtest_history_frame,
)
from trend_option_backtest.models import BacktestResult, StrategyConfig
from trend_option_backtest.planning import (
    filter_unmatched_option_legs,
    get_position_symbols,
    normalize_app_symbol,
    normalize_app_symbols,
)
from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider
from trend_option_backtest.screening import build_discovery_frame, score_symbol_signals, split_discovery_frame
from trend_option_backtest.strategies.trend_following import TrendFollowingStrategy


# ===== 模块内常量（仅 workspaces.py 使用） =====
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


# ===== 本地小工具（与 app.py 同名实现保持一致） =====
def _format_pct(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value * 100:.2f}%"


def _format_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${float(value):,.2f}"


def _dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def _select_existing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame[[column for column in columns if column in frame.columns]].copy()


def _clean_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    for column in display.columns:
        if pd.api.types.is_numeric_dtype(display[column]):
            continue
        display[column] = display[column].fillna("")
    return display


def _count_position_rows(frame: pd.DataFrame) -> int:
    if frame.empty or "持仓股数" not in frame.columns:
        return 0
    quantities = pd.to_numeric(frame["持仓股数"], errors="coerce").fillna(0.0)
    return int((quantities.abs() > 1e-12).sum())


@dataclass
class WorkspaceContext:
    """工作区渲染上下文：所有数据 + 必要的持久化回调。"""

    config: StrategyConfig
    market_data: dict[str, pd.DataFrame]
    result: BacktestResult
    equity_df: pd.DataFrame
    strategy_plan_df: pd.DataFrame
    option_overlay_df: pd.DataFrame
    option_combo_df: pd.DataFrame
    account_info: dict[str, Any] | None
    edited_positions_df: pd.DataFrame
    current_positions: dict[str, dict[str, Any]]
    option_position_symbols: list[str]
    watchlist_df: pd.DataFrame
    position_env_label: str
    capital_source: str
    capital_value: float
    data_source: str
    app_version: str
    futu_host: str
    futu_port: int
    futu_cache_dir: Path
    # 持久化回调（保持 CSV 路径在 app.py 集中管理）
    append_cockpit_snapshot: Callable[[dict[str, Any]], pd.DataFrame]
    load_cockpit_snapshots: Callable[[], pd.DataFrame]
    append_cockpit_review: Callable[[dict[str, Any]], pd.DataFrame]
    load_cockpit_reviews: Callable[[], pd.DataFrame]
    append_cockpit_regression: Callable[[pd.DataFrame], pd.DataFrame]
    load_cockpit_regressions: Callable[[], pd.DataFrame]


# ===== 渲染函数 =====
def _render_single_symbol_chart(ctx: WorkspaceContext) -> None:
    st.subheader("单标的价格与仓位")
    chart_options = ctx.config.default_backtest_symbols
    focused_symbol = st.session_state.get("cockpit_focus_symbol")
    last_synced_focus = st.session_state.get("_last_synced_focus_symbol")
    if focused_symbol and focused_symbol in chart_options and focused_symbol != last_synced_focus:
        st.session_state["chart_symbol_select"] = focused_symbol
        st.session_state["_last_synced_focus_symbol"] = focused_symbol
    chart_symbol = st.selectbox("查看标的", options=chart_options, key="chart_symbol_select")
    if chart_symbol not in ctx.market_data:
        st.warning(f"{chart_symbol} 没有可用行情数据。")
        return
    strategy = TrendFollowingStrategy(ctx.config)
    chart_df = strategy.prepare_with_signals(ctx.market_data[chart_symbol], ctx.market_data.get(ctx.config.sector_symbol))
    if not ctx.equity_df.empty:
        chart_start = pd.Timestamp(ctx.equity_df["date"].min())
        chart_df = chart_df[pd.to_datetime(chart_df["date"]) >= chart_start]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["close"], mode="lines", name="收盘价"))
    if "ma_short" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["ma_short"], mode="lines", name=f"MA{ctx.config.ma_short}"))
    if "ma_long" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df["date"], y=chart_df["ma_long"], mode="lines", name=f"MA{ctx.config.ma_long}"))
    # 单标的收益率曲线（副 Y 轴）
    symbol_equity_rows = getattr(ctx.result, "symbol_equity_curve", None) or []
    return_series_df: pd.DataFrame | None = None
    if symbol_equity_rows:
        equity_curve_df = pd.DataFrame(symbol_equity_rows)
        if chart_symbol in equity_curve_df.columns:
            equity_curve_df["date"] = pd.to_datetime(equity_curve_df["date"])
            symbol_equity_series = equity_curve_df[["date", chart_symbol]].dropna()
            base_capital = float(symbol_equity_series[chart_symbol].iloc[0]) if not symbol_equity_series.empty else 0.0
            if base_capital > 0:
                symbol_equity_series = symbol_equity_series.copy()
                symbol_equity_series["return_pct"] = (symbol_equity_series[chart_symbol] / base_capital - 1.0) * 100.0
                return_series_df = symbol_equity_series[["date", "return_pct"]]
                fig.add_trace(go.Scatter(
                    x=return_series_df["date"], y=return_series_df["return_pct"],
                    mode="lines", name="累计收益率 %",
                    line=dict(color="#9333EA", width=2, dash="dot"),
                    yaxis="y2",
                    hovertemplate="收益率 %{y:.2f}%<extra></extra>",
                ))
    # 叠加交易动作标记
    symbol_trades = [t for t in (ctx.result.trades or []) if t.get("symbol") == chart_symbol]
    if symbol_trades:
        trades_df = pd.DataFrame(symbol_trades)
        trades_df["date"] = pd.to_datetime(trades_df["date"])
        buy_actions = {"买入", "加仓"}
        sell_actions = {"减仓", "清仓", "期末平仓"}
        buy_df = trades_df[trades_df["action"].isin(buy_actions)]
        sell_df = trades_df[trades_df["action"].isin(sell_actions)]
        if not buy_df.empty:
            fig.add_trace(go.Scatter(
                x=buy_df["date"], y=buy_df["price"], mode="markers", name="买入/加仓",
                marker=dict(color="#16A34A", size=11, symbol="triangle-up", line=dict(color="#0F5132", width=1)),
                customdata=buy_df[["action", "reason"]].fillna("").values,
                hovertemplate="%{customdata[0]} @ %{y:.2f}<br>%{customdata[1]}<extra></extra>",
            ))
        if not sell_df.empty:
            fig.add_trace(go.Scatter(
                x=sell_df["date"], y=sell_df["price"], mode="markers", name="减仓/清仓",
                marker=dict(color="#DC2626", size=11, symbol="triangle-down", line=dict(color="#7F1D1D", width=1)),
                customdata=sell_df[["action", "reason"]].fillna("").values,
                hovertemplate="%{customdata[0]} @ %{y:.2f}<br>%{customdata[1]}<extra></extra>",
            ))
        # 在收益率曲线上同步标注交易点
        if return_series_df is not None and not return_series_df.empty:
            return_lookup = return_series_df.sort_values("date").rename(columns={"date": "date_aligned", "return_pct": "cum_return_pct"})
            aligned_trades = pd.merge_asof(
                trades_df.sort_values("date"),
                return_lookup,
                left_on="date", right_on="date_aligned",
                direction="backward",
            ).dropna(subset=["cum_return_pct"])
            buy_ret = aligned_trades[aligned_trades["action"].isin(buy_actions)]
            sell_ret = aligned_trades[aligned_trades["action"].isin(sell_actions)]
            if not buy_ret.empty:
                fig.add_trace(go.Scatter(
                    x=buy_ret["date"], y=buy_ret["cum_return_pct"], mode="markers", name="收益率·买入/加仓",
                    marker=dict(color="#16A34A", size=9, symbol="circle", line=dict(color="#FFFFFF", width=1.5)),
                    yaxis="y2",
                    customdata=buy_ret[["action", "reason"]].fillna("").values,
                    hovertemplate="%{customdata[0]}时累计收益 %{y:.2f}%<br>%{customdata[1]}<extra></extra>",
                    showlegend=False,
                ))
            if not sell_ret.empty:
                fig.add_trace(go.Scatter(
                    x=sell_ret["date"], y=sell_ret["cum_return_pct"], mode="markers", name="收益率·减仓/清仓",
                    marker=dict(color="#DC2626", size=9, symbol="circle", line=dict(color="#FFFFFF", width=1.5)),
                    yaxis="y2",
                    customdata=sell_ret[["action", "reason"]].fillna("").values,
                    hovertemplate="%{customdata[0]}时累计收益 %{y:.2f}%<br>%{customdata[1]}<extra></extra>",
                    showlegend=False,
                ))
    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="价格"),
        yaxis2=dict(title="收益率 %", overlaying="y", side="right", showgrid=False, zeroline=True, zerolinecolor="#CBD5E1"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")


def render_simulation_workspace(ctx: WorkspaceContext) -> None:
    """模拟研究工作区：单标的图表 + 回测历史。"""
    _render_single_symbol_chart(ctx)
    st.subheader("回测运行历史")
    history_rows = st.session_state.get("backtest_history", [])
    if not history_rows:
        st.info("当前会话还没有历史记录。")
        return
    history_df = normalize_backtest_history_frame(history_rows)
    summary_df = build_template_history_summary(history_rows)
    if not summary_df.empty:
        summary_display_df = summary_df.copy()
        summary_display_df["平均收益率"] = summary_display_df["平均收益率"].map(_format_pct)
        summary_display_df["最好收益率"] = summary_display_df["最好收益率"].map(_format_pct)
        summary_display_df["最差回撤"] = summary_display_df["最差回撤"].map(_format_pct)
        summary_display_df["平均Sharpe"] = summary_display_df["平均Sharpe"].map(lambda value: f"{float(value):.2f}" if not pd.isna(value) else "")
        summary_display_df["平均交易动作"] = summary_display_df["平均交易动作"].map(lambda value: f"{float(value):.1f}" if not pd.isna(value) else "")
        st.dataframe(summary_display_df, width="stretch", hide_index=True)

    template_options = sorted(history_df["策略模板"].dropna().map(str).unique().tolist()) if "策略模板" in history_df.columns else []
    selected_history_templates = st.multiselect("按策略模板筛选历史", options=template_options, default=template_options)
    filtered_history_df = filter_history_by_templates(history_rows, selected_history_templates)
    if filtered_history_df.empty:
        st.info("当前筛选条件下没有历史记录。")
    else:
        st.dataframe(filtered_history_df.tail(20).sort_values("运行时间", ascending=False), width="stretch", hide_index=True)


def render_account_workspace(ctx: WorkspaceContext) -> None:
    """账户追踪工作区：主画布（今日决策 / 账户快照 / 标的发掘 / Cockpit / 复盘档案）。"""
    _tab_today, _tab_status, _tab_discovery, _tab_cockpit, _tab_archive = st.tabs([
        "📋 今日决策",
        "📊 账户快照",
        "🔍 标的发掘",
        "🎛 Cockpit",
        "📜 复盘档案",
    ])
    with _tab_today:
        _render_today_tab(ctx)
    with _tab_status:
        _render_status_tab(ctx)
    with _tab_discovery:
        _render_discovery_tab(ctx)
    with _tab_cockpit:
        _render_cockpit_tab(ctx)
    with _tab_archive:
        _render_archive_tab(ctx)


def _format_price(value: object, symbol: str) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    currency = "HK$" if str(symbol).upper().startswith("HK.") else "$"
    return f"{currency}{float(value):,.2f}"


def _render_signal_radar(row: pd.Series, *, height: int = 190) -> None:
    labels = ["趋势", "突破", "量能", "共振", "温度", "风险"]
    values = [
        1.0 if bool(row.get("均线趋势")) else 0.35,
        1.0 if bool(row.get("价格突破")) else 0.35,
        1.0 if bool(row.get("成交量确认")) else 0.35,
        1.0 if bool(row.get("行业共振")) else 0.35,
        1.0 if bool(row.get("未过热")) else 0.35,
        max(0.25, min(1.0, 1 - abs(float(row.get("距入场参考", 0.0))))),
    ]
    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=[*values, values[0]],
                theta=[*labels, labels[0]],
                fill="toself",
                line=dict(color="#2563EB", width=2),
                fillcolor="rgba(37,99,235,0.18)",
                hoverinfo="skip",
                showlegend=False,
            )
        ]
    )
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        polar=dict(radialaxis=dict(visible=False, range=[0, 1]), angularaxis=dict(tickfont=dict(size=11))),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _build_action_signal_radar_row(plan_row: pd.Series, ctx: WorkspaceContext) -> pd.Series | None:
    symbol = normalize_app_symbol(str(plan_row.get("标的", "")))
    if not symbol:
        return None
    symbol_data = ctx.market_data.get(symbol)
    if symbol_data is None:
        symbol_data = ctx.market_data.get(symbol.split(".", 1)[-1])
    if symbol_data is None or getattr(symbol_data, "empty", True):
        return None

    sector_data = ctx.market_data.get(ctx.config.sector_symbol)
    if sector_data is None:
        sector_data = ctx.market_data.get(normalize_app_symbol(ctx.config.sector_symbol))
    signal_df = TrendFollowingStrategy(ctx.config).prepare_with_signals(symbol_data, sector_data)
    signal_df = signal_df.dropna(subset=["close", "ma_short", "ma_long", "prior_high", "volume_ma"])
    if signal_df.empty:
        return None

    last_row = signal_df.iloc[-1]
    scoring = score_symbol_signals(last_row, ctx.config)
    signals = dict(scoring["signals"])
    close = float(last_row.get("close", 0.0) or 0.0)
    ma_short = float(last_row.get("ma_short", 0.0) or 0.0)
    prior_high = float(last_row.get("prior_high", 0.0) or 0.0)
    entry_price = max(ma_short, prior_high)
    distance_to_entry = close / entry_price - 1 if close > 0 and entry_price > 0 else float(plan_row.get("距关键价位", 0.0) or 0.0)
    return pd.Series(
        {
            "均线趋势": bool(signals.get("trend_ok")),
            "价格突破": bool(signals.get("breakout_ok")),
            "成交量确认": bool(signals.get("volume_ok")),
            "行业共振": bool(signals.get("sector_ok")),
            "未过热": bool(signals.get("temperature_ok")),
            "距入场参考": distance_to_entry,
        }
    )


def _render_discovery_symbol_card(row: pd.Series) -> None:
    symbol = str(row.get("标的", ""))
    score = int(row.get("综合评分", 0))
    badge_bg = "#DCFCE7" if score >= 5 else "#DBEAFE"
    badge_fg = "#166534" if score >= 5 else "#1D4ED8"
    with st.container(border=True):
        st.markdown(
            f"""
            <div style='display:flex;justify-content:space-between;gap:12px;align-items:flex-start;'>
              <div style='min-width:0;'>
                <div style='font-size:1.28rem;font-weight:900;color:#0F172A;letter-spacing:-0.03em;'>{symbol}</div>
                <div style='font-size:0.82rem;color:#64748B;font-weight:700;margin-top:4px;'>{row.get('分组', '')} · 收盘 {_format_price(row.get('收盘价'), symbol)}</div>
              </div>
              <div style='background:{badge_bg};color:{badge_fg};border-radius:999px;padding:5px 12px;font-size:0.78rem;font-weight:900;white-space:nowrap;'>{score} / 5 {row.get('接近程度', '')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        chart_col, detail_col = st.columns([1.0, 1.55], gap="small")
        with chart_col:
            _render_signal_radar(row)
        with detail_col:
            signal_labels = []
            for label in ["均线趋势", "价格突破", "成交量确认", "行业共振", "未过热"]:
                is_on = bool(row.get(label))
                bg = "#DCFCE7" if is_on else "#F8FAFC"
                fg = "#166534" if is_on else "#64748B"
                bd = "#BBF7D0" if is_on else "#E2E8F0"
                signal_labels.append(f"<span style='background:{bg};color:{fg};border:1px solid {bd};border-radius:999px;padding:4px 9px;font-size:0.76rem;font-weight:800;white-space:nowrap;'>{label}</span>")
            st.markdown(f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 12px;'>{''.join(signal_labels)}</div>", unsafe_allow_html=True)
            price_cols = st.columns(2)
            values = [
                ("入场参考", _format_price(row.get("入场参考价"), symbol), "#0F172A"),
                ("止损参考", _format_price(row.get("止损参考价"), symbol), "#DC2626"),
                ("止盈参考", _format_price(row.get("止盈参考价"), symbol), "#15803D"),
                ("首仓金额", _format_money(row.get("首仓参考金额")), "#1D4ED8"),
            ]
            for index, (label, value, color) in enumerate(values):
                with price_cols[index % 2]:
                    st.markdown(
                        f"""
                        <div style='background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:8px 10px;margin-bottom:8px;min-width:0;'>
                          <div style='font-size:0.72rem;color:#64748B;font-weight:700;'>{label}</div>
                          <div style='font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1rem;font-weight:900;color:{color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{value}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )


def _render_discovery_group_columns(others_df: pd.DataFrame) -> None:
    if others_df.empty:
        st.success("没有未命中的观察标的。")
        return
    group_names = others_df["分组"].dropna().map(str).drop_duplicates().tolist()
    columns = st.columns(min(3, max(1, len(group_names))))
    for index, group_name in enumerate(group_names):
        group_df = others_df[others_df["分组"].map(str) == group_name].sort_values(["综合评分", "距入场参考", "标的"], ascending=[False, False, True]).reset_index(drop=True)
        with columns[index % len(columns)]:
            top_note = str(group_df.iloc[0].get("提前关注点", "")) if not group_df.empty else ""
            st.markdown(
                f"""
                <div title='{top_note}' style='background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:12px;margin-bottom:10px;'>
                  <div style='display:flex;justify-content:space-between;gap:8px;align-items:flex-start;'>
                    <div>
                      <div style='font-size:0.95rem;font-weight:900;color:#0F172A;'>{group_name}</div>
                      <div style='font-size:0.75rem;color:#64748B;font-weight:700;margin-top:3px;'>{len(group_df)} 只 · 按接近度排序</div>
                    </div>
                    <span style='width:20px;height:20px;border-radius:999px;background:#EFF6FF;color:#1D4ED8;border:1px solid #BFDBFE;display:inline-flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:900;'>i</span>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for _, row in group_df.head(5).iterrows():
                score = int(row.get("综合评分", 0))
                tag_bg = "#FEF3C7" if score >= 3 else "#E0F2FE" if score == 2 else "#F1F5F9"
                tag_fg = "#B45309" if score >= 3 else "#0369A1" if score == 2 else "#64748B"
                st.markdown(
                    f"""
                    <div title='{row.get('提前关注点', '')}' style='background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:10px;margin-bottom:8px;'>
                      <div style='display:flex;justify-content:space-between;gap:8px;align-items:center;'>
                        <div style='font-size:0.92rem;font-weight:900;color:#0F172A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{row.get('标的', '')}</div>
                        <span style='background:{tag_bg};color:{tag_fg};border-radius:999px;padding:3px 8px;font-size:0.72rem;font-weight:900;white-space:nowrap;'>{row.get('接近程度', '')}</span>
                      </div>
                      <div style='font-size:0.78rem;color:#334155;font-weight:800;line-height:1.45;margin-top:7px;'>{row.get('转入场条件', '')}</div>
                      <div style='font-size:0.72rem;color:#64748B;font-weight:700;margin-top:4px;'>距入场 {float(row.get('距入场参考', 0.0)) * 100:+.2f}% · {score}/5</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _render_discovery_tab(ctx: WorkspaceContext) -> None:
    st.subheader("标的发掘")
    st.caption("从富途自选股里筛出当前最接近策略入场条件的标的。只读取自选股和行情，不会下单。")

    provider = FutuHistoricalDataProvider(FutuDataConfig(host=ctx.futu_host, port=int(ctx.futu_port), cache_dir=ctx.futu_cache_dir))
    controls = st.container(border=True)
    with controls:
        col1, col2, col3 = st.columns([1.2, 1.2, 2.2])
        if col1.button("📥 读取自选股", width="stretch", key="discovery_load_watchlists"):
            now_ts = time.time()
            last_read_ts = float(st.session_state.get("discovery_watchlist_loaded_at", 0.0) or 0.0)
            cached_groups = st.session_state.get("discovery_watchlist_groups", {})
            cooldown_seconds = 30.0
            try:
                if cached_groups and now_ts - last_read_ts < cooldown_seconds:
                    remain = max(0.0, cooldown_seconds - (now_ts - last_read_ts))
                    st.info(f"读取过于频繁，已使用最近一次自选股结果（建议 {remain:.1f} 秒后再拉取）。")
                else:
                    with st.spinner("正在按富途频率限制读取自选股，分组较多时可能需要等待 30 秒左右..."):
                        groups = provider.get_watchlist_symbols()
                    st.session_state["discovery_watchlist_groups"] = groups
                    st.session_state["discovery_selected_groups"] = list(groups.keys())
                    st.session_state["discovery_watchlist_loaded_at"] = now_ts
                    st.success(f"已读取 {len(groups)} 个自选股分组。")
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if "频率" in message and cached_groups:
                    st.warning("触发富途频率限制，已保留上次读取的自选股结果，请稍后再试。")
                elif "频率" in message:
                    st.error("读取自选股失败：触发富途接口频率限制，请等待约 30 秒后重试。")
                else:
                    st.error(f"读取自选股失败：{exc}")
        watchlist_groups = st.session_state.get("discovery_watchlist_groups", {})
        group_options = list(watchlist_groups.keys())
        saved_groups = [group for group in st.session_state.get("discovery_selected_groups", group_options) if group in group_options]
        if not saved_groups and group_options:
            saved_groups = group_options
        st.session_state["discovery_selected_groups"] = saved_groups
        selected_groups = col3.multiselect(
            "筛选分组",
            options=group_options,
            default=saved_groups,
            key="discovery_selected_groups",
            label_visibility="collapsed",
            placeholder="先读取自选股分组",
        )
        if col2.button("🔎 刷新筛选", width="stretch", key="discovery_run_screen"):
            selected_watchlists = {group: watchlist_groups.get(group, []) for group in selected_groups}
            symbols = normalize_app_symbols([symbol for symbols in selected_watchlists.values() for symbol in symbols])
            if not symbols:
                st.warning("请先读取并选择至少一个自选股分组。")
            else:
                with st.spinner("正在读取行情并筛选自选股..."):
                    market_data, data_errors = provider.get_market_data_with_errors(
                        symbols,
                        sector_symbol=ctx.config.sector_symbol,
                        years=ctx.config.backtest_years,
                        warmup_days=ctx.config.indicator_warmup_days,
                        use_cache=True,
                    )
                    result_df = build_discovery_frame(selected_watchlists, market_data, ctx.config, plan_capital=ctx.capital_value)
                    st.session_state["discovery_result_df"] = result_df
                    st.session_state["discovery_data_errors"] = data_errors
                st.success(f"筛选完成：{len(result_df)} 只标的可分析。")

    result_df = st.session_state.get("discovery_result_df", pd.DataFrame())
    data_errors = st.session_state.get("discovery_data_errors", {})
    if isinstance(data_errors, dict) and data_errors:
        with st.expander(f"行情读取失败 {len(data_errors)} 只", expanded=False):
            st.dataframe(pd.DataFrame([{"标的": symbol, "错误": error} for symbol, error in data_errors.items()]), width="stretch", hide_index=True)
    if not isinstance(result_df, pd.DataFrame) or result_df.empty:
        st.info("读取富途自选股并点击“刷新筛选”后，这里会优先展示符合入场条件的标的。")
        return

    hits_df, others_df = split_discovery_frame(result_df)
    metric_cols = st.columns(4)
    metric_cols[0].metric("参与筛选", len(result_df))
    metric_cols[1].metric("符合入场", len(hits_df))
    metric_cols[2].metric("接近触发", int((others_df["综合评分"] == 3).sum()) if not others_df.empty else 0)
    metric_cols[3].metric("自选分组", result_df["分组"].nunique())

    st.markdown("#### 符合入场条件")
    if hits_df.empty:
        st.warning("当前没有评分达到 4/5 的入场候选。可以展开下方分组查看最接近触发的标的。")
    else:
        card_cols = st.columns(2)
        for index, (_, row) in enumerate(hits_df.iterrows()):
            with card_cols[index % 2]:
                _render_discovery_symbol_card(row)

        selected_hit_symbols = st.multiselect("加入回测标的池", options=hits_df["标的"].tolist(), default=hits_df["标的"].tolist(), key="discovery_add_symbols")
        if st.button("加入回测标的池", width="stretch", key="discovery_add_pool_btn"):
            current_payload = ctx.config.to_dict()
            updated_pool = normalize_app_symbols([*current_payload.get("default_pool", []), *selected_hit_symbols])
            updated_symbols = normalize_app_symbols([*current_payload.get("default_backtest_symbols", []), *selected_hit_symbols])
            current_payload["default_pool"] = updated_pool
            current_payload["default_backtest_symbols"] = updated_symbols
            st.session_state["config_payload"] = current_payload
            st.session_state["pending_selected_backtest_symbols"] = updated_symbols
            st.success(f"已准备加入 {len(selected_hit_symbols)} 只标的；页面刷新后会进入回测标的池。")

    with st.expander("其他关注标的", expanded=False):
        _render_discovery_group_columns(others_df)


def _render_status_tab(ctx: WorkspaceContext) -> None:
    """� 账户快照 tab：资金 + 持仓汇总。"""
    st.subheader("账户快照")
    _snap_cols = st.columns(4)
    _snap_cols[0].metric("总资产", _format_money(ctx.account_info.get("total_assets")) if ctx.account_info else "未读取")
    _snap_cols[1].metric("现金", _format_money(ctx.account_info.get("cash")) if ctx.account_info else "未读取")
    _snap_cols[2].metric("购买力", _format_money(ctx.account_info.get("buying_power")) if ctx.account_info else "未读取")
    _stock_rows = int(_count_position_rows(ctx.edited_positions_df))
    _option_rows = len(ctx.option_position_symbols)
    _snap_cols[3].metric("持仓条目", f"{_stock_rows} 正股/ETF · {_option_rows} 期权")
    if not ctx.account_info:
        st.caption("还没读取过账户资金。可点击左侧“🔄 一键刷新持仓 + 重跑今日策略”，或到左侧账户卡里点“💰 读取资金”。")
    else:
        st.caption(f"账户环境：{ctx.position_env_label}。资金口径来自富途 OpenAPI，仅做读取，不会下单。")


def _render_cockpit_tab(ctx: WorkspaceContext) -> None:
    """🎛 Cockpit tab：策略 Cockpit 全块（含风险预算 / 任务 / 聚焦 / 分区明细 / 快照 / 复盘 / 检查清单）。"""
    st.subheader("策略 Cockpit")
    if ctx.strategy_plan_df.empty:
        st.info("运行回测并生成观察清单后，这里会汇总当前动作、风险队列、接近触发和期权关注。")
    else:
        cockpit_metrics, cockpit_tasks_df = build_cockpit_overview(ctx.strategy_plan_df, ctx.option_overlay_df, ctx.option_combo_df)
        cockpit_sections = build_cockpit_sections(ctx.strategy_plan_df, ctx.option_overlay_df, ctx.option_combo_df)
        cockpit_risk_budget = build_cockpit_risk_budget(ctx.strategy_plan_df, ctx.option_overlay_df, ctx.option_combo_df, capital_value=float(ctx.capital_value))
        cockpit_risk_budget_detail_df = build_cockpit_risk_budget_detail(ctx.strategy_plan_df, ctx.option_overlay_df, ctx.option_combo_df)
        metric_cols = st.columns(4)
        for column, name in zip(metric_cols, ["当前动作", "降低风险", "接近触发", "期权关注"]):
            column.metric(name, cockpit_metrics[name])
        st.caption(f"计划资金基准：{ctx.capital_source} {_format_money(ctx.capital_value)}。Cockpit 只做开盘前观察汇总，不自动下单。")
        with st.expander("风险预算", expanded=False):
            budget_cols = st.columns(6)
            budget_cols[0].metric("增风险金额", _format_money(cockpit_risk_budget["增风险金额"]))
            budget_cols[1].metric("降风险金额", _format_money(cockpit_risk_budget["降风险金额"]))
            budget_cols[2].metric("净风险变化", _format_money(cockpit_risk_budget["净风险变化"]))
            budget_cols[3].metric("动作资金占比", _format_pct(cockpit_risk_budget["今日动作资金占比"]))
            budget_cols[4].metric("潜在接股金额", _format_money(cockpit_risk_budget["潜在接股金额"]))
            budget_cols[5].metric("组合价差风险", _format_money(cockpit_risk_budget["组合价差风险金额"]))
            if cockpit_risk_budget_detail_df.empty:
                st.caption("当前没有可拆解的风险预算明细。")
            else:
                budget_detail_display_df = cockpit_risk_budget_detail_df.copy()
                budget_detail_display_df["参考金额"] = budget_detail_display_df["参考金额"].map(lambda value: "" if pd.isna(value) else _format_money(value))
                st.dataframe(budget_detail_display_df, width="stretch", hide_index=True)

        edited_cockpit_tasks_df = pd.DataFrame(columns=["状态", "备注", *cockpit_tasks_df.columns.tolist()])
        if cockpit_tasks_df.empty:
            st.success("当前没有已触发动作、临近触发或需要优先复核的期权持仓。")
        else:
            editable_tasks_df = cockpit_tasks_df.copy()
            editable_tasks_df.insert(0, "状态", "未处理")
            editable_tasks_df.insert(1, "备注", "")
            edited_cockpit_tasks_df = st.data_editor(
                editable_tasks_df,
                width="stretch",
                hide_index=True,
                column_config={"状态": st.column_config.SelectboxColumn("状态", options=["未处理", "已处理", "跳过", "等待"]), "备注": st.column_config.TextColumn("备注")},
                key="cockpit_task_status_editor",
            )

        focus_symbols = sorted({symbol for symbol in ctx.strategy_plan_df.get("标的", pd.Series(dtype=str)).dropna().map(str).tolist() if symbol in ctx.config.default_backtest_symbols})
        if focus_symbols:
            focused_symbol = st.selectbox("Cockpit 聚焦标的", options=focus_symbols, key="cockpit_focus_symbol")
            focus_plan_df = ctx.strategy_plan_df[ctx.strategy_plan_df["标的"] == focused_symbol].copy()
            focus_combo_df = ctx.option_combo_df[ctx.option_combo_df["正股标的"] == focused_symbol].copy() if not ctx.option_combo_df.empty else pd.DataFrame()
            with st.expander(f"{focused_symbol} 聚焦摘要", expanded=True):
                if not focus_plan_df.empty:
                    row = focus_plan_df.iloc[0]
                    focus_cols = st.columns(4)
                    focus_cols[0].metric("计划动作", str(row.get("计划动作", "")))
                    focus_cols[1].metric("优先级", str(row.get("优先级", "")))
                    focus_cols[2].metric("距关键价位", f"{float(row.get('距关键价位', 0.0)) * 100:+.2f}%")
                    focus_cols[3].metric("参考金额", "暂不交易" if pd.isna(row.get("参考交易金额")) else _format_money(row.get("参考交易金额")))
                    st.caption(str(row.get("触发依据", "")))
                    st.caption(str(row.get("计划说明", "")))
                if not focus_combo_df.empty:
                    st.dataframe(focus_combo_df[["到期日", "组合类型", "组合方向", "期权腿数", "行权价区间", "组合说明", "风险提示"]], width="stretch", hide_index=True)

        with st.expander("Cockpit 分区明细", expanded=True):
            risk_tab, option_tab, capital_tab, observe_tab = st.tabs(["风险持仓", "期权到期", "资金动作", "今日只观察"])
            with risk_tab:
                frame = cockpit_sections["risk_positions"]
                if frame.empty:
                    st.info("当前没有触发清仓/减仓，或贴近关键风控线的持仓。")
                else:
                    st.dataframe(frame, width="stretch", hide_index=True)
            with option_tab:
                frame = cockpit_sections["option_expiry"]
                if frame.empty:
                    st.info("未来 30 天内没有需要特别提醒的期权到期。")
                else:
                    st.dataframe(frame, width="stretch", hide_index=True)
            with capital_tab:
                frame = cockpit_sections["capital_actions"].copy()
                if frame.empty:
                    st.info("当前没有已触发动作对应的参考交易金额。")
                else:
                    frame["参考金额合计"] = frame["参考金额合计"].map(lambda value: f"${float(value):,.2f}")
                    st.dataframe(frame, width="stretch", hide_index=True)
            with observe_tab:
                frame = cockpit_sections["observe_only"]
                if frame.empty:
                    st.info("当前没有可归入只观察队列的标的。")
                else:
                    st.dataframe(frame, width="stretch", hide_index=True)

        snapshot_row = build_cockpit_snapshot_row(cockpit_metrics, cockpit_tasks_df, cockpit_sections, data_source=ctx.data_source, capital_source=ctx.capital_source, capital_value=float(ctx.capital_value), symbols=ctx.config.default_backtest_symbols, app_version=ctx.app_version)
        snapshot_col1, snapshot_col2 = st.columns(2)
        if snapshot_col1.button("保存 Cockpit 快照", width="stretch"):
            snapshots_df = ctx.append_cockpit_snapshot(snapshot_row)
            st.success(f"已保存 Cockpit 快照，共 {len(snapshots_df)} 条。")
        snapshots_df = ctx.load_cockpit_snapshots()
        if not snapshots_df.empty:
            snapshot_col2.download_button("下载 Cockpit 快照 CSV", data=_dataframe_to_csv_bytes(snapshots_df), file_name="cockpit_snapshots.csv", mime="text/csv", width="stretch")

        with st.expander("今日复盘", expanded=False):
            review_date = st.date_input("复盘日期", value=pd.Timestamp.today().date(), key="cockpit_review_date")
            review_summary = st.text_area("今日总结", key="cockpit_review_summary")
            review_done = st.text_area("已处理事项", key="cockpit_review_done")
            review_follow_up = st.text_area("待跟进事项", key="cockpit_review_follow_up")
            status_counts = edited_cockpit_tasks_df["状态"].value_counts() if "状态" in edited_cockpit_tasks_df.columns else pd.Series(dtype=int)
            review_col1, review_col2 = st.columns(2)
            if review_col1.button("保存今日复盘", width="stretch"):
                review_row = {
                    "复盘时间": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "复盘日期": str(review_date),
                    "应用版本": ctx.app_version,
                    "数据源": ctx.data_source,
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
                reviews_df = ctx.append_cockpit_review(review_row)
                st.success(f"已保存今日复盘，共 {len(reviews_df)} 条。")
            reviews_df = ctx.load_cockpit_reviews()
            if not reviews_df.empty:
                review_col2.download_button("下载 Cockpit 复盘 CSV", data=_dataframe_to_csv_bytes(reviews_df), file_name="cockpit_reviews.csv", mime="text/csv", width="stretch")
                trend_df = build_review_trend(reviews_df)
                if not trend_df.empty:
                    st.dataframe(trend_df, width="stretch", hide_index=True)
                weekly_summary_df = build_weekly_review_summary(reviews_df)
                if not weekly_summary_df.empty:
                    st.dataframe(weekly_summary_df.tail(8).sort_values("周开始", ascending=False), width="stretch", hide_index=True)

        with st.expander("真实账户检查清单", expanded=False):
            st.caption("用真实账户只读数据跑完页面后，在这里逐项记录是否正常。这里不会自动下单，也不会自动判断交易建议。")
            regression_date = st.date_input("检查日期", value=pd.Timestamp.today().date(), key="cockpit_regression_date")
            regression_default_df = build_regression_check_frame(
                REGRESSION_CHECK_ITEMS,
                data_source=ctx.data_source,
                position_count=_count_position_rows(ctx.edited_positions_df),
                stock_count=len(get_position_symbols(ctx.edited_positions_df)),
                option_count=len(ctx.option_position_symbols),
                has_account_info=bool(ctx.account_info),
                has_last_backtest="last_backtest" in st.session_state,
                strategy_plan_count=len(ctx.strategy_plan_df),
                cockpit_task_count=len(edited_cockpit_tasks_df),
                option_combo_count=len(ctx.option_combo_df),
            )
            st.caption("检查项会按当前页面状态预填；需要主观判断的项目仍建议人工复核。")
            edited_regression_df = st.data_editor(
                regression_default_df,
                width="stretch",
                hide_index=True,
                column_config={"检查项": st.column_config.TextColumn("检查项"), "结果": st.column_config.SelectboxColumn("结果", options=["未检查", "通过", "需复核", "失败"]), "备注": st.column_config.TextColumn("备注")},
                disabled=["检查项"],
                key="cockpit_regression_check_editor",
            )
            regression_col1, regression_col2 = st.columns(2)
            if regression_col1.button("保存检查清单", width="stretch"):
                rows = build_regression_check_rows(
                    edited_regression_df,
                    {
                        "检查日期": str(regression_date),
                        "应用版本": ctx.app_version,
                        "数据源": ctx.data_source,
                        "交易环境": ctx.position_env_label,
                        "持仓行数": len(ctx.edited_positions_df),
                        "期权行数": len(ctx.option_position_symbols),
                        "任务数": len(edited_cockpit_tasks_df),
                    },
                )
                regression_history_df = ctx.append_cockpit_regression(rows)
                st.success(f"已保存检查清单，共 {len(regression_history_df)} 条明细。")
            regression_history_df = ctx.load_cockpit_regressions()
            if not regression_history_df.empty:
                regression_col2.download_button("下载真实账户检查 CSV", data=_dataframe_to_csv_bytes(regression_history_df), file_name="cockpit_regression_checks.csv", mime="text/csv", width="stretch")
                summary = build_regression_check_summary(regression_history_df)
                summary_cols = st.columns(4)
                summary_cols[0].metric("最近检查项", int(summary["检查项"]))
                summary_cols[1].metric("通过", int(summary["通过"]))
                summary_cols[2].metric("需复核/失败", int(summary["需复核"]) + int(summary["失败"]))
                summary_cols[3].metric("通过率", _format_pct(float(summary["通过率"])))
                st.dataframe(regression_history_df.tail(30).sort_values("检查时间", ascending=False), width="stretch", hide_index=True)


def _render_today_tab(ctx: WorkspaceContext) -> None:
    """\U0001F4CB \u4eca\u65e5\u51b3\u7b56 tab\uff1amockup \u5bf9\u9f50\u7684 2 \u5217\u5e03\u5c40\uff1a\u5de6\u884c\u52a8\u5361 / \u53f3\u5355\u6807\u7684\u56fe\u8868\u3002"""
    _left_col, _right_col = st.columns([1.0, 1.15], gap="large")
    with _left_col:
        _render_today_actions(ctx)
    with _right_col:
        _render_single_symbol_chart(ctx)
        if not ctx.strategy_plan_df.empty:
            action_plan_frame = ctx.strategy_plan_df.drop(columns=["优先级排序"], errors="ignore")
            with st.expander("全部行动计划表", expanded=False):
                action_plan_display_df = _clean_display_frame(_select_existing_columns(action_plan_frame, ACTION_PLAN_DISPLAY_COLUMNS))
                st.dataframe(action_plan_display_df, width="stretch", hide_index=True)
            with st.expander("行动计划详情", expanded=False):
                detail_df = _clean_display_frame(_select_existing_columns(action_plan_frame, ACTION_PLAN_DETAIL_COLUMNS))
                st.dataframe(detail_df, width="stretch", hide_index=True)
            export_df = build_strategy_plan_export_frame(ctx.strategy_plan_df, config=ctx.config, data_source=ctx.data_source, equity_df=ctx.equity_df, capital_source=ctx.capital_source, capital_value=float(ctx.capital_value), position_source="当前持仓表" if ctx.current_positions else "回测模拟", app_version=ctx.app_version, account_info=ctx.account_info)
            st.download_button("下载今日行动计划 CSV", data=_dataframe_to_csv_bytes(export_df), file_name="strategy_action_plan.csv", mime="text/csv", width="stretch")


def _render_today_actions(ctx: WorkspaceContext) -> None:
    """\u5de6\u5217\uff1a\u4eca\u65e5\u884c\u52a8\u8ba1\u5212 + \u89c2\u5bdf\u6e05\u5355 + \u671f\u6743\u5173\u8054\u3002"""
    st.subheader("今日行动计划")
    if ctx.strategy_plan_df.empty:
        st.info("运行回测后会生成今日行动计划。")
    else:
        action_plan_frame = ctx.strategy_plan_df.drop(columns=["优先级排序"], errors="ignore")
        if "优先级排序" in ctx.strategy_plan_df.columns:
            _top_rows = ctx.strategy_plan_df.sort_values("优先级排序").head(5)
        else:
            _top_rows = ctx.strategy_plan_df.head(5)
        st.caption(f"今天只看这 {len(_top_rows)} 件事（按优先级排序）：")
        _action_palette = {
            "买入": ("#16A34A", "#DCFCE7"),
            "加仓": ("#15803D", "#D1FAE5"),
            "减仓": ("#D97706", "#FEF3C7"),
            "清仓": ("#DC2626", "#FEE2E2"),
            "观察": ("#2563EB", "#DBEAFE"),
        }
        _priority_palette = {
            "立即": ("#DC2626", "#FEE2E2"),
            "尽快": ("#D97706", "#FEF3C7"),
            "今日": ("#2563EB", "#DBEAFE"),
        }
        for _, _row in _top_rows.iterrows():
            _action_text = str(_row.get("计划动作", "—"))
            _fg, _bg = next(
                (color for key, color in _action_palette.items() if key in _action_text),
                ("#475569", "#E2E8F0"),
            )
            _priority_text = str(_row.get("优先级", "") or "—")
            _pfg, _pbg = next(
                (color for key, color in _priority_palette.items() if key in _priority_text),
                ("#475569", "#F1F5F9"),
            )
            _amt = _row.get("参考交易金额")
            _amt_text = "暂不交易" if (_amt is None or pd.isna(_amt)) else _format_money(_amt)
            _meta_bits = []
            _shares = _row.get("建议股数")
            if _shares is not None and pd.notna(_shares):
                _meta_bits.append(f"{int(_shares)} 股")
            _gap = _row.get("距关键价位")
            if _gap is not None and not pd.isna(_gap):
                _meta_bits.append(f"距关键价位 {float(_gap) * 100:+.2f}%")
            _status = _row.get("状态")
            if _status:
                _meta_bits.append(str(_status))
            _meta_text = " · ".join(_meta_bits) if _meta_bits else ""
            _trigger = str(_row.get("触发依据", "") or "")
            _plan_note = str(_row.get("计划说明", "") or "")

            _detail_lines = []
            if _trigger:
                _detail_lines.append(
                    f"<div style='color:#334155;font-size:0.95rem;margin-top:8px;line-height:1.5;'>"
                    f"<span style='color:#0F172A;font-weight:600;'>触发</span>：{_trigger}</div>"
                )
            if _plan_note:
                _detail_lines.append(
                    f"<div style='color:#64748B;font-size:0.9rem;margin-top:4px;line-height:1.5;'>{_plan_note}</div>"
                )
            _radar_row = _build_action_signal_radar_row(_row, ctx)
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style='border-left:5px solid {_pfg};padding-left:14px;'>
                        <div style='display:flex;align-items:center;flex-wrap:wrap;gap:12px;'>
                            <span style='background:{_bg};color:{_fg};padding:5px 14px;border-radius:999px;
                                         font-weight:700;font-size:0.95rem;letter-spacing:0.3px;'>{_action_text}</span>
                            <span style='font-size:1.4rem;font-weight:800;color:#0F172A;letter-spacing:-0.3px;'>{_row.get('标的', '')}</span>
                            <span style='background:{_pbg};color:{_pfg};padding:4px 12px;border-radius:7px;
                                         font-weight:700;font-size:0.9rem;'>{_priority_text}</span>
                            <span style='margin-left:auto;font-weight:800;font-size:1.5rem;color:#0F172A;letter-spacing:-0.3px;'>{_amt_text}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if _radar_row is None:
                    st.markdown(
                        f"""
                        {('<div style="color:#475569;font-size:0.98rem;line-height:1.5;font-weight:500;">' + _meta_text + '</div>') if _meta_text else ''}
                        {''.join(_detail_lines)}
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    _radar_col, _detail_col = st.columns([0.72, 1.35], gap="small")
                    with _radar_col:
                        _render_signal_radar(_radar_row, height=150)
                    with _detail_col:
                        _signal_labels = []
                        for _label in ["均线趋势", "价格突破", "成交量确认", "行业共振", "未过热"]:
                            _is_on = bool(_radar_row.get(_label))
                            _tag_bg = "#DCFCE7" if _is_on else "#F8FAFC"
                            _tag_fg = "#166534" if _is_on else "#64748B"
                            _tag_bd = "#BBF7D0" if _is_on else "#E2E8F0"
                            _signal_labels.append(f"<span style='background:{_tag_bg};color:{_tag_fg};border:1px solid {_tag_bd};border-radius:999px;padding:4px 9px;font-size:0.74rem;font-weight:800;white-space:nowrap;'>{_label}</span>")
                        st.markdown(
                            f"""
                            <div style='display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 8px;'>{''.join(_signal_labels)}</div>
                            {('<div style="color:#475569;font-size:0.95rem;line-height:1.5;font-weight:500;">' + _meta_text + '</div>') if _meta_text else ''}
                            {''.join(_detail_lines)}
                            """,
                            unsafe_allow_html=True,
                        )
        if len(ctx.strategy_plan_df) > len(_top_rows):
            st.caption(f"还有 {len(ctx.strategy_plan_df) - len(_top_rows)} 条次优先动作，展开右侧「全部行动计划表」查看。")

    if not ctx.watchlist_df.empty:
        with st.expander("策略观察清单", expanded=False):
            st.dataframe(ctx.watchlist_df, width="stretch", hide_index=True)

    if not ctx.watchlist_df.empty:
        if not ctx.option_overlay_df.empty:
            st.subheader("期权持仓关联")
            unmatched_option_legs_df = filter_unmatched_option_legs(ctx.option_overlay_df, ctx.option_combo_df)
            if not ctx.option_combo_df.empty:
                st.markdown("#### 期权组合识别")
                st.dataframe(ctx.option_combo_df, width="stretch", hide_index=True)
                st.download_button("下载期权组合识别 CSV", data=_dataframe_to_csv_bytes(ctx.option_combo_df), file_name="option_combo_summary.csv", mime="text/csv", width="stretch")
            else:
                st.info("当前没有识别出常见期权组合；可继续查看下方单腿关联明细。")
            st.markdown("#### 未归入组合的单腿关联")
            if unmatched_option_legs_df.empty:
                st.info("当前期权腿已全部归入上方组合识别，单腿区不重复展示。")
            else:
                st.dataframe(unmatched_option_legs_df, width="stretch", hide_index=True)
            st.download_button("下载全部期权单腿明细 CSV", data=_dataframe_to_csv_bytes(ctx.option_overlay_df), file_name="option_overlay_summary.csv", mime="text/csv", width="stretch")


def _render_archive_tab(ctx: WorkspaceContext) -> None:
    _archive_cards = [
        ("\u26a0\ufe0f", "\u98ce\u9669\u9884\u7b97\u660e\u7ec6", "FEF3C7", "B45309", "\u67e5\u770b\u6bcf\u6761\u8ba1\u5212\u5360\u7528\u7684\u8d44\u91d1 / \u540d\u4e49\u98ce\u9669\uff0c\u4e0e Cockpit tab \u540c\u6e90\u3002"),
        ("\U0001F4D3", "Cockpit \u590d\u76d8", "DCFCE7", "15803D", "\u4eca\u65e5\u590d\u76d8\u8bb0\u5f55\u4e0e\u5468\u5ea6\u8d8b\u52bf\uff0c\u5b58\u6863\u4e8e Cockpit tab \u2192 \u4eca\u65e5\u590d\u76d8\u3002"),
        ("\U0001F4CA", "\u56de\u6d4b\u5386\u53f2", "DBEAFE", "1D4ED8", "\u8fd1 20 \u6b21\u56de\u6d4b\u7ed3\u679c\u5b58\u6863\u4e8e\u5de6\u4fa7\U0001F680 \u8fd0\u884c\u9762\u677f \u2192 \u56de\u6d4b\u5386\u53f2\u3002"),
        ("\U0001F9E9", "\u671f\u6743\u7ec4\u5408\u5f52\u6863", "EDE9FE", "6D28D9", "\u5df2\u8bc6\u522b\u7684\u5e38\u89c1\u671f\u6743\u7ec4\u5408\u660e\u7ec6\uff0c\u8be6\u89c1 \u4eca\u65e5\u51b3\u7b56 tab \u2192 \u671f\u6743\u6301\u4ed3\u5173\u8054\u3002"),
        ("\u2705", "\u771f\u5b9e\u8d26\u6237\u68c0\u67e5", "FEE2E2", "B91C1C", "\u771f\u5b9e\u8d26\u6237\u6bcf\u65e5\u68c0\u67e5\u6e05\u5355\u4e0e\u901a\u8fc7\u7387\u7edf\u8ba1\uff0c\u8be6\u89c1 Cockpit tab\u3002"),
        ("\U0001F50D", "\u5355\u6807\u7684\u7814\u7a76", "E0F2FE", "0369A1", "\u5355\u6807\u7684\u56fe\u8868\u4e0e\u8fd1\u671f\u4fe1\u53f7\u8be6\u60c5\uff0c\u8be6\u89c1 \u4eca\u65e5\u51b3\u7b56 tab \u672b\u5c3e\u3002"),
    ]
    _cards_html = ""
    for icon, title, bg, fg, desc in _archive_cards:
        _cards_html += (
            f"<div class='archive-card'>"
            f"<span class='ic' style='background:#{bg};color:#{fg};'>{icon}</span>"
            f"<div class='body'><div class='t'>{title}</div><div class='s'>{desc}</div></div>"
            f"<span class='chev'>\u203a</span>"
            f"</div>"
        )
    _archive_html = (
        "<div class='archive-section'>"
        "<div class='arc-title'>"
        f"<h3>\U0001F4DC \u590d\u76d8\u6863\u6848</h3>"
        f"<span class='arc-badge'>{len(_archive_cards)}</span>"
        f"<span class='arc-tip'>\u6863\u6848\u6027\u89c6\u56fe\u96c6\u4e2d\u5165\u53e3\uff1bV0.6 \u6570\u636e\u4ecd\u5728 Cockpit / \u4eca\u65e5\u51b3\u7b56 tab \u4e2d\u3002</span>"
        "</div>"
        f"<div class='archive-grid'>{_cards_html}</div>"
        "</div>"
    )
    st.markdown(_archive_html, unsafe_allow_html=True)
