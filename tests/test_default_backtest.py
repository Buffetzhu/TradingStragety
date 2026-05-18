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
from trend_option_backtest.exporting import build_strategy_plan_export_frame
from trend_option_backtest.models import StrategyConfig
from trend_option_backtest.providers.futu_provider import FutuDataConfig, FutuHistoricalDataProvider, normalize_symbol
from trend_option_backtest.services.backtest_service import BacktestService


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