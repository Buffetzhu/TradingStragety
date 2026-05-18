# TradingStragety

AI 趋势交易策略工作台。项目按 `CLAUDE.md` 中的 `Playbooks -> Scripts` 两层框架组织。

当前版本：0.2。开发进度和下一步计划见 `DEVELOPMENT_LOG.md`。

## V1 目标

- 内置 `GPT_Trend_Default_v1` 默认策略
- 支持一键运行趋势回测
- 支持后续接入富途 OpenAPI、观察库、策略线和单标的策略驾驶舱

## V2 稳定版范围

- 富途持仓只读导入，支持正股、ETF、期权和负数量持仓
- 富途账户资金只读导入，可用购买力/现金/总资产估算策略计划资金基准
- 当前持仓、观察清单和策略计划联动，期权不进入正股趋势回测
- 期权持仓关联正股策略计划，显示到期、行权价、覆盖/保护比例、Overlay 角色和风险提示
- 策略计划 CSV 导出包含版本、行情区间、资金来源、持仓来源和策略参数快照
- V2 回归流程见 `playbooks/validate-v2-stable.md`

## 快速验证

```powershell
python scripts/run_backtest.py --demo
```

## V2 验证

```powershell
.venv\Scripts\python.exe -m pytest tests
```

## 启动 Streamlit

```powershell
streamlit run app.py
```
