# TradingStragety

AI 趋势交易策略工作台。项目按 `CLAUDE.md` 中的 `Playbooks -> Scripts` 两层框架组织。

当前版本：0.1。开发进度和下一步计划见 `DEVELOPMENT_LOG.md`。

## V1 目标

- 内置 `GPT_Trend_Default_v1` 默认策略
- 支持一键运行趋势回测
- 支持后续接入富途 OpenAPI、观察库、策略线和单标的策略驾驶舱

## 快速验证

```powershell
python scripts/run_backtest.py --demo
```

## 启动 Streamlit

```powershell
streamlit run app.py
```