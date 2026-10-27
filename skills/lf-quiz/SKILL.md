---
name: lf-quiz
description: LearnForge 出题、判分、记错因。用户说“出题”“考考我”“做诊断卷”“做题”“练一下 XX”“这题我答……”，或者在 lf-teach / lf-review 里需要做题时使用。题目来自 lf 题库或现场生成，答案一律用 lf 判分和验算，答错时按固定词表标错因写进账本。
---

# lf-quiz：出题、判分、记错因

引擎是 `lf` 命令（所有命令都可以加 `--json`）。数据仓库由 `lf` 自己定位，不需要你找路径。

## 有 learnforge MCP 工具时（优先）

宿主加载了 `learnforge` MCP 服务（工具名以 `lf_` 开头）时，优先用工具，不用命令行：

- 出题：`lf_quiz`（诊断卷或某知识点）或 `lf_practice`（按今日建议）。支持界面的宿主（Claude 桌面版、claude.ai、ChatGPT）会直接显示题卡，用户在卡片里作答、交卷，**判分和记账已经在服务端完成**，你不用再把题目抄进聊天，也不要把答案说出来。出题后照实说题数和总分（工具返回的文字里有总分，不要自己加）；如果用户说看不到题卡，告诉用户可以换用 Opus 模型再出一次，或者打开网页版 http://127.0.0.1:8765/?view=quiz&pack=os 。
- 卡片里点“讲讲这题 / 请 AI 批改”会以用户消息发给你：先调 `lf_explain_context` 拿题目、用户作答和验算过程，再讲。主观题批改完调 `lf_grade_subjective` 记分。
- 纯文字宿主（Claude Code、Codex 命令行）看不到卡片：把 `lf_quiz` 返回的题目逐题给用户，收齐后用 `lf_submit` 提交。
- 错因：`lf_tag_error`；提示：`lf_hint`；验算：`lf_calc`。

没有这些工具时，按下面的命令行流程做。

## 铁律

1. **能算的不猜。** 计算题的答案、过程表格一律来自 `lf calc` / `lf grade`，不自己心算。`lf calc --list` 看有哪些验算器。
2. **提示分三级，三级用完才给答案。** 用户坚持要答案时，先给第一级提示；用户说“直接给答案”第二次，再一级一级往下。提示用 `lf q hint <id> --level 1|2|3`；题目没有 hints 时你自己写三级：方向 → 关键步骤 → 差一步就是答案。
3. **每次作答都要记录**：`lf record`。不记录，复习建议和掌握度就是瞎的。
4. **错因只能用固定词表**：`concept` 概念不懂、`confusion` 两个概念记混、`reading` 审题错、`calc` 计算错、`procedure` 步骤遗漏或顺序错、`time` 超时、`format` 答题格式不规范。拿不准时问用户一句（“你是没想到要用 NOT EXISTS，还是想到了但写错了？”），不要瞎标。
5. **绝不读 holdout/ 目录**，也不用盲测题出题、讲题。

## 流程

### 1. 选题

- 诊断卷：`lf paper <os|db>` 打印整卷（不含答案）。在对话里**一次给一道**，除非用户要整卷一起做。
- 针对某个知识点：`lf q list --concept os.vm.replace --unseen`，再 `lf q show <id>`（不带 `--answer`）。
- 复习时用 `lf today` 推荐的题号，错题优先重做。
- 题库里没有合适的题：现场出一道，写成 JSON 用 `lf q add` 入库再出给用户（见下方“现场出题”）。

出题时把题干、选项原样给用户。计算题提醒用户按哪些项作答（`lf q show` 里的 `answer_keys`）。可以顺口问一句“有几成把握？”，答案记进 `--confidence`（0~1）。

### 2. 判分并记录

客观题（choice / judge / fill / calc / sql）直接让引擎判，并同时记录：

```bash
lf record os-seed-0013 --given '{"FIFO":15,"LRU":10,"OPT":9}' --hints 1 --confidence 0.7
lf record db-seed-0006 --given "SELECT Sname FROM Student WHERE ..."
```

- `--given` 里计算题用 JSON（键名照 `answer_keys`），单空或选择题直接写字符串，多个空用 `|` 分隔。
- `--hints` 填这题用了几级提示（每级扣 25% 的得分，用来算掌握度）。
- SQL 题引擎会在“教材数据 + 边界数据”两个数据集上实际执行比对，反馈里会说少了哪些行、多了哪些行，这就是讲错因的素材。

主观题（short / design / code）：用 `lf q show <id> --answer` 拿到 rubric 和参考答案，**逐条对 rubric 打分**，告诉用户每一条得了几分、差在哪，然后：

```bash
lf record os-seed-0004 --given "<用户的作答摘要>" --score 0.6 --cause procedure --detail "P(mutex) 写在 P(empty) 前面"
```

### 3. 答错时

1. 先说结论：错在哪一步（不要先贴完整答案）。
2. 标错因：`lf record ... --cause <词表> --detail "<一句话，具体到步骤>"`；如果已经记录了作答但漏了错因，用 `lf err add <id> --cause ... --detail ...`。
3. 讲错因而不是讲答案：计算题用 `lf calc <验算器> '<参数 JSON>'` 打出逐步表格，指出用户在第几步和表格分岔。概念题对照 `explain` 字段讲。
4. 给一次重做机会或同类的一道新题。重做答对时 `lf record` 会自动把这道错题标成已订正。
5. `lf today` 里出现“专项练习”提示（同一知识点同一错因 ≥ 3 次）时，下一组题集中打这个错因。

### 现场出题

```bash
lf calc os.page_replace '{"frames":4,"refs":[1,2,3,4,1,2,5,1,2,3,4,5],"algo":"FIFO"}'
echo '<一行 JSON>' | lf q add
```

题目 JSON 至少包含 `concept`（必须是 `lf map <pack>` 里有的 id）、`type`、`score`、`stem`、`answer`；计算题再加 `verify`（入库时会自动验算，对不上会报出来，那就改题或丢掉），给三级 `hints` 和一段 `explain`。`source` 写 `gen`。格式照抄题库里的现成题：`lf q show os-seed-0013 --answer --json`。

答案不唯一的项（安全序列、最小依赖集、分解、候选码）不要只存一个字面答案，放进 `check` 字段让检查函数判：`os.check_banker_sequence`、`db.check_min_cover`、`db.check_decomposition`、`db.check_keys`、`db.check_closure`、`db.check_nf`、`db.check_set`。

## 做完一组题后

用两三句话告诉用户：做了几题、对了几题、暴露出的错因是什么、下一步建议（来自 `lf today`）。诊断卷做完跑 `lf stats --pack <os|db>`，把各章掌握情况给用户看。
