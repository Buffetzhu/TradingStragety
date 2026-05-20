# Playbook: 验证 V0.6 稳定版（双工作区 + 账户对齐）

## 目的

确认 V0.6 双工作区（模拟研究 / 账户追踪）和账户对齐回测在真实富途账户下能完整跑通：环境就绪 → 账户读取 → 模拟回测 → 账户工作区行动计划 → 导出。

## 前提条件

- 已完成 `playbooks/setup-project.md`
- Python 依赖已安装；`futu-api` 已安装
- OpenD 已运行在 `127.0.0.1:11111` 并完成账户登录
- Streamlit 应用可通过 `streamlit run app.py` 启动

## 步骤

1. [环境自检] `.venv\Scripts\python.exe scripts\check_env.py`
   - 不带 OpenD 时加 `--skip-opend`
   - 期望：全部 OK 或仅 WARN，退出码 0
2. [静态验证] `.venv\Scripts\python.exe -m py_compile app.py src\trend_option_backtest\providers\futu_provider.py tests\test_default_backtest.py`
3. [单元测试] `.venv\Scripts\python.exe -m pytest tests -q`
   - 期望：33+ 通过，0 失败
4. [账户冒烟] `.venv\Scripts\python.exe scripts\smoke_account.py --market US --env REAL`
   - 期望：OpenD 连接 OK、账户资金 OK、持仓行数已打印
5. [页面启动] `.venv\Scripts\streamlit.exe run app.py --server.address 127.0.0.1 --server.port 8501`
6. [模拟工作区回归]
   - 切到「模拟研究」工作模式
   - 默认参数运行回测，确认：回测结果展开、权益曲线渲染、单标的图可切换、回测历史可见
7. [账户工作区回归]
   - 切到「账户追踪」工作模式
   - 点「🔄 一键刷新持仓 + 重跑今日策略」，确认顶部出现 `🔄 刷新成功` toast
   - 确认账户快照 4 个 metric 全部有数值（不再是「未读取」）
   - 确认今日行动计划 Top 5 卡片渲染正常
   - 确认 Cockpit 风险预算 / 分区明细 / 任务表格无报错
8. [导出检查] 下载 `strategy_action_plan.csv` 和 `option_overlay_summary.csv`，确认字段齐全

## 判断标准

- 若环境自检 FAIL，停在 #1，不继续；先 `pip install -r requirements.txt` 或排查 OpenD
- 若账户冒烟 FAIL，停在 #4；常见原因：OpenD 未登录、acc_id 不存在、市场选错
- 若账户工作区 toast 失败：检查 sidebar 「持仓 OpenD 地址 / 端口 / 市场 / 交易环境」是否正确
- 若期权对应正股未参与回测，应在期权关联区显示「未纳入回测」，不视为错误
- 若策略计划导出缺少快照字段，优先修复 `build_strategy_plan_export_frame`

## 验证

- 环境自检退出码 0
- pytest 全部通过
- 账户冒烟显示真实总资产/购买力/持仓行数
- Streamlit HTTP 200，两个工作区切换无报错
- 账户工作区一键刷新触发 toast + 自动回测
- 行动计划 Top 5 卡片可见，CSV 导出含全部快照字段
