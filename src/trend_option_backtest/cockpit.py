from __future__ import annotations

import pandas as pd


def _format_optional_money(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"${float(value):,.2f}"


def _format_optional_pct(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value) * 100:+.2f}%"


def _is_triggered_action(row: pd.Series) -> bool:
    action = str(row.get("计划动作", ""))
    if action not in {"建仓", "加仓", "减仓", "清仓"}:
        return False
    amount = row.get("参考交易金额")
    return amount is not None and not pd.isna(amount) and float(amount) > 0


def _is_near_trigger(row: pd.Series, threshold: float) -> bool:
    action = str(row.get("计划动作", ""))
    if action not in {"等待触发", "等待"}:
        return False
    distance = row.get("距关键价位")
    return distance is not None and not pd.isna(distance) and abs(float(distance)) <= threshold


def _is_option_attention(row: pd.Series, expiry_days_threshold: int) -> bool:
    role = str(row.get("Overlay角色", ""))
    coverage_label = str(row.get("覆盖口径", ""))
    days_to_expiry = row.get("到期天数")
    coverage_ratio = row.get("覆盖/保护比例")
    if "风险敞口" in role or "无正股" in coverage_label or "无对应正股" in coverage_label:
        return True
    if days_to_expiry is not None and not pd.isna(days_to_expiry) and int(days_to_expiry) <= expiry_days_threshold:
        return True
    if coverage_label == "备兑覆盖比例" and coverage_ratio is not None and not pd.isna(coverage_ratio):
        return float(coverage_ratio) < 1
    return False


def build_cockpit_overview(
    strategy_plan_df: pd.DataFrame,
    option_overlay_df: pd.DataFrame,
    *,
    near_trigger_threshold: float = 0.03,
    option_expiry_days_threshold: int = 30,
) -> tuple[dict[str, int], pd.DataFrame]:
    metrics = {
        "当前动作": 0,
        "降低风险": 0,
        "接近触发": 0,
        "期权关注": 0,
    }
    task_rows: list[dict[str, object]] = []

    if not strategy_plan_df.empty:
        for _, row in strategy_plan_df.iterrows():
            symbol = str(row.get("标的", ""))
            action = str(row.get("计划动作", ""))
            priority = str(row.get("优先级", ""))
            if _is_triggered_action(row):
                metrics["当前动作"] += 1
                if action in {"清仓", "减仓"}:
                    metrics["降低风险"] += 1
                task_rows.append(
                    {
                        "类别": "当前动作",
                        "标的": symbol,
                        "动作": action,
                        "优先级": priority,
                        "依据": str(row.get("触发依据", "")),
                        "资金/仓位": _format_optional_money(row.get("参考交易金额")),
                    }
                )
            elif _is_near_trigger(row, near_trigger_threshold):
                metrics["接近触发"] += 1
                task_rows.append(
                    {
                        "类别": "接近触发",
                        "标的": symbol,
                        "动作": action,
                        "优先级": priority,
                        "依据": str(row.get("触发依据", "")),
                        "资金/仓位": str(row.get("金额说明", "")),
                    }
                )

    if not option_overlay_df.empty:
        for _, row in option_overlay_df.iterrows():
            if not _is_option_attention(row, option_expiry_days_threshold):
                continue
            metrics["期权关注"] += 1
            task_rows.append(
                {
                    "类别": "期权关注",
                    "标的": str(row.get("期权代码", "")),
                    "动作": str(row.get("Overlay角色", "")),
                    "优先级": str(row.get("正股优先级", "")),
                    "依据": str(row.get("风险提示", "")),
                    "资金/仓位": str(row.get("覆盖口径", "")),
                }
            )

    task_df = pd.DataFrame(task_rows, columns=["类别", "标的", "动作", "优先级", "依据", "资金/仓位"])
    if task_df.empty:
        return metrics, task_df
    category_rank = {"当前动作": 1, "期权关注": 2, "接近触发": 3}
    task_df["_rank"] = task_df["类别"].map(lambda value: category_rank.get(str(value), 9))
    return metrics, task_df.sort_values(["_rank", "标的"]).drop(columns=["_rank"]).reset_index(drop=True)


def build_cockpit_sections(
    strategy_plan_df: pd.DataFrame,
    option_overlay_df: pd.DataFrame,
    *,
    risk_distance_threshold: float = 0.05,
    option_expiry_days_threshold: int = 30,
) -> dict[str, pd.DataFrame]:
    risk_rows: list[dict[str, object]] = []
    capital_rows: list[dict[str, object]] = []
    expiry_rows: list[dict[str, object]] = []
    observe_rows: list[dict[str, object]] = []

    if not strategy_plan_df.empty:
        triggered_actions = strategy_plan_df[strategy_plan_df.apply(_is_triggered_action, axis=1)].copy()
        if not triggered_actions.empty:
            for action, group in triggered_actions.groupby("计划动作", sort=False):
                capital_rows.append(
                    {
                        "动作": str(action),
                        "标的数": int(len(group)),
                        "参考金额合计": float(group["参考交易金额"].fillna(0.0).sum()),
                    }
                )

        for _, row in strategy_plan_df.iterrows():
            status = str(row.get("状态", ""))
            action = str(row.get("计划动作", ""))
            distance = row.get("距关键价位")
            near_risk_line = status == "持仓" and distance is not None and not pd.isna(distance) and float(distance) <= risk_distance_threshold
            if action in {"继续持仓", "等待触发", "等待"} and not _is_near_trigger(row, risk_distance_threshold) and not near_risk_line:
                observe_rows.append(
                    {
                        "标的": str(row.get("标的", "")),
                        "状态": status,
                        "计划动作": action,
                        "距关键价位": _format_optional_pct(distance),
                        "下一步关注": str(row.get("触发依据", "")),
                    }
                )
            if status != "持仓":
                continue
            if action not in {"清仓", "减仓"} and not near_risk_line:
                continue
            if action == "清仓":
                risk_level = "高"
            elif action == "减仓":
                risk_level = "中"
            else:
                risk_level = "观察"
            risk_rows.append(
                {
                    "标的": str(row.get("标的", "")),
                    "风险等级": risk_level,
                    "计划动作": action,
                    "距关键价位": _format_optional_pct(distance),
                    "风控关注": str(row.get("风控关注", "")),
                    "下一步": str(row.get("计划说明", row.get("触发依据", ""))),
                }
            )

    if not option_overlay_df.empty:
        for _, row in option_overlay_df.iterrows():
            days_to_expiry = row.get("到期天数")
            if days_to_expiry is None or pd.isna(days_to_expiry) or int(days_to_expiry) > option_expiry_days_threshold:
                continue
            expiry_rows.append(
                {
                    "期权代码": str(row.get("期权代码", "")),
                    "正股标的": str(row.get("正股标的", "")),
                    "到期天数": int(days_to_expiry),
                    "Overlay角色": str(row.get("Overlay角色", "")),
                    "覆盖口径": str(row.get("覆盖口径", "")),
                    "风险提示": str(row.get("风险提示", "")),
                }
            )

    risk_df = pd.DataFrame(risk_rows, columns=["标的", "风险等级", "计划动作", "距关键价位", "风控关注", "下一步"])
    capital_df = pd.DataFrame(capital_rows, columns=["动作", "标的数", "参考金额合计"])
    expiry_df = pd.DataFrame(expiry_rows, columns=["期权代码", "正股标的", "到期天数", "Overlay角色", "覆盖口径", "风险提示"])
    observe_df = pd.DataFrame(observe_rows, columns=["标的", "状态", "计划动作", "距关键价位", "下一步关注"])
    if not risk_df.empty:
        risk_rank = {"高": 1, "中": 2, "观察": 3}
        risk_df["_rank"] = risk_df["风险等级"].map(lambda value: risk_rank.get(str(value), 9))
        risk_df = risk_df.sort_values(["_rank", "标的"]).drop(columns=["_rank"]).reset_index(drop=True)
    if not expiry_df.empty:
        expiry_df = expiry_df.sort_values(["到期天数", "期权代码"]).reset_index(drop=True)
    if not observe_df.empty:
        observe_df = observe_df.sort_values(["状态", "标的"]).reset_index(drop=True)
    return {
        "risk_positions": risk_df,
        "option_expiry": expiry_df,
        "capital_actions": capital_df,
        "observe_only": observe_df,
    }


def build_cockpit_snapshot_row(
    metrics: dict[str, int],
    tasks_df: pd.DataFrame,
    sections: dict[str, pd.DataFrame],
    *,
    data_source: str,
    capital_source: str,
    capital_value: float,
    symbols: list[str],
    app_version: str,
    created_at: pd.Timestamp | None = None,
) -> dict[str, object]:
    timestamp = created_at or pd.Timestamp.now()
    capital_actions_df = sections.get("capital_actions", pd.DataFrame())
    triggered_amount = 0.0
    if not capital_actions_df.empty and "参考金额合计" in capital_actions_df.columns:
        triggered_amount = float(pd.to_numeric(capital_actions_df["参考金额合计"], errors="coerce").fillna(0.0).sum())
    return {
        "快照时间": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "应用版本": app_version,
        "数据源": data_source,
        "参与标的": ",".join(symbols),
        "资金来源": capital_source,
        "计划资金基准": float(capital_value),
        "当前动作": int(metrics.get("当前动作", 0)),
        "降低风险": int(metrics.get("降低风险", 0)),
        "接近触发": int(metrics.get("接近触发", 0)),
        "期权关注": int(metrics.get("期权关注", 0)),
        "今日任务数": int(len(tasks_df)),
        "风险持仓数": int(len(sections.get("risk_positions", pd.DataFrame()))),
        "期权到期数": int(len(sections.get("option_expiry", pd.DataFrame()))),
        "只观察数": int(len(sections.get("observe_only", pd.DataFrame()))),
        "已触发参考金额": triggered_amount,
    }


def build_cockpit_risk_budget(
    strategy_plan_df: pd.DataFrame,
    option_overlay_df: pd.DataFrame,
    *,
    capital_value: float,
) -> dict[str, float]:
    increase_actions = {"建仓", "加仓"}
    decrease_actions = {"减仓", "清仓"}
    increase_amount = 0.0
    decrease_amount = 0.0
    if not strategy_plan_df.empty:
        triggered = strategy_plan_df[strategy_plan_df.apply(_is_triggered_action, axis=1)].copy()
        if not triggered.empty:
            amounts = pd.to_numeric(triggered["参考交易金额"], errors="coerce").fillna(0.0)
            actions = triggered["计划动作"].map(str)
            increase_amount = float(amounts[actions.isin(increase_actions)].sum())
            decrease_amount = float(amounts[actions.isin(decrease_actions)].sum())

    potential_assignment = 0.0
    uncovered_short_call_count = 0.0
    if not option_overlay_df.empty:
        for _, row in option_overlay_df.iterrows():
            option_type = str(row.get("期权类型", ""))
            direction = str(row.get("持仓方向", ""))
            contract_shares = row.get("合约对应股数", 0.0)
            strike = row.get("行权价", 0.0)
            if option_type == "Put" and direction == "空头":
                potential_assignment += float(contract_shares or 0.0) * float(strike or 0.0)
            coverage_label = str(row.get("覆盖口径", ""))
            coverage_ratio = row.get("覆盖/保护比例")
            if option_type == "Call" and direction == "空头" and coverage_label == "备兑覆盖比例":
                if coverage_ratio is None or pd.isna(coverage_ratio) or float(coverage_ratio) < 1:
                    uncovered_short_call_count += 1

    net_change = increase_amount - decrease_amount
    gross_action_amount = increase_amount + decrease_amount
    capital_base = float(capital_value) if capital_value and capital_value > 0 else 0.0
    return {
        "增风险金额": increase_amount,
        "降风险金额": decrease_amount,
        "净风险变化": net_change,
        "今日动作资金占比": gross_action_amount / capital_base if capital_base else 0.0,
        "潜在接股金额": potential_assignment,
        "未充分备兑Call数": uncovered_short_call_count,
    }


def build_review_trend(reviews_df: pd.DataFrame) -> pd.DataFrame:
    if reviews_df.empty:
        return pd.DataFrame(columns=["复盘日期", "任务数", "已处理", "完成率", "未完成"])
    required_columns = {"复盘日期", "任务数", "已处理"}
    if not required_columns.issubset(reviews_df.columns):
        return pd.DataFrame(columns=["复盘日期", "任务数", "已处理", "完成率", "未完成"])

    trend_df = reviews_df.copy()
    trend_df["复盘日期"] = pd.to_datetime(trend_df["复盘日期"], errors="coerce")
    trend_df["任务数"] = pd.to_numeric(trend_df["任务数"], errors="coerce").fillna(0).astype(int)
    trend_df["已处理"] = pd.to_numeric(trend_df["已处理"], errors="coerce").fillna(0).astype(int)
    if "复盘时间" in trend_df.columns:
        trend_df["复盘时间"] = pd.to_datetime(trend_df["复盘时间"], errors="coerce")
        trend_df = trend_df.sort_values(["复盘日期", "复盘时间"])
    trend_df = trend_df.dropna(subset=["复盘日期"]).groupby("复盘日期", as_index=False).tail(1)
    trend_df["完成率"] = trend_df.apply(lambda row: float(row["已处理"]) / float(row["任务数"]) if row["任务数"] else 1.0, axis=1)
    trend_df["未完成"] = (trend_df["任务数"] - trend_df["已处理"]).clip(lower=0)
    return trend_df[["复盘日期", "任务数", "已处理", "完成率", "未完成"]].reset_index(drop=True)


def build_weekly_review_summary(reviews_df: pd.DataFrame) -> pd.DataFrame:
    trend_df = build_review_trend(reviews_df)
    if trend_df.empty:
        return pd.DataFrame(columns=["周开始", "周结束", "复盘天数", "任务数", "已处理", "未完成", "平均完成率", "净风险变化"])

    weekly_df = trend_df.copy()
    weekly_df["周开始"] = weekly_df["复盘日期"] - pd.to_timedelta(weekly_df["复盘日期"].dt.weekday, unit="D")
    weekly_df["周结束"] = weekly_df["周开始"] + pd.Timedelta(days=6)

    net_risk_by_day = pd.DataFrame(columns=["复盘日期", "净风险变化"])
    if "净风险变化" in reviews_df.columns:
        net_risk_df = reviews_df.copy()
        net_risk_df["复盘日期"] = pd.to_datetime(net_risk_df["复盘日期"], errors="coerce")
        net_risk_df["净风险变化"] = pd.to_numeric(net_risk_df["净风险变化"], errors="coerce").fillna(0.0)
        if "复盘时间" in net_risk_df.columns:
            net_risk_df["复盘时间"] = pd.to_datetime(net_risk_df["复盘时间"], errors="coerce")
            net_risk_df = net_risk_df.sort_values(["复盘日期", "复盘时间"])
        net_risk_by_day = net_risk_df.dropna(subset=["复盘日期"]).groupby("复盘日期", as_index=False).tail(1)[["复盘日期", "净风险变化"]]

    weekly_df = weekly_df.merge(net_risk_by_day, on="复盘日期", how="left")
    weekly_df["净风险变化"] = weekly_df["净风险变化"].fillna(0.0)
    summary_df = (
        weekly_df.groupby(["周开始", "周结束"], as_index=False)
        .agg(
            复盘天数=("复盘日期", "count"),
            任务数=("任务数", "sum"),
            已处理=("已处理", "sum"),
            未完成=("未完成", "sum"),
            平均完成率=("完成率", "mean"),
            净风险变化=("净风险变化", "sum"),
        )
        .sort_values("周开始")
        .reset_index(drop=True)
    )
    return summary_df[["周开始", "周结束", "复盘天数", "任务数", "已处理", "未完成", "平均完成率", "净风险变化"]]


def build_regression_check_rows(
    checks_df: pd.DataFrame,
    metadata: dict[str, object],
    *,
    created_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    columns = ["检查时间", "检查日期", "应用版本", "数据源", "交易环境", "持仓行数", "期权行数", "任务数", "检查项", "结果", "备注"]
    if checks_df.empty:
        return pd.DataFrame(columns=columns)
    timestamp = created_at or pd.Timestamp.now()
    rows: list[dict[str, object]] = []
    for _, row in checks_df.iterrows():
        item = str(row.get("检查项", "")).strip()
        if not item:
            continue
        raw_result = row.get("结果", "未检查")
        result = "未检查" if pd.isna(raw_result) else str(raw_result).strip() or "未检查"
        raw_note = row.get("备注", "")
        note = "" if pd.isna(raw_note) else str(raw_note)
        rows.append(
            {
                "检查时间": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "检查日期": str(metadata.get("检查日期", timestamp.date())),
                "应用版本": str(metadata.get("应用版本", "")),
                "数据源": str(metadata.get("数据源", "")),
                "交易环境": str(metadata.get("交易环境", "")),
                "持仓行数": int(metadata.get("持仓行数", 0) or 0),
                "期权行数": int(metadata.get("期权行数", 0) or 0),
                "任务数": int(metadata.get("任务数", 0) or 0),
                "检查项": item,
                "结果": result,
                "备注": note,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_regression_check_summary(regression_rows_df: pd.DataFrame) -> dict[str, float | int | str]:
    summary: dict[str, float | int | str] = {
        "检查时间": "",
        "检查项": 0,
        "通过": 0,
        "需复核": 0,
        "失败": 0,
        "未检查": 0,
        "通过率": 1.0,
    }
    if regression_rows_df.empty or "检查时间" not in regression_rows_df.columns or "结果" not in regression_rows_df.columns:
        return summary
    checks_df = regression_rows_df.copy()
    checks_df["_检查时间"] = pd.to_datetime(checks_df["检查时间"], errors="coerce")
    checks_df = checks_df.dropna(subset=["_检查时间"])
    if checks_df.empty:
        return summary
    latest_time = checks_df["_检查时间"].max()
    latest_df = checks_df[checks_df["_检查时间"] == latest_time]
    result_counts = latest_df["结果"].map(str).value_counts()
    total = int(len(latest_df))
    passed = int(result_counts.get("通过", 0))
    summary.update(
        {
            "检查时间": latest_time.strftime("%Y-%m-%d %H:%M:%S"),
            "检查项": total,
            "通过": passed,
            "需复核": int(result_counts.get("需复核", 0)),
            "失败": int(result_counts.get("失败", 0)),
            "未检查": int(result_counts.get("未检查", 0)),
            "通过率": passed / total if total else 1.0,
        }
    )
    return summary
