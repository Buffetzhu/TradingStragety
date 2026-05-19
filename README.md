# TradingStragety

AI 趋势交易策略工作台。项目按 `CLAUDE.md` 中的 `Playbooks -> Scripts` 两层框架组织。

当前版本：0.3。开发进度和下一步计划见 `DEVELOPMENT_LOG.md`。

## V1 目标

- 内置 `GPT_Trend_Default_v1` 默认策略
- 支持一键运行趋势回测
- 支持后续接入富途 OpenAPI、观察库、策略线和单标的策略驾驶舱

## V2 稳定版范围

- 富途持仓只读导入，支持正股、ETF、期权和负数量持仓
- 富途账户资金只读导入，可用购买力/现金/总资产估算策略计划资金基准
- 当前持仓、观察清单和策略计划联动，期权不进入正股趋势回测
- 期权持仓关联正股策略计划，显示到期、行权价、覆盖/保护比例、Overlay 角色和风险提示
- 期权组合识别聚焦 Vertical Spread、Straddle/Strangle 和 Collar；Covered Call、Protective Put、Cash-secured Put 保留在单腿关联角色中提示
- 策略计划 CSV 导出包含版本、行情区间、资金来源、持仓来源和策略参数快照
- V2 回归流程见 `playbooks/validate-v2-stable.md`

## V0.3 Cockpit 稳定版

- Cockpit 首页汇总当前动作、风险持仓、接近触发、期权关注和只观察队列
- 页面默认不勾选参与回测标的，默认交易环境为真实账户只读，默认回测周期为 6 个月，默认数据源为富途真实行情
- 支持保存 Cockpit 快照到 `data/cockpit_snapshots.csv`，用于后续每日复盘
- 支持编辑今日任务状态，并保存 Cockpit 复盘到 `data/cockpit_reviews.csv`
- 显示增风险金额、降风险金额、净风险变化、动作资金占比和潜在接股金额
- 支持 Cockpit 聚焦标的联动到下方单标的价格与仓位图
- 支持按每日复盘记录展示完成率趋势
- 支持按周汇总复盘天数、任务完成、未完成和净风险变化
- 支持记录真实账户只读检查清单，并保存到 `data/cockpit_regression_checks.csv`
- 将持仓识别、策略计划和期权 Overlay 计算沉淀到 `src/trend_option_backtest/planning.py`
- 期权区域先展示多腿组合识别，再展示未归入组合的单腿关联，避免重复阅读
- 默认展示 `今日行动计划`，将 `策略观察清单` 收进折叠区，降低页面重复感
- 支持在 VS Code 内用 Simple Browser 预览本地 Streamlit 页面

## 后续路线原则

- 易用性优先：优先把默认流程、错误提示、页面层级和每日 Cockpit 做轻，不把工具做成重度专业终端。
- 日常使用优先：下一阶段重点是让真实持仓读取、加入股票池、运行回测、查看计划和保存复盘更顺手。
- 期权轻量化：近期只保留期权识别、隔离、关联正股计划和基础风险提醒；复杂期权定价、希腊值、隐含波动率和组合风险建模延后评估。
- 安全边界不变：富途相关能力继续保持只读，不解锁交易，不自动下单。

## 快速验证

```powershell
python scripts/run_backtest.py --demo
```

## V0.3 验证

```powershell
.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\planning.py src\trend_option_backtest\cockpit.py tests\test_default_backtest.py
.venv\Scripts\python.exe -m pytest tests
```

## 启动 Streamlit

```powershell
streamlit run app.py
```

## VS Code 内预览

1. 按 `Ctrl+Shift+P`，运行 `Tasks: Run Task`。
2. 选择 `启动 Streamlit 工具`。
3. 再按 `Ctrl+Shift+P`，运行 `Simple Browser: Show`。
4. 输入 `http://127.0.0.1:8501`。

这样页面会在 VS Code 标签页里打开，不需要每次切到外部浏览器。
