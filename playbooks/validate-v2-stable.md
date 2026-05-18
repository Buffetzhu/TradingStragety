# Playbook: 验证 V2 稳定版

## 目的

确认 V2 能读取富途持仓和账户资金，生成可追溯策略计划，并正确隔离和关联期权持仓。

## 前提条件

- 已完成 `playbooks/setup-project.md`
- Python 依赖已安装
- Streamlit 应用可通过 `streamlit run app.py` 启动
- 若验证真实富途数据，OpenD 已运行在 `127.0.0.1:11111`，并已安装 `futu-api`

## 步骤

1. [静态验证] 运行 `.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\providers\futu_provider.py tests\test_default_backtest.py`，确认核心文件可编译。
2. [单元测试] 运行 `.venv\Scripts\python.exe -m pytest tests`，确认回测、富途 provider 和导出快照测试通过。
3. [页面启动] 运行 `.venv\Scripts\streamlit.exe run app.py --server.address 127.0.0.1 --server.port 8501`，打开 `http://127.0.0.1:8501`。
4. [演示回归] 使用“演示数据”运行默认回测，确认回测结果、观察清单、策略计划明细、期权持仓关联区域无报错。
5. [富途只读回归] 在“当前持仓”区域读取持仓和账户资金，确认正股/ETF 加入策略计划，期权只进入期权持仓关联视图。
6. [导出检查] 下载 `strategy_action_plan.csv` 和 `option_overlay_summary.csv`，确认策略计划导出包含版本、行情日期、资金来源、持仓来源和策略参数快照。

## 判断标准

- 若 OpenD 不可用，只完成静态验证、单元测试、页面启动和演示回归；真实富途回归标记为未验证。
- 若富途返回部分标的行情失败，保留成功标的继续验证，并记录失败标的。
- 若期权对应正股未参与回测，应在期权持仓关联中显示未纳入回测，并提示先将正股加入股票池。
- 若策略计划导出缺少快照字段，应优先修复导出逻辑，再继续后续验证。

## 验证

- `pytest` 全部通过。
- Streamlit 页面 HTTP 200。
- 策略计划明细不包含期权标的。
- 期权持仓关联显示期权类型、到期天数、行权价、覆盖/保护比例、Overlay 角色、观察建议和风险提示。
- `strategy_action_plan.csv` 包含 `导出时间`、`应用版本`、`行情开始日期`、`行情结束日期`、`资金来源`、`持仓来源`、`策略参数快照`。
