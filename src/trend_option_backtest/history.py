from __future__ import annotations

import pandas as pd


HISTORY_TEMPLATE_COLUMN = "策略模板"
UNKNOWN_TEMPLATE_LABEL = "未记录模板"


def normalize_backtest_history_frame(history_rows: list[dict]) -> pd.DataFrame:
    if not history_rows:
        return pd.DataFrame()
    frame = pd.DataFrame(history_rows).copy()
    if HISTORY_TEMPLATE_COLUMN not in frame.columns:
        frame[HISTORY_TEMPLATE_COLUMN] = UNKNOWN_TEMPLATE_LABEL
    frame[HISTORY_TEMPLATE_COLUMN] = frame[HISTORY_TEMPLATE_COLUMN].fillna(UNKNOWN_TEMPLATE_LABEL).map(str)
    frame.loc[frame[HISTORY_TEMPLATE_COLUMN].str.strip() == "", HISTORY_TEMPLATE_COLUMN] = UNKNOWN_TEMPLATE_LABEL
    return frame


def build_template_history_summary(history_rows: list[dict]) -> pd.DataFrame:
    frame = normalize_backtest_history_frame(history_rows)
    columns = ["策略模板", "回测次数", "最近运行", "平均收益率", "最好收益率", "最差回撤", "平均Sharpe", "平均交易动作"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    numeric_columns = ["总收益率", "最大回撤", "Sharpe", "交易动作"]
    for column in numeric_columns:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "运行时间" not in frame.columns:
        frame["运行时间"] = ""

    grouped = (
        frame.groupby(HISTORY_TEMPLATE_COLUMN, dropna=False)
        .agg(
            回测次数=(HISTORY_TEMPLATE_COLUMN, "size"),
            最近运行=("运行时间", "max"),
            平均收益率=("总收益率", "mean"),
            最好收益率=("总收益率", "max"),
            最差回撤=("最大回撤", "min"),
            平均Sharpe=("Sharpe", "mean"),
            平均交易动作=("交易动作", "mean"),
        )
        .reset_index()
        .rename(columns={HISTORY_TEMPLATE_COLUMN: "策略模板"})
        .sort_values(["平均收益率", "平均Sharpe"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return grouped[columns]


def filter_history_by_templates(history_rows: list[dict], selected_templates: list[str]) -> pd.DataFrame:
    frame = normalize_backtest_history_frame(history_rows)
    if frame.empty or not selected_templates:
        return frame
    selected = {str(template) for template in selected_templates}
    return frame[frame[HISTORY_TEMPLATE_COLUMN].isin(selected)].reset_index(drop=True)
