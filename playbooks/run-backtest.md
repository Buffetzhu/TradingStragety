# Playbook: 运行 V1 默认趋势回测

## 目的
使用 `GPT_Trend_Default_v1` 默认参数完成一次趋势策略回测并输出核心指标。

## 前提条件
- 已完成 `playbooks/setup-project.md`
- Python 依赖已安装
- 默认策略配置存在于 `config/default_config.json`

## 步骤
1. [默认回测] 运行 `scripts/run_backtest.py --demo`，使用内置演示数据验证引擎。
2. [真实数据回测] 后续接入数据缓存后运行 `scripts/run_backtest.py`。

## 判断标准
- 若只验证代码逻辑，使用 `--demo`。
- 若验证真实策略表现，使用富途或缓存数据。

## 验证
- 输出包含总收益率、最大回撤、Sharpe、胜率、Profit Factor、交易次数。