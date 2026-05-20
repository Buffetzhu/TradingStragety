"""双工作区渲染：模拟研究 / 账户追踪。

把 app.py 中两个 render 函数搬到独立模块，避免单文件超长；
通过 WorkspaceContext 注入所有数据与持久化回调，保持与 Streamlit 解耦。
"""

from __future__ import annotations

from dataclasses import dataclass
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
)
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
        height=360,
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
    """账户追踪工作区：账户快照 + Cockpit + 行动计划 + 期权关联 + 单标的图。"""
    st.subheader("账户快照")
    _snap_cols = st.columns(4)
    _snap_cols[0].metric("总资产", _format_money(ctx.account_info.get("total_assets")) if ctx.account_info else "未读取")
    _snap_cols[1].metric("现金", _format_money(ctx.account_info.get("cash")) if ctx.account_info else "未读取")
    _snap_cols[2].metric("购买力", _format_money(ctx.account_info.get("buying_power")) if ctx.account_info else "未读取")
    _stock_rows = int(_count_position_rows(ctx.edited_positions_df))
    _option_rows = len(ctx.option_position_symbols)
    _snap_cols[3].metric("持仓条目", f"{_stock_rows} 正股/ETF · {_option_rows} 期权")
    if not ctx.account_info:
        st.caption("还没读取过账户资金。可点击上方“🔄 一键刷新持仓 + 重跑今日策略”，或到左侧栏“当前持仓与账户资金”里点“读取账户资金”。")
    else:
        st.caption(f"账户环境：{ctx.position_env_label}。资金口径来自富途 OpenAPI，仅做读取，不会下单。")

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
        for _, _row in _top_rows.iterrows():
            with st.container(border=True):
                _action_text = str(_row.get("计划动作", "—"))
                _fg, _bg = next(
                    (color for key, color in _action_palette.items() if key in _action_text),
                    ("#475569", "#E2E8F0"),
                )
                _head_c1, _head_c2, _head_c3 = st.columns([3, 1, 1])
                _head_c1.markdown(
                    f"""
                    <div style='display:flex;align-items:center;gap:10px;margin-bottom:2px;'>
                        <span style='background:{_bg};color:{_fg};padding:3px 12px;border-radius:999px;
                                     font-weight:700;font-size:0.82rem;letter-spacing:0.3px;'>{_action_text}</span>
                        <span style='font-size:1.1rem;font-weight:700;color:#0F172A;'>{_row.get('标的', '')}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                _head_c2.metric("优先级", str(_row.get("优先级", "")))
                _amt = _row.get("参考交易金额")
                _head_c3.metric("参考金额", "暂不交易" if pd.isna(_amt) else _format_money(_amt))
                _meta_bits = []
                _shares = _row.get("建议股数")
                if pd.notna(_shares):
                    _meta_bits.append(f"建议股数：{int(_shares)}")
                _gap = _row.get("距关键价位")
                if _gap is not None and not pd.isna(_gap):
                    _meta_bits.append(f"距关键价位：{float(_gap) * 100:+.2f}%")
                _status = _row.get("状态")
                if _status:
                    _meta_bits.append(f"状态：{_status}")
                if _meta_bits:
                    st.caption(" ｜ ".join(_meta_bits))
                _trigger = str(_row.get("触发依据", "") or "")
                if _trigger:
                    st.markdown(f"**触发依据**：{_trigger}")
                _plan_note = str(_row.get("计划说明", "") or "")
                if _plan_note:
                    st.caption(f"说明：{_plan_note}")
        if len(ctx.strategy_plan_df) > len(_top_rows):
            st.caption(f"还有 {len(ctx.strategy_plan_df) - len(_top_rows)} 条次优先动作，展开下方表格查看。")
        with st.expander("全部行动计划表", expanded=False):
            action_plan_display_df = _clean_display_frame(_select_existing_columns(action_plan_frame, ACTION_PLAN_DISPLAY_COLUMNS))
            st.dataframe(action_plan_display_df, width="stretch", hide_index=True)
        with st.expander("行动计划详情", expanded=False):
            detail_df = _clean_display_frame(_select_existing_columns(action_plan_frame, ACTION_PLAN_DETAIL_COLUMNS))
            st.dataframe(detail_df, width="stretch", hide_index=True)
        export_df = build_strategy_plan_export_frame(ctx.strategy_plan_df, config=ctx.config, data_source=ctx.data_source, equity_df=ctx.equity_df, capital_source=ctx.capital_source, capital_value=float(ctx.capital_value), position_source="当前持仓表" if ctx.current_positions else "回测模拟", app_version=ctx.app_version, account_info=ctx.account_info)
        st.download_button("下载今日行动计划 CSV", data=_dataframe_to_csv_bytes(export_df), file_name="strategy_action_plan.csv", mime="text/csv", width="stretch")

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

    _render_single_symbol_chart(ctx)
