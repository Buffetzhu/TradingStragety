# TradingStragety

AI 趋势交易策略工作台。项目按 `CLAUDE.md` 中的 `Playbooks -> Scripts` 两层框架组织。

当前版本：0.8。开发进度和下一步计划见 `DEVELOPMENT_LOG.md`。远程部署清单见 `deploy/README.md`。

## 隐私优先部署（推荐）

- 默认建议采用本地私有部署，不把 OpenD 暴露到公网。
- 手机访问优先使用同一 Wi-Fi 局域网地址，或使用 Tailscale 私网地址。
- 一键启动命令：

```bash
bash scripts/start_private_access.sh
```

- 详细说明见 `deploy/README.md`。
- 如需“网页打开先输密码”，可配置访问密码：

```bash
export APP_ACCESS_PASSWORD='请改成强密码'
bash scripts/start_private_access.sh
```

- 也可写入 `.streamlit/secrets.toml` 的 `APP_ACCESS_PASSWORD`。

## 外网访问（免安装客户端）

如果你希望在任何网络环境下访问，并且只通过网页密码放行：

```bash
export APP_ACCESS_PASSWORD='请改成强密码'
bash scripts/start_public_password_access.sh
```

- 脚本会打印一个 `https://*.trycloudflare.com` 外网地址。
- 手机或电脑在外网打开该地址，输入正确密码即可访问。
- 该方案只暴露 Web 端口 8501，OpenD 仍保持本机 `127.0.0.1:11111`。

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

## V0.4 开发方向

- 强化日常使用流程：打开页面后先看到当前是否已选标的、是否有持仓、是否读取账户资金、是否已生成行动计划
- 今日流程状态显示数据源、账户模式和只读安全边界，减少真实账户模式下的误解
- 继续减少首页噪音，让默认路径围绕读取持仓、加入回测、运行回测、查看今日行动计划展开
- 保持期权模块轻量，不把期权高级分析放进主流程
- 今日行动计划主表只保留执行字段，价格、风控和触发依据进入详情折叠区
- Cockpit 默认显示核心指标，风险预算按需展开，聚焦摘要和分区明细默认展开
- 富途连接、行情缺失和账户输入错误给出更具体的操作提示
- 清理 Streamlit 弃用参数提醒，保持本地运行日志更干净
- 真实账户检查清单按当前页面状态预填结果和备注，保留人工复核入口
- Cockpit 期权到期分区优先显示多腿组合，组合腿不再重复按单腿展示
- Cockpit 期权关注任务和风险预算使用组合优先口径，价差组合单独显示组合价差风险
- 风险预算提供明细表，展示每一项预算来源和涉及合约

## V0.5 开发方向

- 新增轻量策略模板选择，不开放自由策略代码，先用参数模板控制复杂度
- 内置 `GPT 趋势默认`、`稳健趋势`、`激进突破`、`防守观察` 四套模板
- 模板切换只调整策略参数，不覆盖股票池、当前回测标的、持仓和账户状态
- 应用模板前展示参数差异预览，明确当前值和模板值
- 回测历史和当前策略摘要记录模板来源，便于比较不同风格的回测结果
- 回测运行历史提供按策略模板分组的表现摘要，并支持按模板筛选明细

## 下一步原则

- V0.5 先收口，不继续追加新功能。
- 下一轮优先重新审视页面复杂度，区分每日决策主路径和低频辅助功能。
- 后续开发先考虑减法、折叠、拆页和去重复，再考虑新增分析能力。

## V0.6 开发方向

- 引入 `模拟研究 / 账户追踪` 双工作区，模式切换后只显示对应区块，减少首页噪音
- 账户模式下默认折叠 `策略历史回测参考` 和 `策略历史回测结果`，并明确标注与账户无关，避免与真实账户数据混淆
- 账户工作区顶部新增 `账户快照`：总资产 / 现金 / 购买力 / 持仓条目（正股+期权数量）
- 主区新增 `🔄 一键刷新持仓 + 重跑今日策略` 按钮，自动完成读账户 -> 写持仓 -> 跑回测 -> 出行动计划，并通过 toast 提示成功/失败
- 今日行动计划由表格改为按优先级排序的 Top 5 卡片，完整明细收进折叠面板
- 模拟工作区抽出为 `_render_simulation_workspace()`，账户工作区用清晰分段标题分组
- 侧栏 `数据接入` `当前持仓与账户资金` `策略规则参数` 全部默认折叠在账户模式下，模拟模式默认展开
- 单标的图表选择器只在 Cockpit 聚焦真正变化时同步一次，手动切换标的不再被覆盖

## 双工作区使用指南

- **模拟研究**：默认展开 `当前策略摘要` 和 `回测结果与权益曲线`，用于比较不同策略模板和参数；下方有单标的图表和回测运行历史，不与账户挂钩
- **账户追踪**：默认展示 `今日流程状态` -> `当前策略来源` -> `一键刷新` -> `账户快照` -> `Cockpit` -> `今日行动计划（卡片化）` -> `期权关联` -> `单标的图表`；`策略历史回测参考` 折叠在顶部仅供策略健康度判断

## 快速验证

```powershell
python scripts/run_backtest.py --demo
```

## 当前版本验证

```powershell
.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\planning.py src\trend_option_backtest\cockpit.py src\trend_option_backtest\history.py src\trend_option_backtest\strategy_templates.py src\trend_option_backtest\__init__.py tests\test_default_backtest.py
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
