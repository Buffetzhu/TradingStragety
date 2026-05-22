# TradingStragety 开发日志

## 版本 0.1 - 2026-05-15

### 当前定位

本项目当前是一个个人股票趋势策略工作台。第一阶段目标不是自动交易，而是把“股票池选择、趋势策略回测、参数调试、策略观察清单、当前持仓计划”串成一个可快速迭代的本地工具。

当前前端使用 Streamlit，主入口是 `app.py`。后端核心代码放在 `src/trend_option_backtest/`。

### 已完成能力

- 支持点击运行默认回测，也支持用当前参数回测。
- 支持股票池选择和手动添加标的。
- 应用内股票代码统一为富途格式，例如 `US.AMD`、`US.NVDA`。
- 支持演示行情和富途真实历史行情两种数据源。
- 富途历史行情支持本地 CSV 缓存、缓存状态查看、缓存新鲜度提示和强制刷新。
- 策略参数可配置，包括 MA 周期、突破天数、成交量倍数、过热距离、建仓/加仓/减仓比例、最小成交额、SOXX 板块过滤。
- 支持保存、加载、删除策略参数预设。
- 回测引擎支持分批建仓、加仓、减仓、清仓，不再默认期末强制平仓。
- 回测结果包括核心指标、权益曲线、单标的表现概览、交易流水。
- 历史运行记录会持久化到本地，支持运行对比和 CSV 下载。
- “收益与回撤对比”已改为风险收益分布图，便于比较不同回测版本。
- 当前策略观察清单会显示每个标的的状态、关键价位、信号和下一步关注点。
- 策略计划明细会把信号翻译成行动计划，包括计划动作、优先级、参考交易金额、金额说明、触发依据和风控关注。
- 支持手动录入当前持仓，并用当前持仓表生成观察清单和策略计划。
- 支持从富途 OpenD 只读导入当前持仓，默认使用模拟账户；真实账户模式也是只读，不下单、不解锁交易。
- 富途持仓导入后保存到 `data/current_positions.csv`，该文件按 `.gitignore` 不提交。

### 当前关键文件

- `app.py`：Streamlit 主界面，包含参数侧边栏、回测入口、图表、观察清单、策略计划和当前持仓导入。
- `src/trend_option_backtest/backtest.py`：回测撮合和仓位执行逻辑。
- `src/trend_option_backtest/strategies/trend_following.py`：趋势策略信号生成逻辑。
- `src/trend_option_backtest/providers/futu_provider.py`：富途历史行情和持仓只读 provider。
- `src/trend_option_backtest/models.py`：策略配置和回测结果模型。
- `tests/test_default_backtest.py`：当前核心回归测试。
- `config/default_config.json`：默认策略参数。

### 验证状态

最近一次验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

最近一次结果：

```text
8 passed
```

Streamlit 本地页面状态：

```text
http://127.0.0.1:8501 返回 HTTP 200
```

### 下一步建议

1. 优化“当前持仓”体验：导入富途持仓后自动提示哪些持仓不在当前股票池，并提供一键加入股票池。
2. 继续完善策略计划明细：增加“建议股数”和“目标仓位差额”，让参考金额更接近可执行订单。
3. 增加账户资金读取：读取富途账户现金/购买力后，用真实可用资金替代模拟初始资金生成计划。
4. 拆分 `app.py`：把持仓、计划、图表、历史记录等函数逐步移到 `src/` 下，避免主文件继续膨胀。
5. 增加富途持仓 provider 的单元测试：用 monkeypatch 模拟 SDK 返回，验证字段解析和异常处理。
6. 增加策略计划导出版本号：让每次下载的计划能追踪到策略参数、行情日期和持仓来源。
7. 中期目标是做成“策略 cockpit”：持仓、股票池、信号、风险、计划、复盘记录在同一个页面闭环。

### 回家后继续开发入口

1. 拉取仓库：`git clone https://github.com/Buffetzhu/TradingStragety.git`
2. 进入项目：`cd TradingStragety`
3. 创建或启用虚拟环境后安装依赖：`pip install -r requirements.txt`
4. 运行测试：`python -m pytest tests`
5. 启动页面：`streamlit run app.py`
6. 优先从“当前持仓导入后，一键加入股票池”这个功能继续做。

### 注意事项

- 不提交 `.venv/`、`data/*.csv`、`data/*.json`、`output/*`、`.tmp/*`。
- 富途真实行情和持仓读取依赖本机 OpenD，默认地址为 `127.0.0.1:11111`。
- 当前没有实现自动下单，也没有实现交易解锁；所有富途交易相关能力目前只读。
- 对真实账户数据要继续保持保守，先读取、展示、生成计划，再由用户手动决策。

## 版本 0.2 - 2026-05-18

### 版本定位

V2 稳定版：在 V1 回测工作台基础上，补齐富途持仓、账户资金、策略计划、期权持仓关联、可追溯导出和回归测试。当前版本仍然保持只读分析，不自动下单、不解锁交易。

### 今日检查

- 本地仓库位于 `main` 分支，最新提交为 `082dd05`，标签为 `v0.1`。
- 工作区开始开发前为干净状态。
- gstack 环境检查结果为 `GSTACK_OK`。

### V2 稳定版新增

- 当前持仓表会自动识别持仓中尚未参与本次回测的标的。
- 在“当前持仓”区域新增两个操作：
  - `加入股票池并参与回测`：把缺失持仓标的加入股票池，并加入当前回测选择。
  - `仅加入股票池`：只加入股票池，不自动参与当前回测。
- 一键加入时会保留当前多选框已有选择，不会回退到默认标的列表。
- 持仓提示文案从“手动持仓”调整为“当前持仓表”，兼容手动录入和富途导入两种来源。
- 策略计划明细新增 `建议股数` 和 `目标仓位差额`：
  - `建议股数` 按当前收盘价和参考交易金额估算。
  - `目标仓位差额` 用正负美元表示应该增仓、减仓或清仓的仓位变化。
- 富途 provider 新增账户资金只读查询能力，读取总资产、现金、购买力和计划资金基准。
- “当前持仓”区域新增 `读取账户资金`，读取后可勾选 `用账户资金估算策略计划`。
- 策略计划明细会显示当前资金来源：模拟初始资金或富途账户资金。
- 修复持仓读取和展示问题：
  - 富途持仓读取不再过滤负数量，避免卖出期权、空头或其他非零持仓被漏掉。
  - 本地持仓保存和当前持仓表识别改为保留所有非零数量。
  - 账户资金展示从三列指标卡改为表格，避免侧边栏金额被截断成 `$1,...`。
  - 当前持仓表允许输入负数量，并在提示中说明正数为多头、负数为空头或卖出期权持仓。
- 优化策略计划明细口径：`等待触发` 不再把触发后预算写入当前交易金额和目标仓位差额，避免多只观察标的显示大量相同金额；触发后预算改写在 `金额说明` 中。
- 当前持仓表、当前策略观察清单、策略计划明细新增 `市场` 列，并按市场优先排序：港股、美股、A股、新加坡、其他。
- 当前持仓表新增 `类型` 和 `正股标的`：
  - 可识别富途美股期权代码，如 `US.INTC260120C50000`。
  - 期权持仓暂不加入正股趋势回测，一键加入股票池只处理正股/ETF。
  - 期权的正股标的会先显示为后续期权 Overlay 的关联入口。
- 新增 `期权持仓关联` 视图：
  - 将期权持仓按正股标的关联到当前策略计划。
  - 显示期权类型、到期日、到期天数、行权价、持仓方向、成本价、正股计划动作和正股触发依据。
  - 增加初步 Overlay 观察建议：区分保护性 Put、现金担保 Put、备兑 Call、进攻性 Call 等角色，并给出风险提示。
  - 增加合约对应股数、正股持仓股数、保护/覆盖比例，便于观察期权仓位是否和正股仓位匹配。
  - 支持下载 `option_overlay_summary.csv`。
- 新增富途 provider monkeypatch 测试：
  - 覆盖持仓查询 `refresh_cache=True`、负数量持仓保留、`stock_code/position_qty/diluted_cost` 字段兼容。
  - 覆盖账户资金查询 `refresh_cache=True`、`total_asset/cash_balance/max_power_long` 字段兼容，以及计划资金基准选择。
- V2 稳定版增强：
  - 策略计划导出 `strategy_action_plan.csv` 增加导出时间、版本、行情日期、资金来源、持仓来源、账户信息和策略参数快照。
  - 新增富途 provider 异常路径测试，覆盖查询失败、字段缺失和空资金结果。
  - 新增 `playbooks/validate-v2-stable.md`，固化演示回归、富途只读回归和导出检查流程。
  - README 补充 V2 稳定版范围和验证入口。

### 发布验证

最近一次验证命令：

```powershell
.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\providers\futu_provider.py src\trend_option_backtest\exporting.py tests\test_default_backtest.py
.venv\Scripts\python.exe -m pytest tests
```

最近一次结果：

```text
py_compile 通过
15 passed
Streamlit 页面 HTTP 200
VS Code diagnostics 无错误
```

### 发布备注

- 版本号更新为 `0.2`。
- 本版本已经具备日常 V2 稳定版使用基础。
- 真实富途账户回归仍需在本机 OpenD 登录态下按 `playbooks/validate-v2-stable.md` 执行。

### V2 后续建议

1. 使用真实富途账户执行 `playbooks/validate-v2-stable.md`，记录真实字段和页面回归结果。
2. 优先优化易用性：减少默认页面噪音、明确每日只需要处理的动作、让新标的加入股票池和回测的路径更顺。
3. 将持仓、账户资金和期权关联函数从 `app.py` 拆到独立 service/provider 模块，降低主文件复杂度。
4. 增加富途 provider 更多边界测试，覆盖字段全为空和非法交易环境。
5. 期权 Overlay 深度增强下调优先级；短期只保留轻量提示，期权最新价、市值、盈亏和隐含波动率放到后续版本评估。

## 2026-05-19 开发记录

### 今日目标

开始 V0.3 策略 cockpit：首页先聚合“现在要处理什么”，减少每天从多个明细表里手动扫信号的成本。

### V0.3 Cockpit 初版

- 新增 `src/trend_option_backtest/cockpit.py`：
  - 汇总策略计划和期权 Overlay，生成 cockpit 指标和今日任务表。
  - 指标包括 `当前动作`、`降低风险`、`接近触发`、`期权关注`。
  - 今日任务表按当前动作、期权关注、接近触发排序。
- Streamlit 页面新增 `策略 Cockpit` 区域：
  - 放在回测核心指标之后、运行历史之前。
  - 显示资金基准、四个 cockpit 指标和今日任务表。
  - 支持下载 `cockpit_today_tasks.csv`。
- Cockpit 新增三个首页分区：
  - `风险持仓`：展示触发清仓/减仓，或贴近关键风控线的持仓。
  - `期权到期`：展示未来 30 天内到期的期权持仓。
  - `资金动作`：按计划动作汇总已触发动作的参考交易金额。
  - `今日只观察`：收纳未触发动作且未贴近关键价位的标的。
- Cockpit 新增快照功能：
  - 可将当前 Cockpit 指标、任务数量、分区数量、资金基准和已触发参考金额保存到 `data/cockpit_snapshots.csv`。
  - 页面支持查看最近 10 条快照和下载快照 CSV。
  - 快照文件按 `.gitignore` 不提交，作为本地每日复盘数据。
- Cockpit 新增可用闭环能力：
  - 今日任务表支持编辑 `状态` 和 `备注`，状态包括未处理、已处理、跳过、等待。
  - 新增风险预算指标：增风险金额、降风险金额、净风险变化、动作资金占比和潜在接股金额。
  - 新增 `今日复盘` 区域，可保存总结、已处理事项、待跟进事项和任务状态统计到 `data/cockpit_reviews.csv`。
- Cockpit 稳定版增强：
  - 新增 `Cockpit 聚焦标的`，可同步下方 `单标的价格与仓位` 图表。
  - 新增复盘完成率趋势，根据每日最新复盘记录展示任务完成率。
  - 新增周度复盘摘要，汇总复盘天数、任务数、已处理、未完成、平均完成率和净风险变化。
  - 新增真实账户回归检查入口，可记录 OpenD、持仓、资金、股票/期权隔离、回测、策略计划、风险预算和复盘更新结果。
  - 新增期权组合识别，聚焦 Vertical Spread、Straddle/Strangle 和 Collar；Covered Call、Protective Put、Cash-secured Put 保留在单腿关联角色中提示。
  - 修正组合识别口径：同一期权腿只归入一个组合，价差组合张数按配对张数计算，单腿区域只展示未归入组合的期权腿。
  - 调整页面默认值：参与回测标的默认空选，持仓交易环境默认真实账户只读，回测周期默认 6 个月，数据源默认富途真实行情。
  - 修复 `加入股票池并参与回测` 在默认空选后无法同步勾选标的的问题。
  - 优化策略计划区层级：默认展示 `今日行动计划`，将 `策略观察清单` 收进折叠区，减少重复感。
- 代码结构调整：
  - 新增 `src/trend_option_backtest/planning.py`，承载标的规范化、持仓分类、策略观察清单、策略计划和期权 Overlay 计算。
  - `app.py` 删除已被 `planning.py` 接管的旧重复实现，回到页面编排层。
  - 重建 `app.py` 为干净 UTF-8 文件，避免 Windows PowerShell 编码转换造成中文乱码。
- 页面复用同一份观察清单、策略计划和期权 Overlay 计算结果，避免后续明细区域重复构建。
- 新增 cockpit/planning 单元测试，覆盖当前动作、风险动作、接近触发、期权关注、风险持仓、到期提醒、资金动作汇总、只观察队列、快照摘要、风险预算、复盘趋势、周度复盘摘要、回归检查摘要、持仓分类、期权 Overlay 和期权组合识别。
- 新增 VS Code 任务 `启动 Streamlit 工具`，配合内置 Simple Browser 可在编辑器内预览页面。

### V0.3 Cockpit 收尾

- 版本号更新为 `0.3`。
- `真实账户回归检查` 改为 `真实账户检查清单`，说明文案强调这是用户用只读真实数据跑完页面后的人工验收记录，不会自动下单，也不会自动判断交易建议。
- `今日行动计划` 默认只展示核心字段：市场、标的、状态、计划动作、优先级、建议股数、参考交易金额、金额说明、收盘价、触发依据和计划说明。
- `策略观察清单` 默认收进折叠区，需要查看均线、前高、过热价和持仓来源时再展开。
- V0.3 定位为可日常使用的轻量 Cockpit checkpoint；后续优先做易用性，不把期权和专业指标继续做重。

### V0.3 发布验证

```powershell
.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\planning.py src\trend_option_backtest\cockpit.py tests\test_default_backtest.py
.venv\Scripts\python.exe -m pytest tests
```

最近一次结果：

```text
py_compile 通过
25 passed
VS Code diagnostics 无错误
```

### 后续优先级调整

- 产品方向：先做轻量、清晰、每天可用的个人策略工具，不追求一开始覆盖重度专业交易终端能力。
- 优先级上调：页面易用性、默认流程、错误提示、真实账户回归、策略计划可读性、Cockpit 首页信息减负。
- 优先级保持：只读安全边界、真实数据兼容、回测稳定性、导出可追溯。
- 优先级下调：期权高级分析、隐含波动率、期权希腊值、复杂组合风险建模和过多专业指标。
- 期权近期边界：只做识别、隔离、关联正股计划和基础风险提醒；不把期权模块做成主流程入口。

## 版本 0.4-dev - 2026-05-19

### V0.4 开发目标

继续按易用性优先推进，让页面打开后更快回答“我现在该做哪一步”。V0.4 不扩大期权深度，不引入自动交易，重点优化日常流程、空状态提示和行动计划阅读体验。

### V0.4 首批改动

- 版本号进入 `0.4-dev`。
- 新增 `今日流程状态`：展示回测标的数量、持仓记录数量、账户资金是否已读取、行动计划是否已生成。
- `今日流程状态` 新增数据源、账户模式和只读安全边界提示，真实账户模式下更容易确认当前只是读取数据。
- 根据当前状态给出轻量提示：未选标的、已有持仓但未参与回测、富途行情需确认 OpenD、已生成行动计划等。
- 将两个回测按钮并排展示，减少纵向占用。
- 空状态不再重复显示“准备就绪”说明，避免页面刚打开时显得啰嗦。
- 当前持仓区域改为 `当前持仓与账户资金`，默认在尚未生成行动计划时展开，并显示日常流程提示。
- 从富途读取或手动保存非空持仓后，默认开启 `用当前持仓生成今日行动计划`，减少真实持仓被忽略的风险。
- 持仓区域说明正股/ETF 会进入行动计划，期权只做隔离识别和轻量风险提示。
- 今日行动计划主表进一步减负，仅保留执行决策字段；价格、目标仓位差额、风控关注、触发依据和计划说明进入 `行动计划详情` 折叠区。
- 持仓区新增 `持仓标的参与状态`，区分已参与本次回测、在股票池但未参与回测、未加入股票池。
- 富途持仓/资金读取和行情拉取失败时，提示 OpenD、账户 ID、市场权限和代码格式等可检查项。
- Cockpit 首页继续减噪：默认显示四个核心指标；风险预算默认折叠，分区明细和聚焦摘要默认展开，方便直接查看关键上下文。
- Streamlit 宽度参数从 `use_container_width=True` 迁移为 `width="stretch"`，清理启动和页面刷新时的弃用提醒。
- 真实账户检查清单会根据当前页面状态预填结果和备注：客观可确认项自动标记通过，需要人工判断的计划、期权和风险预算保留为需复核。
- Cockpit `期权到期` 分区改为组合优先展示：已识别为多腿组合的合约不再重复按单腿列出，未归入组合的单腿继续作为补充提醒。
- Cockpit 任务表和风险预算同步改为组合优先：组合腿不再重复进入期权关注、潜在接股和未充分备兑统计，价差组合单独估算 `组合价差风险金额`。
- 风险预算新增明细表，逐行展示股票增/降风险动作、组合价差风险、未归入组合的空头 Put 接股风险和未充分备兑 Call，便于核对预算来源。

### V0.4 后续建议

1. 用真实账户跑一轮 V0.4 页面回归，确认流程状态、持仓参与状态、今日行动计划详情和 Cockpit 折叠层级符合预期。
2. 根据真实账户反馈微调字段顺序和文案。
3. 保持期权区域轻量，只做识别、隔离和基础风险提醒。

## 版本 0.5-dev - 2026-05-19

### V0.5 开发目标

在不引入自由策略代码和复杂策略 DSL 的前提下，先提供几套可快速切换的参数模板，让同一套趋势策略可以用稳健、激进、防守等风格回测比较。

### V0.5 首批改动

- 版本号进入 `0.5-dev`。
- 新增 `src/trend_option_backtest/strategy_templates.py`，集中定义策略模板和模板应用函数。
- 侧边栏新增 `策略模板` 选择，当前内置 `GPT 趋势默认`、`稳健趋势`、`激进突破`、`防守观察`。
- 应用模板时保留当前股票池、参与回测标的、持仓和账户状态，只替换策略参数和 `strategy_name`。
- 应用模板前展示 `模板参数差异`，列出将变化的参数、当前值和模板值，避免盲目切换。
- 当前策略摘要和回测历史新增模板来源，便于后续比较不同策略风格。
- 回测运行历史新增按策略模板分组的表现摘要，并支持按模板筛选运行明细；旧历史缺少模板字段时归为 `未记录模板`。
- 增加策略模板回归测试，确认模板参数会生效且不会丢失股票池和回测标的。

### V0.5 后续建议

V0.5 到这里先收口，不继续追加功能。当前系统已经开始显得臃肿，下一步优先做产品减负审视，而不是继续增加模板、图表或导出入口。

### 下一轮重新审视重点

1. 梳理首页主路径：保留每天真正要看的内容，折叠或移走低频功能。
2. 区分“每日决策必需”和“调试/复盘/研发辅助”：避免所有能力都堆在同一页面。
3. 检查 Cockpit、今日行动计划、期权关联、回测历史之间是否有重复信息。
4. 决定 V0.6 是否先做减法：例如拆页面、隐藏高级区块、合并重复表格，而不是继续加新分析能力。
5. 真实账户只读和不自动交易仍是硬边界，任何精简都不能削弱安全提示。

## 版本 0.6-dev - 2026-05-20

### V0.6 开发目标

页面减负 + 工作区拆分。把原先单页面里"模拟研究 / 账户追踪"两类信息混在一起的问题彻底分开，让用户进入页面后能按当前意图（看历史回测 vs 跟真实账户每日操作）直接命中所需视图，而不是从满屏控件里挑。

### V0.6 落地改动

- 版本号进入 `0.6-dev`，`__version__` 同步到 `0.6.0.dev0`。
- 页面顶部新增 `工作模式` radio：`模拟研究 / 账户追踪`，`show_simulation` / `show_account` 双开关贯穿全局。
- 模拟工作区抽出为 `_render_simulation_workspace()`，封装单标的图 + 回测运行历史；账户工作区用 `# ===== 账户追踪工作区 =====` 分段标记，去掉末尾冗余的 `if show_account:` 守卫。
- 账户模式下默认隐藏 `回测周期` 下拉和 `模拟初始资金` 输入，资金优先取账户购买力，并在原位置加 caption 说明。
- 侧栏新增 `数据接入` expander，把 `数据源` radio、OpenD 地址/端口、缓存刷新、测试连接按钮全部收进去；账户模式默认折叠。
- 侧栏 `当前持仓与账户资金` expander 仅在账户模式渲染；`策略规则参数` expander 在账户模式默认折叠。
- 主区账户模式顶部新增提示 `📌 当前策略来源：xxx` 让模板选择直接可见，并补一个 `🔄 一键刷新持仓 + 重跑今日策略` 主按钮：用 session_state 里的 OpenD 配置 re-fetch 持仓和账户资金，写入 `auto_run_backtest` 标志并 `st.rerun()`，下一轮 `run_default` 自动检测该标志触发回测；成功/失败统一通过 `st.toast` 跨 rerun 显示。
- 账户工作区顶部新增 `账户快照` 板块：4 列 metric 显示总资产 / 现金 / 购买力 / 持仓条目（正股+期权），未读账户资金时显示"未读取"占位并附操作提示。
- `当前策略摘要` / `回测结果与权益曲线` 两个 expander 在账户模式下默认折叠并改名为 `策略历史回测参考（与你账户无关）` / `策略历史回测结果（仅供参考）`，加 caption 说明指标是 ,000 × 6 月窗口的纯模拟结果。
- `今日行动计划` 由表格改为按优先级排序的 Top 5 卡片：每张卡片用 `st.container(border=True)` 渲染计划动作·标的 + 优先级 metric + 参考金额 metric + 副行 metadata + 触发依据 + 计划说明；完整表格收进 `全部行动计划表` 折叠面板，行动计划详情 / CSV 下载保留。
- 修复 `use_current_positions_for_plan` widget 在主区 rerun 时报"cannot be modified after the widget is instantiated"的问题：用 `_pending_use_current_positions` 标志，等下一轮侧栏 checkbox 渲染之前消费。
- 修复单标的图表 `查看标的` 选择器被 Cockpit 聚焦标的强制覆盖、手动切换失败的问题：记录 `_last_synced_focus_symbol`，仅在 Cockpit 聚焦真正变化时同步一次。
- README 同步双工作区叙事；新增 `V0.6 开发方向` 和 `双工作区使用指南` 章节。

### V0.6 后续建议

- 把账户工作区也抽到 `src/trend_option_backtest/workspaces.py`，让 `app.py` 只保留 dispatcher 和共享 compute（当前仍 1100+ 行）。
- 实装 `账户对齐回测`：让回测引擎支持 `initial_positions`，账户工作区的"策略历史回测参考"才能变成真正与账户挂钩的对齐口径；本轮先用 caption 方向 A 兜底标注。
- 真实富途账户跑一轮全流程回归，按 V0.4 收尾建议闭环字段顺序和文案。
- 补一个一键环境自检脚本（Python 依赖 + OpenD 在线 + 缓存目录），让 `validate-v2-stable.md` 有离线兜底路径。

### V0.6-dev 后续四件套（2026-05-21）

- 新增 `scripts/check_env.py`：一键检查 Python 依赖、关键目录、OpenD TCP/握手；支持 `--skip-opend`，退出码区分 FAIL/PASS。已在本机跑通 exit 0。
- 新增 `scripts/smoke_account.py`：只读冒烟测试，依次走 OpenD 连接 → 账户资金 → 持仓列表，全程不下单不解锁，便于真实账户验收前快速核对。
- 新增 `playbooks/validate-v06-workspaces.md`：把 8 步 V0.6 验收流程串起来（环境自检 → 单元测试 → 账户冒烟 → 页面 → 双工作区 → 一键刷新 → 行动计划 → 导出）。
- `BacktestEngine` 与 `BacktestService` 新增 `initial_positions` 参数（`{symbol: {shares, cost_basis}}`）：账户模式下勾选"账户对齐回测"会用真实持仓种子化 `_run_single_symbol`，cash 自动扣除成本基；策略摘要给出 ✅ 提示。
- 拆出 `src/trend_option_backtest/workspaces.py`：定义 `WorkspaceContext` dataclass（数据 + 持久化回调），将 `_render_single_symbol_chart` / `render_simulation_workspace` / `render_account_workspace` 全部迁出 `app.py`，主文件 dispatcher 仅构造 ctx 后分发；33 个单元测试和 `py_compile` 仍通过。

## 版本 0.5 - 2026-05-20

### 版本定位

V0.5 收口：在 0.6-dev 期间累积的双工作区拆分、`workspaces.py` 抽取、`initial_positions` 种子化、环境自检脚本等基础上，做了一轮 UI / 可视化加固和图表细节修复，把配置面板从"调试器表单"重做成"控制面板卡片"。版本号正式落到 `0.5`，`__version__` 同步到 `0.5.0`。

### V0.5 落地改动

**Bug 修复**

- 修复"保存持仓"按钮后立即写 `use_current_positions_for_plan` 报 `SessionState 不能在 widget 实例化后修改`：改用 `_pending_use_current_positions` 标志 + 下一轮 rerun 消费的模式，支持 True/False 显式区分。
- 修复单标的图表上买卖三角形标记在 `workspaces.py` 抽取后丢失：恢复 `result.trades` 按动作着色（绿三角=买/加，红三角=减/清/期末平仓）。
- 修复收益率曲线点击买卖时 `KeyError: ['return_pct']`：策略组合曲线列被重命名为 `cum_return_pct` 后再与 `trades` 做 `pd.merge_asof(direction="backward")`，避免与单笔交易 dict 自带的 `return_pct` 字段冲突。

**新增图表特性**

- 单标的图表副轴 Y2 增加策略组合"收益率曲线"（紫色虚线 `#9333EA`），数据来源 `result.symbol_equity_curve[symbol] / base_capital - 1`，与价格主轴并排显示。
- 在收益率曲线上叠加买卖圆点（绿圆=买入/加仓，红圆=减仓/清仓/期末平仓），与价格轴上的三角标记时间对齐，便于直接看每笔交易对组合收益的边际影响。

**布局重做**

- 删除原 `st.tabs(["🎯 策略与数据", "💼 账户与持仓"])` 切换，改为全宽 `st.container(border=True)` 卡片：策略卡 + 账户卡（仅账户模式）并列堆叠，宽度与下方摘要 / 结果卡保持一致。
- 策略卡内部重新分栏：
  - 顶部 4 列：`策略模板`（宽）/ `回测周期` / `初始资金` / `🔄 恢复默认`（按钮通过 `<div style='height: 1.55rem;'>` 占位与左侧 label 基线对齐）。
  - 中部：模板描述 caption + 条件性 `应用模板` 按钮和 `模板参数差异` expander + 全宽 `参与回测标的` multiselect。
  - 底部 4 列折叠抽屉：`➕ 扩展标的池` / `📡 数据接入` / `⚙️ 策略规则参数` / `💾 参数预设`，把之前堆在 tab 里的高级控件统一收进抽屉。
  - 收尾行：参数状态 caption + `保存当前预设` 按钮（3:1 分栏）。
- 运行按钮独立成居中操作条：`[1, 3, 1]` 外夹白 + 两个等宽按钮（`▶ 运行默认回测` / `运行当前参数回测`），不再随配置区被拉宽。

**视觉风格**

- 主区 `block-container` 限宽 1200px 居中，避免大屏下控件被无限拉伸。
- 配置卡 / 账户卡：白底、`#E2E8F0` 边框、14px 圆角、轻阴影；卡内 `stExpander` 改成浅灰内嵌（`#F8FAFC` 底、8px 圆角），避免卡上叠卡的笨重感；输入控件统一 8px 圆角，label 字号 0.82rem / 偏灰 `#475569`。
- 按钮统一圆角 8px；主按钮加蓝色渐变 + 悬停阴影。

**文档与版本**

- `VERSION` → `0.5`，`src/trend_option_backtest/__init__.py:__version__` → `0.5.0`。
- `README.md` 同步当前版本号。

### V0.5 验证

- `python -m py_compile app.py` 通过。
- `python -m pytest tests -q` → 33 passed。
- 本地 Streamlit `http://127.0.0.1:8501` 启动返回 200。

### V0.5 已知遗留 / 下一步

- 顶部 `🔄 恢复默认` 与左侧 `初始资金` 输入框基线对齐用了固定 `1.55rem` 占位高度，依赖 Streamlit 默认主题；若主题字号变化需重新校准。
- `app.py` 仍约 1130 行，配置卡内部 4-抽屉布局可继续抽到独立 `render_config_panel(ctx)` 模块；下一轮做减法时一并处理。
- 账户模式下 "💼 账户与持仓" 卡内部分栏仍沿用旧 2 列结构，未跟随策略卡同步重排，留待 V0.6 处理。

## 版本 0.8 - 2026-05-22

### 版本定位

V0.8 不动业务代码，只新增 Macbook 远程部署套件，目标是让家里 Macbook 24h 在线、任意设备（手机 / 公司 Windows / 出差笔记本）通过 Cloudflare Tunnel HTTPS 访问同一份数据，达成多端同步阅读。架构上明确分工：**公司 Windows 主力开发、git push 同步代码；家里 Macbook git pull + 跑生产 + 跑 OpenD + 暴露隧道**。

### V0.8 落地改动（Windows 侧已完成）

**新增文件（业务代码 0 改动）**

- `deploy/start_app.sh` — Streamlit 启动脚本，含 OpenD 端口自检 + venv 激活 + 日志落盘。
- `deploy/com.trading.streamlit.plist` — launchd 守护模板，登录自启 + 崩溃自动重启（`KeepAlive` + `ThrottleInterval` 10s）。
- `deploy/cloudflared/config.yml.example` — Cloudflare Tunnel 路由配置模板，把 `trading.example.com` → `http://127.0.0.1:8501`。
- `deploy/README.md` — Macbook 一步步部署清单：基础依赖、克隆仓库、防睡眠、launchd 注册、Tunnel 创建、Access 邮箱白名单、故障排查、日常 git pull 流程、数据架构说明。
- `deploy/.gitignore` — 排除 `logs/`。

**配置追加**

- `.streamlit/config.toml` 新增 `[server]` 段：`headless = true` / `address = "127.0.0.1"` / `enableXsrfProtection = false` / `enableCORS = false`。隧道反向代理时来源域名会变，必须关 XSRF；只绑 127.0.0.1 是因为 cloudflared 在本机连过去，不需要对外暴露端口。

**版本同步**

- `VERSION` → `0.8`，`src/trend_option_backtest/__init__.py:__version__` → `0.8.0`（顺手修复 0.7 时漏同步的 0.6.0）。

### V0.8 待 Macbook 回家执行（不在 Windows 端可完成）

按 `deploy/README.md` 顺序执行：

1. **拉代码**：`git clone` 或 `git pull` 到 `~/code/TradingStragety`。
2. **装依赖**：`brew install python@3.13 cloudflared netcat`；富途 OpenD Mac 版从官网装；`python3.13 -m venv .venv` + `pip install -r requirements.txt`。
3. **防睡眠**：系统设置 → 电池 → 电源适配器 → 「合上盖子时防止自动睡眠」。
4. **注册 launchd**：`sed` 替换 plist 里 `__REPO_ROOT__` → 拷贝到 `~/Library/LaunchAgents/` → `launchctl load`，验证 `curl -I http://127.0.0.1:8501` 返回 200。
5. **试临时 Tunnel**（最小可用闭环）：`cloudflared tunnel --url http://127.0.0.1:8501`，输出 `https://xxx.trycloudflare.com` 临时 URL，立刻能用，关掉就失效。
6. **（可选）正式 Tunnel + 域名**：`cloudflared tunnel login` → `cloudflared tunnel create trading` → 改 `~/.cloudflared/config.yml` → `cloudflared tunnel route dns trading <domain>` → `sudo cloudflared service install`。
7. **（强烈建议）加 Access**：Cloudflare Zero Trust → Applications → 邮箱 OTP 白名单，防陌生人扫到域名。

### V0.8 数据架构说明

`.gitignore` 已经排除 `data/*.csv|*.json|*.db`，所以：

- **代码** 通过 git 同步（Windows ↔ GitHub ↔ Macbook）。
- **数据**（持仓、回测历史、复盘、账户快照）只在 Macbook 上，是唯一生产数据源。
- 多设备访问 = 通过 Tunnel 访问 Macbook 的 Streamlit；数据天然不会冲突，无需做云数据库。
- 副作用：公司想用真实数据开发，得手动 `scp` 一份 `data/` 过来。

### V0.8 验证

- Windows 侧只新增静态文件 + 配置，`python -m py_compile app.py` 通过；`python -m pytest tests -q` 维持 33 passed（业务代码 0 改动）。
- Macbook 侧验证留待回家执行 README 第 5 步（临时 Tunnel）后做端到端测试。

### V0.8 已知遗留 / 下一步

- `deploy/start_app.sh` 假定 OpenD 已经手动从 GUI 启动；OpenD 没有官方 CLI 启动方式，暂不自动化。后续可考虑用 AppleScript 包一层。
- 临时 trycloudflare URL 每次重启会变，不适合长期收藏；想稳定 URL 需要自有域名（约 ¥60/年）。
- 暂未做 git push → Macbook 自动 pull + reload 的 webhook，每次更新需手动 `git pull` + `launchctl unload/load`。
- 多设备并发写入未加文件锁；单用户场景不会触发，多人/自动化场景需评估。

