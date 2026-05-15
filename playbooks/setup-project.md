# Playbook: 初始化策略工作台工程

## 目的
项目具备 Playbooks/Scripts 结构、默认策略配置、可运行回测入口和 V1 Streamlit 骨架。

## 前提条件
- 当前目录为 `D:\project\TradingStragety`
- Python 可用
- 目录下存在 `CLAUDE.md`

## 步骤
1. [结构检查] 运行 `scripts/check_structure.ps1`，确认基础目录完整。
2. [数据库初始化] 运行 `scripts/init_db.py`，创建 SQLite 表。
3. [默认回测] 运行 `scripts/run_backtest.py --demo`，验证默认策略可执行。

## 判断标准
- 若结构检查失败，补齐缺失目录后重试。
- 若数据库初始化失败，按错误类型修复 `scripts/init_db.py` 或数据库路径配置。
- 若默认回测失败，优先检查策略配置、示例数据和回测引擎。

## 验证
- `scripts/check_structure.ps1` 无输出且退出码为 0。
- `scripts/init_db.py` 输出数据库路径。
- `scripts/run_backtest.py --demo` 输出总收益率、最大回撤、Sharpe、交易次数。