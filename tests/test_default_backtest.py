from pathlib import Path
import sys
import types

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trend_option_backtest.demo_data import make_demo_market_data
from trend_option_backtest.backtest import BacktestEngine
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
from trend_option_backtest.history import build_template_history_summary, filter_history_by_templates, normalize_backtest_history_frame
from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.planning import (
    build_option_combo_summary,
    build_option_overlay_summary,
    build_position_editor_frame,
    filter_unmatched_option_legs,
    get_option_position_symbols,
    get_position_symbols,
)
from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider, normalize_symbol
from trend_option_backtest.services.backtest_service import BacktestService
from trend_option_backtest.strategy_templates import STRATEGY_TEMPLATES, apply_strategy_template, build_template_diff_rows, get_template_label


class FakeFutuTradeContext:
    position_ret = 0
    position_data = pd.DataFrame()
    account_ret = 0
    account_data = pd.DataFrame()
    position_query_args: dict[str, object] = {}
    account_query_args: dict[str, object] = {}
    close_count = 0

    def __init__(self, *, filter_trdmarket, host, port):
        self.filter_trdmarket = filter_trdmarket
        self.host = host
        self.port = port

    def position_list_query(self, **query_args):
        FakeFutuTradeContext.position_query_args = query_args
        return FakeFutuTradeContext.position_ret, FakeFutuTradeContext.position_data

    def accinfo_query(self, **query_args):
        FakeFutuTradeContext.account_query_args = query_args
        return FakeFutuTradeContext.account_ret, FakeFutuTradeContext.account_data

    def close(self):
        FakeFutuTradeContext.close_count += 1


def install_fake_futu_module(monkeypatch):
    FakeFutuTradeContext.position_data = pd.DataFrame()
    FakeFutuTradeContext.position_ret = 0
    FakeFutuTradeContext.account_data = pd.DataFrame()
    FakeFutuTradeContext.account_ret = 0
    FakeFutuTradeContext.position_query_args = {}
    FakeFutuTradeContext.account_query_args = {}
    FakeFutuTradeContext.close_count = 0
    fake_module = types.SimpleNamespace(
        OpenSecTradeContext=FakeFutuTradeContext,
        RET_OK=0,
        TrdEnv=types.SimpleNamespace(SIMULATE="SIMULATE", REAL="REAL"),
        TrdMarket=types.SimpleNamespace(US="US", HK="HK", HKCC="HKCC", CN="CN", SG="SG"),
    )
    monkeypatch.setitem(sys.modules, "futu", fake_module)


def test_default_demo_backtest_runs():
    config = StrategyConfig.from_json(ROOT / "config" / "default_config.json")
    assert config.backtest_years == 0.5
    market_data = make_demo_market_data(
        config.default_backtest_symbols,
        sector_symbol=config.sector_symbol,
        years=config.backtest_years,
        warmup_days=config.indicator_warmup_days,
    )
    result = BacktestService(config).run(market_data)

    assert result.metrics["trade_count"] >= 0
    assert "total_return" in result.metrics
    assert result.equity_curve
    assert result.symbol_equity_curve
    symbol_equity_df = pd.DataFrame(result.symbol_equity_curve)
    assert "组合" in symbol_equity_df.columns
    if result.trades:
        first_trade = result.trades[0]
        assert first_trade["action"] in {"买入", "加仓", "减仓", "清仓", "期末平仓"}
        assert first_trade["shares"] > 0
        assert first_trade["amount"] > 0
        assert first_trade["amount_pct"] > 0
        assert "reason" in first_trade
        assert abs(first_trade["amount_pct"] - first_trade["amount"] / config.initial_capital) < 1e-9
        if first_trade["action"] == "买入":
            symbol_capital = config.initial_capital / len(config.default_backtest_symbols)
            assert first_trade["amount"] <= symbol_capital * config.entry_position_pct + 1e-9


def test_strategy_templates_apply_parameter_overrides_without_losing_pool():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    payload["default_pool"] = [*payload["default_pool"], "TSLA"]
    payload["default_backtest_symbols"] = ["AMD", "TSLA"]

    updated = apply_strategy_template(payload, "steady_trend")

    assert len(STRATEGY_TEMPLATES) == 4
    assert updated["strategy_name"] == "Steady_Trend_v1"
    assert updated["ma_short"] == 30
    assert updated["ma_long"] == 80
    assert updated["entry_position_pct"] == 0.35
    assert updated["default_pool"] == payload["default_pool"]
    assert updated["default_backtest_symbols"] == payload["default_backtest_symbols"]
    assert get_template_label(updated) == "稳健趋势"


def test_strategy_template_diff_rows_show_only_changed_values():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    diff_rows = build_template_diff_rows(payload, "aggressive_breakout")
    diff_by_param = {row["参数"]: row for row in diff_rows}

    assert diff_by_param["MA 短周期"] == {"参数": "MA 短周期", "当前值": "20", "模板值": "10"}
    assert diff_by_param["首次建仓比例"] == {"参数": "首次建仓比例", "当前值": "50%", "模板值": "60%"}
    assert diff_by_param["SOXX 板块共振过滤"] == {"参数": "SOXX 板块共振过滤", "当前值": "启用", "模板值": "关闭"}

    updated = apply_strategy_template(payload, "aggressive_breakout")
    assert build_template_diff_rows(updated, "aggressive_breakout") == []


def test_template_history_summary_groups_runs_and_handles_legacy_rows():
    history_rows = [
        {"运行时间": "2026-05-20 09:30:00", "策略模板": "Steady_Trend_v1", "总收益率": 0.10, "最大回撤": -0.08, "Sharpe": 1.2, "交易动作": 4},
        {"运行时间": "2026-05-20 10:30:00", "策略模板": "Steady_Trend_v1", "总收益率": 0.20, "最大回撤": -0.12, "Sharpe": 1.6, "交易动作": 6},
        {"运行时间": "2026-05-20 11:30:00", "总收益率": 0.05, "最大回撤": -0.04, "Sharpe": 0.8, "交易动作": 2},
    ]

    normalized_df = normalize_backtest_history_frame(history_rows)
    summary_df = build_template_history_summary(history_rows)
    filtered_df = filter_history_by_templates(history_rows, ["Steady_Trend_v1"])

    assert normalized_df["策略模板"].tolist() == ["Steady_Trend_v1", "Steady_Trend_v1", "未记录模板"]
    steady_row = summary_df[summary_df["策略模板"] == "Steady_Trend_v1"].iloc[0]
    assert steady_row["回测次数"] == 2
    assert steady_row["平均收益率"] == pytest.approx(0.15)
    assert steady_row["最好收益率"] == 0.20
    assert steady_row["最差回撤"] == -0.12
    assert steady_row["平均Sharpe"] == pytest.approx(1.4)
    assert filtered_df["策略模板"].tolist() == ["Steady_Trend_v1", "Steady_Trend_v1"]


def test_demo_backtest_supports_manual_symbol():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    payload["default_pool"] = [*payload["default_pool"], "TSLA"]
    payload["default_backtest_symbols"] = ["TSLA"]
    config = StrategyConfig.from_dict(payload)
    market_data = make_demo_market_data(
        config.default_backtest_symbols,
        sector_symbol=config.sector_symbol,
        years=config.backtest_years,
        warmup_days=config.indicator_warmup_days,
    )
    result = BacktestService(config).run(market_data)

    assert result.equity_curve
    assert result.symbol_equity_curve
    assert all(trade["symbol"] == "TSLA" for trade in result.trades)


def test_normalize_symbol_defaults_to_us_market():
    assert normalize_symbol("AMD") == "US.AMD"
    assert normalize_symbol("us.nvda") == "US.NVDA"
    assert normalize_symbol("HK.00700") == "HK.00700"


def test_planning_position_helpers_separate_stock_and_options():
    positions_df = pd.DataFrame(
        [
            {"标的": "AMD", "持仓股数": 10, "成本价": 100.0},
            {"标的": "US.AMD260605P70000", "持仓股数": -1, "成本价": 2.5},
            {"标的": "US.EMPTY", "持仓股数": 0, "成本价": 1.0},
        ]
    )

    editor_df = build_position_editor_frame(["NVDA"], positions_df)

    assert get_position_symbols(positions_df) == ["US.AMD"]
    assert get_option_position_symbols(positions_df) == ["US.AMD260605P70000"]
    assert editor_df["标的"].tolist() == ["US.AMD", "US.AMD260605P70000", "US.EMPTY", "US.NVDA"]
    assert editor_df.loc[editor_df["标的"] == "US.AMD260605P70000", "类型"].iloc[0] == "期权"
    assert editor_df.loc[editor_df["标的"] == "US.AMD260605P70000", "正股标的"].iloc[0] == "US.AMD"


def test_planning_option_overlay_links_underlying_plan():
    positions_df = pd.DataFrame(
        [
            {"标的": "US.AMD", "持仓股数": 100, "成本价": 90.0},
            {"标的": "US.AMD260605C120000", "持仓股数": -1, "成本价": 1.5},
            {"标的": "US.TSLA260605P200000", "持仓股数": -1, "成本价": 3.0},
        ]
    )
    plan_df = pd.DataFrame(
        [
            {
                "标的": "US.AMD",
                "状态": "持仓",
                "计划动作": "继续持仓",
                "优先级": "持仓跟踪",
                "触发依据": "继续观察 MA50",
                "风控关注": "清仓线 MA50",
            }
        ]
    )

    overlay_df = build_option_overlay_summary(positions_df, plan_df)

    assert overlay_df["期权代码"].tolist() == ["US.AMD260605C120000", "US.TSLA260605P200000"]
    assert overlay_df.loc[0, "Overlay角色"] == "备兑 Call"
    assert overlay_df.loc[0, "覆盖口径"] == "备兑覆盖比例"
    assert overlay_df.loc[0, "覆盖/保护比例"] == 1.0
    assert overlay_df.loc[1, "Overlay角色"] == "待关联正股"


def test_planning_option_combo_summary_detects_common_structures():
    option_overlay_df = pd.DataFrame(
        [
            {
                "市场": "美股",
                "正股标的": "US.AMD",
                "到期日": "2026-06-05",
                "期权类型": "Put",
                "持仓方向": "空头",
                "行权价": 120.0,
                "期权代码": "US.AMD260605P120000",
                "持仓数量": -1.0,
                "正股持仓股数": 100.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.AMD",
                "到期日": "2026-06-05",
                "期权类型": "Put",
                "持仓方向": "多头",
                "行权价": 100.0,
                "期权代码": "US.AMD260605P100000",
                "持仓数量": 1.0,
                "正股持仓股数": 100.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.NVDA",
                "到期日": "2026-06-05",
                "期权类型": "Put",
                "持仓方向": "多头",
                "行权价": 90.0,
                "期权代码": "US.NVDA260605P90000",
                "持仓数量": 1.0,
                "正股持仓股数": 100.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.NVDA",
                "到期日": "2026-06-05",
                "期权类型": "Call",
                "持仓方向": "空头",
                "行权价": 140.0,
                "期权代码": "US.NVDA260605C140000",
                "持仓数量": -1.0,
                "正股持仓股数": 100.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.TSLA",
                "到期日": "2026-06-05",
                "期权类型": "Put",
                "持仓方向": "多头",
                "行权价": 180.0,
                "期权代码": "US.TSLA260605P180000",
                "持仓数量": 1.0,
                "正股持仓股数": 0.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.TSLA",
                "到期日": "2026-06-05",
                "期权类型": "Call",
                "持仓方向": "多头",
                "行权价": 260.0,
                "期权代码": "US.TSLA260605C260000",
                "持仓数量": 1.0,
                "正股持仓股数": 0.0,
            },
            {
                "市场": "美股",
                "正股标的": "US.INTC",
                "到期日": "2026-06-05",
                "期权类型": "Call",
                "持仓方向": "多头",
                "行权价": 35.0,
                "期权代码": "US.INTC260605C35000",
                "持仓数量": 1.0,
                "正股持仓股数": 0.0,
            },
        ]
    )

    combo_df = build_option_combo_summary(option_overlay_df)
    combo_by_symbol = {row["正股标的"]: row for row in combo_df.to_dict("records")}

    assert len(combo_df[combo_df["正股标的"] == "US.AMD"]) == 1
    assert combo_by_symbol["US.AMD"]["组合类型"] == "Bull Put Spread"
    assert combo_by_symbol["US.AMD"]["组合方向"] == "偏多/收权利金价差"
    assert combo_by_symbol["US.AMD"]["期权腿数"] == 2
    assert combo_by_symbol["US.AMD"]["合约张数"] == 1.0
    assert combo_by_symbol["US.AMD"]["行权价区间"] == "100.00 - 120.00"
    assert combo_by_symbol["US.NVDA"]["组合类型"] == "Collar"
    assert combo_by_symbol["US.NVDA"]["期权腿数"] == 2
    assert combo_by_symbol["US.TSLA"]["组合类型"] == "Long Strangle"
    assert "US.INTC" not in combo_by_symbol

    unmatched_legs_df = filter_unmatched_option_legs(option_overlay_df, combo_df)
    assert unmatched_legs_df["期权代码"].tolist() == ["US.INTC260605C35000"]


def test_short_period_demo_backtest_runs():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    payload["backtest_years"] = 1 / 12
    config = StrategyConfig.from_dict(payload)
    market_data = make_demo_market_data(
        config.default_backtest_symbols,
        sector_symbol=config.sector_symbol,
        years=config.backtest_years,
        warmup_days=config.indicator_warmup_days,
    )
    result = BacktestService(config).run(market_data)

    assert result.equity_curve
    assert result.symbol_equity_curve


def test_reduce_signal_only_trims_once_per_overheat_episode():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    payload.update(
        {
            "default_pool": ["TST"],
            "default_backtest_symbols": ["TST"],
            "initial_capital": 1000,
            "entry_position_pct": 1.0,
            "add_position_pct": 0.25,
            "reduce_position_pct": 0.5,
            "min_trade_amount": 0.0,
            "use_sector_filter": False,
        }
    )
    config = StrategyConfig.from_dict(payload)
    dates = pd.date_range("2026-01-01", periods=8, freq="B")
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 110, 112, 114, 116, 113, 118, 119],
            "ma_short": [95] * 8,
            "ma_long": [90] * 8,
            "prior_high": [99] * 8,
            "volume": [1000] * 8,
            "volume_ma": [500] * 8,
            "distance_to_ma_short": [0.05, 0.16, 0.17, 0.18, 0.19, 0.10, 0.18, 0.19],
            "entry_signal": [True, False, False, False, False, False, False, False],
            "add_signal": [False] * 8,
            "reduce_signal": [False, True, True, True, True, False, True, True],
            "exit_signal": [False] * 8,
        }
    )

    result = BacktestEngine(config).run({"TST": frame})
    reduce_trades = [trade for trade in result.trades if trade["action"] == "减仓"]

    assert len(reduce_trades) == 2
    assert [trade["date"] for trade in reduce_trades] == [dates[1], dates[6]]


def test_open_position_is_not_forced_closed_at_period_end():
    payload = StrategyConfig.from_json(ROOT / "config" / "default_config.json").to_dict()
    payload.update(
        {
            "default_pool": ["TST"],
            "default_backtest_symbols": ["TST"],
            "initial_capital": 1000,
            "entry_position_pct": 1.0,
            "min_trade_amount": 0.0,
            "use_sector_filter": False,
        }
    )
    config = StrategyConfig.from_dict(payload)
    dates = pd.date_range("2026-01-01", periods=4, freq="B")
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": [100, 105, 110, 115],
            "ma_short": [95] * 4,
            "ma_long": [90] * 4,
            "prior_high": [99] * 4,
            "volume": [1000] * 4,
            "volume_ma": [500] * 4,
            "distance_to_ma_short": [0.05] * 4,
            "entry_signal": [True, False, False, False],
            "add_signal": [False] * 4,
            "reduce_signal": [False] * 4,
            "exit_signal": [False] * 4,
        }
    )

    result = BacktestEngine(config).run({"TST": frame})

    assert [trade["action"] for trade in result.trades] == ["买入"]
    assert result.equity_curve[-1]["equity"] == 1150


def test_cache_info_reports_missing_cache(tmp_path):
    provider = FutuHistoricalDataProvider(FutuDataConfig(cache_dir=tmp_path))
    info = provider.get_cache_info("AMD")

    assert info["normalized"] == "US.AMD"
    assert info["status"] == "未缓存"
    assert info["rows"] == 0
    assert info["cache_age_days"] == ""
    assert info["freshness"] == ""


def test_cache_info_reports_cache_freshness(tmp_path):
    cache_path = tmp_path / "US_AMD.csv"
    today = pd.Timestamp.today().normalize()
    pd.DataFrame(
        {
            "date": [today],
            "symbol": ["AMD"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [100.0],
        }
    ).to_csv(cache_path, index=False)
    provider = FutuHistoricalDataProvider(FutuDataConfig(cache_dir=tmp_path))

    info = provider.get_cache_info("AMD")

    assert info["status"] == "已缓存"
    assert info["rows"] == 1
    assert info["cache_age_days"] == 0
    assert info["freshness"] == "今日最新"


def test_futu_positions_keep_negative_quantity_and_refresh_cache(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.position_data = pd.DataFrame(
        {
            "stock_code": ["US.AMD", "US.INTC260120C50000", "US.ZERO"],
            "position_qty": [12, -2, 0],
            "diluted_cost": [100.5, 1.25, 0.0],
        }
    )
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    positions = provider.get_positions(market="US", trd_env="SIMULATE", acc_id=12345)

    assert positions.to_dict("records") == [
        {"标的": "US.AMD", "持仓股数": 12.0, "成本价": 100.5},
        {"标的": "US.INTC260120C50000", "持仓股数": -2.0, "成本价": 1.25},
    ]
    assert FakeFutuTradeContext.position_query_args == {
        "trd_env": "SIMULATE",
        "refresh_cache": True,
        "acc_id": 12345,
    }
    assert FakeFutuTradeContext.close_count == 1


def test_futu_account_info_uses_buying_power_as_plan_capital(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.account_data = pd.DataFrame(
        {
            "total_asset": [50000.0],
            "cash_balance": [12000.0],
            "max_power_long": [18000.0],
            "currency": ["USD"],
        }
    )
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    account_info = provider.get_account_info(market="US", trd_env="SIMULATE", acc_id=67890)

    assert account_info == {
        "market": "US",
        "trd_env": "SIMULATE",
        "acc_id": 67890,
        "currency": "USD",
        "total_assets": 50000.0,
        "cash": 12000.0,
        "buying_power": 18000.0,
        "plan_capital": 18000.0,
    }
    assert FakeFutuTradeContext.account_query_args == {
        "trd_env": "SIMULATE",
        "refresh_cache": True,
        "acc_id": 67890,
    }
    assert FakeFutuTradeContext.close_count == 1


def test_futu_positions_raise_when_required_fields_missing(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.position_data = pd.DataFrame({"code": ["US.AMD"], "average_cost": [100.0]})
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    with pytest.raises(RuntimeError, match="缺少 code/qty"):
        provider.get_positions(market="US", trd_env="SIMULATE")

    assert FakeFutuTradeContext.close_count == 1


def test_futu_positions_raise_when_query_fails(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.position_ret = -1
    FakeFutuTradeContext.position_data = "permission denied"
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    with pytest.raises(RuntimeError, match="富途持仓查询失败"):
        provider.get_positions(market="US", trd_env="SIMULATE")

    assert FakeFutuTradeContext.close_count == 1


def test_futu_account_info_raises_when_empty(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.account_data = pd.DataFrame()
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    with pytest.raises(RuntimeError, match="资金查询结果为空"):
        provider.get_account_info(market="US", trd_env="SIMULATE")

    assert FakeFutuTradeContext.close_count == 1


def test_futu_account_info_raises_when_query_fails(monkeypatch):
    install_fake_futu_module(monkeypatch)
    FakeFutuTradeContext.account_ret = -1
    FakeFutuTradeContext.account_data = "locked"
    provider = FutuHistoricalDataProvider(FutuDataConfig(host="127.0.0.1", port=11111))

    with pytest.raises(RuntimeError, match="富途资金查询失败"):
        provider.get_account_info(market="US", trd_env="SIMULATE")

    assert FakeFutuTradeContext.close_count == 1


def test_strategy_plan_export_includes_traceable_snapshot():
    config = StrategyConfig.from_json(ROOT / "config" / "default_config.json")
    plan_df = pd.DataFrame(
        [
            {
                "优先级排序": 2,
                "市场": "美股",
                "标的": "US.AMD",
                "计划动作": "建仓",
            }
        ]
    )
    equity_df = pd.DataFrame({"date": pd.to_datetime(["2026-01-02", "2026-01-05"]), "portfolio": [100000, 101000]})

    export_df = build_strategy_plan_export_frame(
        plan_df,
        config=config,
        data_source="富途真实行情",
        equity_df=equity_df,
        capital_source="富途账户资金",
        capital_value=18000.0,
        position_source="当前持仓表",
        app_version="0.1-test",
        account_info={"market": "US", "trd_env": "SIMULATE", "currency": "USD"},
        generated_at=pd.Timestamp("2026-05-18 10:30:00"),
    )

    assert "优先级排序" not in export_df.columns
    row = export_df.iloc[0]
    assert row["导出时间"] == "2026-05-18 10:30:00"
    assert row["应用版本"] == "0.1-test"
    assert row["数据源"] == "富途真实行情"
    assert row["行情开始日期"] == "2026-01-02"
    assert row["行情结束日期"] == "2026-01-05"
    assert row["资金来源"] == "富途账户资金"
    assert row["计划资金基准"] == 18000.0
    assert row["持仓来源"] == "当前持仓表"
    assert row["账户市场"] == "US"
    assert '"ma_short"' in row["策略参数快照"]


def test_cockpit_overview_prioritizes_actions_and_option_attention():
    strategy_plan_df = pd.DataFrame(
        [
            {
                "标的": "US.AMD",
                "计划动作": "减仓",
                "优先级": "降低风险",
                "参考交易金额": 2000.0,
                "距关键价位": -0.12,
                "触发依据": "处于过热区",
                "金额说明": "当前减仓参考",
            },
            {
                "标的": "US.NVDA",
                "计划动作": "等待触发",
                "优先级": "接近触发",
                "参考交易金额": None,
                "距关键价位": -0.015,
                "触发依据": "接近入场观察价",
                "金额说明": "触发后参考 $1,000.00 / 1.0000 股",
            },
        ]
    )
    option_overlay_df = pd.DataFrame(
        [
            {
                "期权代码": "US.AMD260120C50000",
                "Overlay角色": "卖出 Call 风险敞口",
                "正股优先级": "降低风险",
                "风险提示": "正股强反弹时，裸卖 Call 风险不对称。",
                "覆盖口径": "无对应正股持仓",
                "到期天数": 20,
                "覆盖/保护比例": None,
            }
        ]
    )

    metrics, tasks_df = build_cockpit_overview(strategy_plan_df, option_overlay_df)

    assert metrics == {"当前动作": 1, "降低风险": 1, "接近触发": 1, "期权关注": 1}
    assert tasks_df["类别"].tolist() == ["当前动作", "期权关注", "接近触发"]
    assert tasks_df.loc[0, "资金/仓位"] == "$2,000.00"
    assert tasks_df.loc[1, "动作"] == "卖出 Call 风险敞口"


def test_cockpit_overview_prefers_option_combo_over_single_legs():
    option_overlay_df = pd.DataFrame(
        [
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P120000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 120.0,
                "持仓方向": "空头",
                "持仓数量": -1.0,
                "合约对应股数": 100.0,
                "Overlay角色": "卖出 Put 风险敞口",
                "正股优先级": "降低风险",
                "覆盖口径": "潜在接股比例",
                "风险提示": "高行权价 Put 需要关注接股风险。",
            },
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P100000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 100.0,
                "持仓方向": "多头",
                "持仓数量": 1.0,
                "合约对应股数": 100.0,
                "Overlay角色": "保护性 Put",
                "正股优先级": "降低风险",
                "覆盖口径": "保护比例",
                "风险提示": "低行权价 Put 提供有限保护。",
            },
        ]
    )
    option_combo_df = build_option_combo_summary(option_overlay_df)

    metrics, tasks_df = build_cockpit_overview(
        pd.DataFrame(),
        option_overlay_df,
        option_combo_df,
        current_date=pd.Timestamp("2026-05-19"),
    )

    assert metrics["期权关注"] == 1
    assert tasks_df["标的"].tolist() == ["US.AMD"]
    assert tasks_df.loc[0, "动作"] == "Bull Put Spread / 偏多/收权利金价差"
    assert tasks_df.loc[0, "优先级"] == "组合复核"


def test_cockpit_sections_build_risk_expiry_and_capital_views():
    strategy_plan_df = pd.DataFrame(
        [
            {
                "标的": "US.AMD",
                "状态": "持仓",
                "计划动作": "清仓",
                "参考交易金额": 3000.0,
                "距关键价位": -0.02,
                "风控关注": "清仓线 MA50",
                "计划说明": "趋势防线失效，优先保护本金。",
            },
            {
                "标的": "US.NVDA",
                "状态": "持仓",
                "计划动作": "继续持仓",
                "参考交易金额": None,
                "距关键价位": 0.03,
                "风控关注": "清仓线 MA50",
                "计划说明": "靠近关键风控线。",
            },
            {
                "标的": "US.MSFT",
                "状态": "空仓",
                "计划动作": "建仓",
                "参考交易金额": 1500.0,
                "距关键价位": 0.1,
                "风控关注": "入场观察价",
                "计划说明": "突破后建仓。",
            },
            {
                "标的": "US.QQQ",
                "状态": "空仓",
                "计划动作": "等待触发",
                "参考交易金额": None,
                "距关键价位": -0.12,
                "触发依据": "等待突破过去 20 日前高",
                "风控关注": "入场观察价",
                "计划说明": "继续观察。",
            },
        ]
    )
    option_overlay_df = pd.DataFrame(
        [
            {
                "期权代码": "US.AMD260605P70000",
                "正股标的": "US.AMD",
                "到期天数": 12,
                "Overlay角色": "保护性 Put",
                "覆盖口径": "保护比例",
                "风险提示": "时间价值会持续衰减。",
            },
            {
                "期权代码": "US.NVDA261218C120000",
                "正股标的": "US.NVDA",
                "到期天数": 210,
                "Overlay角色": "备兑 Call",
                "覆盖口径": "备兑覆盖比例",
                "风险提示": "突破行情中可能让渡收益。",
            },
        ]
    )

    sections = build_cockpit_sections(strategy_plan_df, option_overlay_df)

    assert sections["risk_positions"]["标的"].tolist() == ["US.AMD", "US.NVDA"]
    assert sections["risk_positions"].loc[0, "风险等级"] == "高"
    assert sections["option_expiry"]["期权代码"].tolist() == ["US.AMD260605P70000"]
    assert sections["capital_actions"].to_dict("records") == [
        {"动作": "清仓", "标的数": 1, "参考金额合计": 3000.0},
        {"动作": "建仓", "标的数": 1, "参考金额合计": 1500.0},
    ]
    assert sections["observe_only"].to_dict("records") == [
        {
            "标的": "US.QQQ",
            "状态": "空仓",
            "计划动作": "等待触发",
            "距关键价位": "-12.00%",
            "下一步关注": "等待突破过去 20 日前高",
        }
    ]


def test_cockpit_option_expiry_prefers_combo_view_over_legs():
    option_overlay_df = pd.DataFrame(
        [
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P120000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 120.0,
                "持仓方向": "空头",
                "持仓数量": -1.0,
                "Overlay角色": "卖出 Put 风险敞口",
                "覆盖口径": "潜在接股比例",
                "风险提示": "高行权价 Put 需要关注接股风险。",
            },
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P100000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 100.0,
                "持仓方向": "多头",
                "持仓数量": 1.0,
                "Overlay角色": "保护性 Put",
                "覆盖口径": "保护比例",
                "风险提示": "低行权价 Put 提供有限保护。",
            },
            {
                "市场": "美股",
                "期权代码": "US.INTC260605C35000",
                "正股标的": "US.INTC",
                "期权类型": "Call",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 35.0,
                "持仓方向": "多头",
                "持仓数量": 1.0,
                "Overlay角色": "进攻性 Call",
                "覆盖口径": "上行杠杆敞口比例",
                "风险提示": "到期前若趋势未恢复，权利金可能损耗。",
            },
        ]
    )
    option_combo_df = build_option_combo_summary(option_overlay_df)

    sections = build_cockpit_sections(
        pd.DataFrame(),
        option_overlay_df,
        option_combo_df,
        current_date=pd.Timestamp("2026-05-19"),
    )
    expiry_df = sections["option_expiry"]
    combo_rows = expiry_df[expiry_df["显示口径"] == "组合"]
    single_rows = expiry_df[expiry_df["显示口径"] == "单腿"]

    assert expiry_df["显示口径"].tolist() == ["组合", "单腿"]
    assert combo_rows.iloc[0]["正股标的"] == "US.AMD"
    assert combo_rows.iloc[0]["期权结构"] == "Bull Put Spread / 偏多/收权利金价差"
    assert "US.AMD260605P120000" in combo_rows.iloc[0]["涉及合约"]
    assert single_rows["期权代码"].tolist() == ["US.INTC260605C35000"]


def test_cockpit_snapshot_row_summarizes_sections():
    metrics = {"当前动作": 2, "降低风险": 1, "接近触发": 1, "期权关注": 1}
    tasks_df = pd.DataFrame([{"类别": "当前动作"}, {"类别": "期权关注"}])
    sections = {
        "risk_positions": pd.DataFrame([{"标的": "US.AMD"}]),
        "option_expiry": pd.DataFrame([{"期权代码": "US.AMD260605P70000"}]),
        "observe_only": pd.DataFrame([{"标的": "US.QQQ"}, {"标的": "US.SPY"}]),
        "capital_actions": pd.DataFrame(
            [
                {"动作": "建仓", "参考金额合计": 1000.0},
                {"动作": "减仓", "参考金额合计": 500.0},
            ]
        ),
    }

    row = build_cockpit_snapshot_row(
        metrics,
        tasks_df,
        sections,
        data_source="演示数据",
        capital_source="模拟初始资金",
        capital_value=100000.0,
        symbols=["US.AMD", "US.NVDA"],
        app_version="0.3-test",
        created_at=pd.Timestamp("2026-05-19 09:30:00"),
    )

    assert row == {
        "快照时间": "2026-05-19 09:30:00",
        "应用版本": "0.3-test",
        "数据源": "演示数据",
        "参与标的": "US.AMD,US.NVDA",
        "资金来源": "模拟初始资金",
        "计划资金基准": 100000.0,
        "当前动作": 2,
        "降低风险": 1,
        "接近触发": 1,
        "期权关注": 1,
        "今日任务数": 2,
        "风险持仓数": 1,
        "期权到期数": 1,
        "只观察数": 2,
        "已触发参考金额": 1500.0,
    }


def test_cockpit_risk_budget_summarizes_stock_and_option_exposure():
    strategy_plan_df = pd.DataFrame(
        [
            {"计划动作": "建仓", "参考交易金额": 2000.0},
            {"计划动作": "加仓", "参考交易金额": 500.0},
            {"计划动作": "减仓", "参考交易金额": 800.0},
            {"计划动作": "等待触发", "参考交易金额": None},
        ]
    )
    option_overlay_df = pd.DataFrame(
        [
            {
                "期权类型": "Put",
                "持仓方向": "空头",
                "合约对应股数": 200.0,
                "行权价": 50.0,
                "覆盖口径": "潜在接股比例",
                "覆盖/保护比例": 0.5,
            },
            {
                "期权类型": "Call",
                "持仓方向": "空头",
                "合约对应股数": 100.0,
                "行权价": 70.0,
                "覆盖口径": "备兑覆盖比例",
                "覆盖/保护比例": 0.75,
            },
        ]
    )

    budget = build_cockpit_risk_budget(strategy_plan_df, option_overlay_df, capital_value=100000.0)

    assert budget == {
        "增风险金额": 2500.0,
        "降风险金额": 800.0,
        "净风险变化": 1700.0,
        "今日动作资金占比": 0.033,
        "潜在接股金额": 10000.0,
        "组合价差风险金额": 0.0,
        "未充分备兑Call数": 1.0,
    }


def test_cockpit_risk_budget_excludes_combo_legs_and_tracks_spread_risk():
    option_overlay_df = pd.DataFrame(
        [
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P120000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 120.0,
                "持仓方向": "空头",
                "持仓数量": -1.0,
                "合约对应股数": 100.0,
                "覆盖口径": "潜在接股比例",
                "覆盖/保护比例": None,
            },
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P100000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 100.0,
                "持仓方向": "多头",
                "持仓数量": 1.0,
                "合约对应股数": 100.0,
                "覆盖口径": "保护比例",
                "覆盖/保护比例": None,
            },
        ]
    )
    option_combo_df = build_option_combo_summary(option_overlay_df)

    budget = build_cockpit_risk_budget(pd.DataFrame(), option_overlay_df, option_combo_df, capital_value=100000.0)

    assert budget["潜在接股金额"] == 0.0
    assert budget["组合价差风险金额"] == 2000.0


def test_cockpit_risk_budget_detail_tracks_sources_without_duplicate_combo_legs():
    strategy_plan_df = pd.DataFrame(
        [
            {"标的": "US.AMD", "计划动作": "减仓", "参考交易金额": 800.0, "触发依据": "过热减仓"},
            {"标的": "US.MSFT", "计划动作": "建仓", "参考交易金额": 1200.0, "触发依据": "突破建仓"},
        ]
    )
    option_overlay_df = pd.DataFrame(
        [
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P120000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 120.0,
                "持仓方向": "空头",
                "持仓数量": -1.0,
                "合约对应股数": 100.0,
                "覆盖口径": "潜在接股比例",
                "覆盖/保护比例": None,
            },
            {
                "市场": "美股",
                "期权代码": "US.AMD260605P100000",
                "正股标的": "US.AMD",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 100.0,
                "持仓方向": "多头",
                "持仓数量": 1.0,
                "合约对应股数": 100.0,
                "覆盖口径": "保护比例",
                "覆盖/保护比例": None,
            },
            {
                "市场": "美股",
                "期权代码": "US.INTC260605P30000",
                "正股标的": "US.INTC",
                "期权类型": "Put",
                "到期日": "2026-06-05",
                "到期天数": 17,
                "行权价": 30.0,
                "持仓方向": "空头",
                "持仓数量": -1.0,
                "合约对应股数": 100.0,
                "覆盖口径": "无正股，需用现金或购买力覆盖潜在接股",
                "覆盖/保护比例": None,
            },
        ]
    )
    option_combo_df = build_option_combo_summary(option_overlay_df)

    detail_df = build_cockpit_risk_budget_detail(strategy_plan_df, option_overlay_df, option_combo_df)
    records = detail_df.to_dict("records")

    assert [row["类别"] for row in records] == ["降风险", "增风险", "组合价差风险", "潜在接股"]
    assert detail_df[detail_df["类别"] == "组合价差风险"].iloc[0]["参考金额"] == 2000.0
    assert detail_df[detail_df["类别"] == "潜在接股"].iloc[0]["涉及合约"] == "US.INTC260605P30000"
    assert "US.AMD260605P120000" not in detail_df[detail_df["类别"] == "潜在接股"]["涉及合约"].tolist()


def test_review_trend_uses_latest_review_per_day():
    reviews_df = pd.DataFrame(
        [
            {"复盘日期": "2026-05-19", "复盘时间": "2026-05-19 09:30:00", "任务数": 4, "已处理": 1},
            {"复盘日期": "2026-05-19", "复盘时间": "2026-05-19 16:00:00", "任务数": 4, "已处理": 3},
            {"复盘日期": "2026-05-20", "复盘时间": "2026-05-20 16:00:00", "任务数": 0, "已处理": 0},
        ]
    )

    trend_df = build_review_trend(reviews_df)

    assert trend_df["复盘日期"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-19", "2026-05-20"]
    assert trend_df["完成率"].tolist() == [0.75, 1.0]
    assert trend_df["未完成"].tolist() == [1, 0]


def test_weekly_review_summary_groups_latest_daily_reviews():
    reviews_df = pd.DataFrame(
        [
            {"复盘日期": "2026-05-18", "复盘时间": "2026-05-18 10:00:00", "任务数": 2, "已处理": 1, "净风险变化": 100.0},
            {"复盘日期": "2026-05-19", "复盘时间": "2026-05-19 09:30:00", "任务数": 4, "已处理": 1, "净风险变化": 300.0},
            {"复盘日期": "2026-05-19", "复盘时间": "2026-05-19 16:00:00", "任务数": 4, "已处理": 3, "净风险变化": -200.0},
            {"复盘日期": "2026-05-25", "复盘时间": "2026-05-25 16:00:00", "任务数": 1, "已处理": 1, "净风险变化": 50.0},
        ]
    )

    summary_df = build_weekly_review_summary(reviews_df)

    assert summary_df["周开始"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-18", "2026-05-25"]
    assert summary_df["任务数"].tolist() == [6, 1]
    assert summary_df["已处理"].tolist() == [4, 1]
    assert summary_df["未完成"].tolist() == [2, 0]
    assert summary_df["净风险变化"].tolist() == [-100.0, 50.0]


def test_regression_check_rows_and_summary_use_latest_batch():
    checks_df = pd.DataFrame(
        [
            {"检查项": "OpenD 连接正常", "结果": "通过", "备注": ""},
            {"检查项": "账户资金读取正常", "结果": "需复核", "备注": "现金待核对"},
        ]
    )
    metadata = {
        "检查日期": "2026-05-19",
        "应用版本": "0.3-test",
        "数据源": "富途真实行情",
        "交易环境": "真实账户（只读）",
        "持仓行数": 4,
        "期权行数": 1,
        "任务数": 3,
    }

    first_rows_df = build_regression_check_rows(checks_df, metadata, created_at=pd.Timestamp("2026-05-19 09:30:00"))
    second_rows_df = build_regression_check_rows(
        checks_df.assign(结果=["通过", "通过"]),
        metadata,
        created_at=pd.Timestamp("2026-05-19 16:00:00"),
    )
    all_rows_df = pd.concat([first_rows_df, second_rows_df], ignore_index=True)
    summary = build_regression_check_summary(all_rows_df)

    assert first_rows_df.to_dict("records")[0] == {
        "检查时间": "2026-05-19 09:30:00",
        "检查日期": "2026-05-19",
        "应用版本": "0.3-test",
        "数据源": "富途真实行情",
        "交易环境": "真实账户（只读）",
        "持仓行数": 4,
        "期权行数": 1,
        "任务数": 3,
        "检查项": "OpenD 连接正常",
        "结果": "通过",
        "备注": "",
    }
    assert summary == {
        "检查时间": "2026-05-19 16:00:00",
        "检查项": 2,
        "通过": 2,
        "需复核": 0,
        "失败": 0,
        "未检查": 0,
        "通过率": 1.0,
    }


def test_regression_check_frame_prefills_from_current_page_state():
    frame = build_regression_check_frame(
        [
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
        ],
        data_source="富途真实行情",
        position_count=3,
        stock_count=2,
        option_count=1,
        has_account_info=True,
        has_last_backtest=True,
        strategy_plan_count=2,
        cockpit_task_count=1,
        option_combo_count=1,
    )

    results = frame.set_index("检查项")["结果"].to_dict()
    notes = frame.set_index("检查项")["备注"].to_dict()

    assert results["OpenD 连接正常"] == "通过"
    assert results["持仓读取正常"] == "通过"
    assert results["账户资金读取正常"] == "通过"
    assert results["股票和期权隔离正确"] == "通过"
    assert results["期权组合识别合理"] == "需复核"
    assert results["策略计划动作合理"] == "需复核"
    assert results["Cockpit 风险预算方向正确"] == "需复核"
    assert results["今日复盘和周度摘要可更新"] == "未检查"
    assert "正股/ETF 2 个，期权 1 个" in notes["股票和期权隔离正确"]