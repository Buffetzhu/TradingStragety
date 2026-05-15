# Playbook: 拉取富途历史行情

## 目的
将指定标的的历史日 K 数据从富途 OpenD 拉取到本地缓存，供 V1 回测使用。

## 前提条件
- 已完成 `playbooks/setup-project.md`
- OpenD 已运行，默认地址为 `127.0.0.1:11111`
- 已安装 `futu-api`

## 步骤
1. [环境检查] 确认 `.venv` 可用并已安装依赖。
2. [行情拉取] 运行 `scripts/fetch_data.py --symbols AMD,NVDA --years 2`。
3. [缓存确认] 检查 `data/cache/` 下是否生成对应 CSV。

## 判断标准
- 若 OpenD 连接失败，先确认 OpenD 是否启动、端口是否为 11111。
- 若单个标的失败，记录失败标的，不影响其他标的缓存。
- 若代码无市场前缀，默认按美股补全为 `US.<symbol>`。

## 验证
- 脚本输出每个标的的缓存路径和行数。
- 缓存 CSV 包含 `date, symbol, open, high, low, close, volume` 字段。