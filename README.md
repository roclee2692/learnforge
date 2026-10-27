# LearnForge v0.2

AI 驱动的长期学习系统。第一批学科包：操作系统（os）、数据库原理（db）。

- 代码（引擎 + 技能 + MCP 服务 + 界面）：`/Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge`
- 你的数据（私有）：`/Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge-data`
- 项目上下文（目标、设计理念、进度、下一步）：`CONTEXT.md`，新协作者先读这份
- 设计决定、v0.2 多宿主架构、各宿主接入状态：`/Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge/docs/decisions.md`

## 安装

```bash
uv tool install --python 3.13 -e '.[book]'
```

```bash
lf init-data ~/learnforge-data
```

第二条会建好你的私有数据仓库，并装入自带的操作系统、数据库学科包和两套诊断卷。

## 三种用法，同一份数据

| 用法 | 怎么开 | 体验 |
|---|---|---|
| 独立网页 | 终端运行 `lf serve --open` | 浏览器里刷题、看复习面板；讲题用你的 API key，或复制提示词到任意 AI |
| 聊天里的界面 | Claude 桌面版（已配置，重启生效） | 对话里直接出现题卡，交卷当场判分记账 |
| 纯文字插件 | Claude Code、Codex 已接入；DeepSeek Harness 在 设置 → 插件 里加 stdio 命令 `/Users/raelon/.local/bin/lf`，参数 `mcp` | 模型逐题出给你，判分记账照样走引擎 |

## 怎么用

在 Claude Code、DeepSeek Harness、Codex 或 OpenClaw 里直接说话就行，四个技能已经装好：

| 你说 | 触发 | 做什么 |
|---|---|---|
| “做一下 OS 诊断卷” / “考考我页面置换” | lf-quiz | 出题、三级提示、判分、记错因 |
| “讲一下银行家算法” | lf-teach | 摸底 → 讲机制 → 引擎算例题 → 你讲回来 → 一道题验证 |
| “今天学什么，我有 45 分钟” | lf-review | 按遗忘程度 × 考试权重 × 错因排序，说明理由 |
| “数据库考试是 1 月 10 号” / “这是往年卷” | lf-plan | 改学科包、导入教材和真题、留盲测卷 |

第一次用，建议先做两套诊断卷（各 20 题、100 分），做完系统就知道你哪里弱了。

## 命令行（可以不用，技能会替你调）

```bash
lf serve --open
```

```bash
lf today --minutes 60
```

```bash
lf stats --pack os
```

```bash
lf paper db
```

```bash
lf calc os.page_replace '{"frames":3,"refs":[7,0,1,2,0,3,0,4,2,3,0,3,2,1,2,0,1,7,0,1],"algo":"LRU"}'
```

```bash
lf sql db "SELECT Sname FROM Student WHERE NOT EXISTS (SELECT * FROM SC WHERE SC.Sno=Student.Sno AND Cno='1')" --dataset school_edge
```

```bash
lf pack os set exam_date 2027-01-10
```

```bash
lf book add os /Users/raelon/Downloads/计算机操作系统.pdf
```

全部命令：`lf --help`；全部验算器：`lf calc --list`。所有命令加 `--json` 输出 JSON。

## 盲测卷

拿到往年真题后，留一套最新的不练，交给 lf-plan 锁进 `holdout/`。考前自己在终端里做（模型不参与、看不到题）：

```bash
lf holdout run os
```

## 开发

```bash
cd /Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge && ~/.local/share/uv/tools/learnforge/bin/python -m unittest discover tests
```

```bash
cd /Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge-data && lf verify
```

引擎是可编辑安装（`uv tool install -e`），改代码立即生效。

| 模块 | 作用 |
|---|---|
| `store.py` | 数据仓库定位、JSONL 读写、盲测卷锁 |
| `verifiers/` | OS：调度、银行家、页面置换、磁盘、地址变换、混合索引、位示图；DB：闭包、候选码、范式、最小依赖集、3NF/BCNF 分解、无损判定、可串行化、日志恢复、SQL 判分 |
| `grade.py` | 判分与出题质检 |
| `fsrs.py` / `model.py` | 按知识点的 FSRS 掌握度、复习排序、统计 |
| `book.py` | 教材按页检索（轻量 RAG） |
| `cli.py` | `lf` 命令 |
| `skills/` | lf-plan、lf-teach、lf-quiz、lf-review（软链接到各宿主的技能目录） |
