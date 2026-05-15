# Playbooks & Scripts - Agent 工作框架说明

按照两层框架执行任务：**Playbooks（协调层）-> Scripts（执行层）**

- **Playbooks**：存放在 `playbooks/` 的结构化流程文件。描述"应当发生什么"，包含默认执行路径、已知分叉判断标准，以及兜底目的（未覆盖分支回归到目标）。
- **Scripts**：`scripts/` 下的确定性脚本（.sh / .py），负责文件操作、API 调用、数据转换等具体执行。相同输入永远产生相同输出。

---

## 目录结构

```text
项目根目录/
├── CLAUDE.md                  # 本文件
├── playbooks/                 # 协调层：Playbook 定义（Markdown）
├── scripts/                   # 执行层：确定性脚本（.sh/.py）
├── src/                       # 项目源代码
├── tests/                     # 测试文件
└── .tmp/                      # 临时文件（处理中间产物，不提交）
```

---

## Playbook 编写规范

每个 Playbook 必须包含以下五个章节。

```markdown
# Playbook: [名称]

## 目的
[执行完成后，什么发生了变化（一句话结果描述，不写过程）]

## 前提条件
- [文件、环境变量、依赖（缺失时在步骤开始前报错，不进入步骤）]

## 步骤
1. [脚本调用] `scripts/xxx` - 输入什么，输出什么
2. [判断] 基于什么条件，可能走向哪里

## 判断标准
- 遇到 [情况 A] 时，选 X 而非 Y，理由是 [...]
- （若本流程线性执行无分叉，写明："本流程线性执行，无需预定义判断标准。"）

## 验证
- [执行完成后，如何确认结果符合预期]
```

"目的"是所有预置判断未覆盖情况时的兜底依据。"判断标准"把可预见分叉提前声明，未覆盖时回到"目的"自行决策。

---

## Script 编写规范

- **单一职责**：一个 Script 只做一件事
- **确定性**：相同输入必须产生相同输出，不包含任何 AI 调用或随机逻辑
- **独立运行**：可脱离 Playbook 单独在命令行执行和调试
- **清晰输入输出**：命令行参数接收输入，stdout 返回结果，exit code 表示成功/失败

```bash
#!/bin/bash
# 用途：检查当前项目缺失的依赖
# 参数：无
# 输出：逐行输出缺失依赖包名称，全部已安装则无输出
# 退出码：0=执行完成，1=执行出错
# Known Issues: （发现的边界情况记录在此）
```

**逻辑固定或会重复执行 -> 写成 Script；需要理解上下文、做主观判断 -> 在 Playbook 中处理。**

---

## 纠错反馈循环

Script 执行失败时，按以下五步完成修复：

1. 报告错误：展示完整错误输出，说明失败的 Script 和步骤
2. 分类错误：判断属于以下哪类（分类决定修复位置）
   - A. Script bug -> 修改 `scripts/` 对应脚本
   - B. 步骤设计有误 -> 更新 Playbook 的“步骤”章节
   - C. 判断标准缺失 -> 补充 Playbook 的“判断标准”章节
   - D. 环境/配置问题（修复项）-> 更新 Playbook 的“前提条件”章节
3. 修复：按分类结果，只改对应位置，不做超出范围的改动
4. 重新验证：再次运行，确认输出符合预期
5. 更新记录：
   - Script bug（类型 A）：将边界情况补充到 Script 头部的 Known Issues
   - Playbook 变更（类型 B/C/D）：已在步骤 2-3 中完成

修复后必须更新文档，避免重复踩坑。临时文件放 `.tmp/`，不要覆盖未知识别文件。

---

## 执行规则

### 执行任务时

1. 查阅 `playbooks/` 目录，寻找匹配当前任务的 Playbook
2. 找到 Playbook 后，先核查“前提条件”章节，确认满足后再进入步骤
3. 执行步骤时，遇到分叉查“判断标准”章节；未覆盖时参考“项目判断原则”；两者都未覆盖时，以 Playbook 的“目的”为准自行决策并说明推理
4. 没有匹配的 Playbook 时，先判断是否值得创建新 Playbook，再开始工作
5. 非明确要求下，直接命令行调用 Script，不在其他代码中模拟 Script 行为
6. 优先复用已有 Script，不重复造轮子

### 编写代码时

1. 不把判断逻辑写进 Script，Script 内容应当是确定性的
2. 新建 Script 时遵循头部注释规范，确保可独立运行
3. 新建 Playbook 时包含全部五个章节
4. 修改现有 Script 前，先运行一次确认当前行为，改完后再次运行验证
5. 单次变更较大时，拆分为可独立验证的子步骤，逐段编写并验证后继续

---

## 沟通风格

所有输出和沟通必须使用中文（代码注释除外）。

1. 执行 Playbook 时，每完成一个步骤都要报告结果，再继续下一步
2. 遇到需要判断的环节，说明推理过程和选择依据
3. Script 执行失败时，先展示错误输出，再按纠错反馈循环处理

---

## gstack
使用 gstack 的 `/gstack-browse` 处理所有网页浏览和页面测试。
不要使用 `mcp__claude-in-chrome__*` 工具。

本项目要求使用全局安装的 gstack。开始任何 AI 辅助工作前，先确认：

```bash
test -d ~/.codex/skills/gstack/bin && echo "GSTACK_OK" || echo "GSTACK_MISSING"
```

如果输出 `GSTACK_MISSING`，停止当前工作并重新安装：

```bash
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/gstack
cd ~/gstack && ./setup --host codex --prefix --team
```

可用技能：
- `/gstack-autoplan`
- `/gstack-benchmark`
- `/gstack-benchmark-models`
- `/gstack-browse`
- `/gstack-canary`
- `/gstack-careful`
- `/gstack-context-restore`
- `/gstack-context-save`
- `/gstack-cso`
- `/gstack-design-consultation`
- `/gstack-design-html`
- `/gstack-design-review`
- `/gstack-design-shotgun`
- `/gstack-devex-review`
- `/gstack-document-release`
- `/gstack-freeze`
- `/gstack-guard`
- `/gstack-health`
- `/gstack-investigate`
- `/gstack-land-and-deploy`
- `/gstack-learn`
- `/gstack-make-pdf`
- `/gstack-office-hours`
- `/gstack-open-gstack-browser`
- `/gstack-pair-agent`
- `/gstack-plan-ceo-review`
- `/gstack-plan-design-review`
- `/gstack-plan-devex-review`
- `/gstack-plan-eng-review`
- `/gstack-plan-tune`
- `/gstack-qa`
- `/gstack-qa-only`
- `/gstack-retro`
- `/gstack-review`
- `/gstack-setup-browser-cookies`
- `/gstack-setup-deploy`
- `/gstack-ship`
- `/gstack-unfreeze`
- `/gstack-upgrade`

### Windows 兼容说明（Bun / bunx）

- 推荐在 Git Bash 或 WSL 中执行 `./setup --host codex --prefix --team`。
- Windows 下除 Bun 外还需要 Node.js，用于 Playwright 和 browse server 的兼容回退。
- 若 PowerShell 中 `bash` 不在 PATH，可直接调用 `C:\Program Files\Git\bin\bash.exe`。
- 若出现 `bunx: command not found`，可用 `bun x` 作为等价替代。
- 若 Bun 通过 winget 安装后未自动进 PATH，可先临时追加 Bun 路径后再执行 setup。

```bash
export PATH="/c/Users/<你的用户名>/AppData/Local/Microsoft/WinGet/Packages/Oven-sh.Bun_Microsoft.Winget.Source_8wekyb3d8bbwe/bun-windows-x64:$PATH"
cd ~/gstack && ./setup --host codex --prefix --team
```

## Skill routing

- 用户提到“debug”“报错”“500”“异常”“为什么坏了”“帮我自己查”时，优先使用 `/gstack-investigate`，先做根因定位，再实施修复。
- 用户提到“打开页面”“跑浏览器”“验证页面”“自己点一遍”“自己看 console / network”时，优先使用 `/gstack-browse` 执行网页复现与回归验证。
- 需要可见浏览器窗口、登录态调试或希望实时观看 AI 操作浏览器时，优先使用 `/gstack-open-gstack-browser`。
- 只要问题涉及本地网页或 Web API，不要等待用户手工复制控制台报错；应优先启动本地服务，自行访问页面、收集报错并完成首次定位。
- 执行调试任务时，默认先查看 `playbooks/ai-autodebug-loop.md`；若适用，则按该 Playbook 执行并在每个关键步骤后汇报结果。
