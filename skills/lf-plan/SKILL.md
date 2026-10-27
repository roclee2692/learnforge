---
name: lf-plan
description: LearnForge 规划学科包。用户说“我要备考 XX”“新建一门课”“我有教材/目录/往年题”“导入试卷”“设置考试日期/范围”时使用。把学习目标编译成学科包：能力地图（知识点与前置）、考点权重、资料卡、题库和盲测卷，并定好验收标准。
---

# lf-plan：把学习目标编译成学科包

学科包在数据仓库的 `packs/<pack>/`：

| 文件 | 内容 |
|---|---|
| `pack.yaml` | 目标、模式（exam / growth）、考试日期、教材、老师划的范围 |
| `map.yaml` | 能力地图：章节 → 知识点（id、名字、prereq 前置） |
| `blueprint.yaml` | 考点权重 `weights`（相对值，引擎会归一化）、题型分值 `types`、来源 `source: estimate/real` |
| `sources.md` | 资料卡：来源、可信度、对应知识点；“前人踩过的坑”单独列 |
| `datasets/` | SQL 题的判分数据集（至少两个：教材样例 + 边界数据） |

已经有 `os`（操作系统）和 `db`（数据库原理）两个包。新课：`lf init <pack> --name <课程名>`。

## 先问清楚（只问缺的）

考试日期、教材（书名版本）、老师划的范围、有没有往年题。拿到一个就落一个：

```bash
lf pack os set exam_date 2027-01-10
lf pack db set textbook "王珊《数据库系统概论》第六版"
```

## 有教材时：目录比全文先用

1. `lf book add <pack> <教材.pdf> --offset <PDF页码与书上页码之差>` 导入，按页存文字。
2. `lf book toc <pack>` 看 PDF 书签目录。没有书签就让用户拍目录页，你直接看图读出来。
3. 按目录对齐 `map.yaml`：章节名和顺序跟用户的教材一致，知识点 id 已经被题库引用的**不要改名**，只改 `name` 或新增。
4. 讲解时 lf-teach 用 `lf book find <pack> "<术语>"` 检索页码。返回“扫描版”警告时，先让有视觉的模型把页面转成文字，存成 .md 再 `lf book add`。

## 有往年题时

1. 试卷是图片或扫描 PDF：直接用你的视觉能力读，逐题切开，写成题目 JSON（`source: "real"`，带 `concept`、`type`、`score`、`stem`、`answer`、来源年份 `origin`）。
2. **切完给用户确认一遍**（题目边界、题型、分值、答案）。这一步错了后面全错。
3. 确认后入库：`lf q add --jsonl --file <切好的题.jsonl>`。计算题配上 `verify`，入库时会自动验算。
4. **留一套最新的不练，作为盲测卷**：`lf holdout add <pack> <那套题.jsonl>`。之后你不再读这套题，也不再看 `holdout/` 目录。
5. 按真题重新估 `blueprint.yaml` 的权重（统计每个知识点的分值占比），把 `source` 改成 `real`。

## 没有往年题时

用教材章节和课后题代替：权重按章节篇幅和常见考法估（`source: estimate`），并在 `sources.md` 写明是估计。

## 验收标准

- 考试模式：盲测卷分数（`lf holdout run <pack>`，用户本人在终端做）。练习分数和预测分都只是过程指标。
- 成长模式：能独立完成的项目和模拟面试表现。

## 不要做

- 不要读或改 `holdout/`；不要改错因词表；不要为了让预测分好看去调低权重。
- 改 `map.yaml` 时不要删除已被作答记录引用的知识点 id。
