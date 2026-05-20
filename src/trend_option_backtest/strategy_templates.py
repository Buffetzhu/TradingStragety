from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyTemplate:
    key: str
    label: str
    strategy_name: str
    description: str
    overrides: dict[str, Any]


STRATEGY_TEMPLATES: dict[str, StrategyTemplate] = {
    "gpt_default": StrategyTemplate(
        key="gpt_default",
        label="GPT 趋势默认",
        strategy_name="GPT_Trend_Default_v1",
        description="均衡趋势模板，适合作为默认基准。",
        overrides={},
    ),
    "steady_trend": StrategyTemplate(
        key="steady_trend",
        label="稳健趋势",
        strategy_name="Steady_Trend_v1",
        description="更慢确认、更小仓位，减少频繁动作。",
        overrides={
            "ma_short": 30,
            "ma_long": 80,
            "breakout_days": 40,
            "volume_multiplier": 1.5,
            "overheat_distance": 0.12,
            "entry_position_pct": 0.35,
            "add_position_pct": 0.15,
            "reduce_position_pct": 0.5,
            "use_sector_filter": True,
        },
    ),
    "aggressive_breakout": StrategyTemplate(
        key="aggressive_breakout",
        label="激进突破",
        strategy_name="Aggressive_Breakout_v1",
        description="更快响应突破，仓位推进更积极。",
        overrides={
            "ma_short": 10,
            "ma_long": 30,
            "breakout_days": 15,
            "volume_multiplier": 1.1,
            "overheat_distance": 0.22,
            "entry_position_pct": 0.6,
            "add_position_pct": 0.3,
            "reduce_position_pct": 0.35,
            "use_sector_filter": False,
        },
    ),
    "defensive_watch": StrategyTemplate(
        key="defensive_watch",
        label="防守观察",
        strategy_name="Defensive_Watch_v1",
        description="更重视风控和观察，降低新增风险。",
        overrides={
            "ma_short": 20,
            "ma_long": 100,
            "breakout_days": 60,
            "volume_multiplier": 1.8,
            "overheat_distance": 0.08,
            "entry_position_pct": 0.25,
            "add_position_pct": 0.1,
            "reduce_position_pct": 0.75,
            "use_sector_filter": True,
        },
    ),
}


TEMPLATE_LABEL_TO_KEY = {template.label: key for key, template in STRATEGY_TEMPLATES.items()}
TEMPLATE_PARAM_LABELS = {
    "ma_short": "MA 短周期",
    "ma_long": "MA 长周期",
    "breakout_days": "突破新高回溯天数",
    "volume_multiplier": "成交量倍数",
    "overheat_distance": "过热距离 MA 短线",
    "entry_position_pct": "首次建仓比例",
    "add_position_pct": "单次加仓比例",
    "reduce_position_pct": "单次减仓比例",
    "use_sector_filter": "SOXX 板块共振过滤",
}
PERCENT_PARAMS = {"overheat_distance", "entry_position_pct", "add_position_pct", "reduce_position_pct"}


def format_template_param_value(param_key: str, value: Any) -> str:
    if value is None:
        return "未设置"
    if isinstance(value, bool):
        return "启用" if value else "关闭"
    if param_key in PERCENT_PARAMS:
        return f"{float(value) * 100:g}%"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def get_template_label(payload: dict[str, Any]) -> str:
    strategy_name = str(payload.get("strategy_name", ""))
    for template in STRATEGY_TEMPLATES.values():
        if template.strategy_name == strategy_name:
            return template.label
    return "自定义参数"


def apply_strategy_template(base_payload: dict[str, Any], template_key: str) -> dict[str, Any]:
    template = STRATEGY_TEMPLATES[template_key]
    updated_payload = base_payload.copy()
    updated_payload.update(template.overrides)
    updated_payload["strategy_name"] = template.strategy_name
    return updated_payload


def build_template_diff_rows(current_payload: dict[str, Any], template_key: str) -> list[dict[str, str]]:
    template = STRATEGY_TEMPLATES[template_key]
    rows: list[dict[str, str]] = []
    for param_key, template_value in template.overrides.items():
        current_value = current_payload.get(param_key)
        if current_value == template_value:
            continue
        rows.append(
            {
                "参数": TEMPLATE_PARAM_LABELS.get(param_key, param_key),
                "当前值": format_template_param_value(param_key, current_value),
                "模板值": format_template_param_value(param_key, template_value),
            }
        )
    return rows
