# 设计决定（相对蓝图 v0.1）

日期：2026-10-23

## 蓝图第 10 节三个待定问题的处理

| 问题 | 你的回答 | 落地方式 |
|---|---|---|
| 要不要结合 RAG，喂书还是喂目录？ | 想结合 | **目录先行，全文按页检索，暂不上向量库。** 目录（PDF 书签或拍照）用来对齐 `map.yaml`，这是收益最大的一步；全文用 `lf book add` 按页存，`lf book find` 用中文二元组 + BM25 检索，返回页码。教材术语非常固定，关键词检索已经够用，而且零依赖、能告诉你“第几页”。等出现检索不准的实际例子，再接本地 bge-m3（第 1 阶段做去重时本来就要装）。 |
| DeepSeek V4.1 Flash 能否识别试卷图片 | 不用它，用别的有视觉的模型 | 切题这一步交给宿主模型（Claude、Codex 等都能看图）：看图 → 切成题目 JSON → **你确认** → `lf q add`。引擎不调用任何视觉接口。扫描版教材同理，先转成文字再导入。 |
| DeepSeek Harness 是否原生支持 SKILL.md | 支持 | 四个技能直接软链接进 `~/.dsh/skills/`，不再绕道 Profile Bundle。 |

## 技能装在哪

| 宿主 | 目录 | 状态 |
|---|---|---|
| Claude Code | `~/.claude/skills/` | 已链接 |
| DeepSeek Harness | `~/.dsh/skills/` | 已链接 |
| Codex | `~/.agents/skills/` | 已链接 |
| OpenClaw | `~/.openclaw/skills/` | 已链接 |
| Hermes | `~/.hermes/skills/` | 本机没装 Hermes，未链接 |

都是软链接，改 `learnforge/skills/` 里的文件，所有宿主同时生效。

## 和蓝图 v0.1 不一样的地方

1. **多了 `bank/<pack>.seed.jsonl`**：诊断卷这类人工（AI）编写、全部验算过的题，`source` 记为 `seed`，和真题 `real`、生成题 `gen` 分开。
2. **`errors.jsonl` 是事件流**：答错写一条 `open`，之后同一道题答对自动写一条 `fix`。账本只追加，不改历史。
3. **掌握度按“知识点 × 天”合并**：同一天对同一知识点的多次作答合并成一次 FSRS 复习，评级由当天得分率决定。否则一晚上刷十道题会把稳定度虚高。用一级提示扣 25% 得分。
4. **`mastery.json` 只是缓存**：每次 `lf today` / `lf stats` 都从 `ledger/` 重算，删了也没关系，所以它在 `.gitignore` 里。
5. **SQL 判分用两个数据集**：教材样例数据 + 专门构造的边界数据（一门课都没选的学生、重名、成绩恰好 90、成绩为 NULL）。只用教材数据时，`Cno <> '1'` 这类错误写法在某些题上会碰巧通过。
6. **答案不唯一的项用检查函数判**：安全序列、最小依赖集、分解、候选码、闭包写法，检查的是性质，不比字面。
7. **盲测卷的锁有两层**：引擎里除 `lf holdout` 外所有读写路径都拒绝 `holdout/`；数据仓库的 `.claude/settings.json` 禁止 Claude Code 直接读这个目录。其他宿主靠技能里的规则约束。
8. **教材和考点权重是假设**：OS 按汤小丹第四版、DB 按王珊第五版组织章节，权重按国内期末常见分布估（`blueprint.yaml` 里 `source: estimate`）。拿到你的教材、范围和往年题后要重新对齐。

## 第 0 阶段验收

> 做完一套诊断卷，`lf stats` 能显示各知识点的掌握情况。

在一份数据副本上模拟做完 OS 诊断卷（20 题，7 题故意答错并标错因），`lf stats` 按章列出 26 个知识点的状态和错因分布，`lf today` 把 4 个有未订正错题的知识点排在前面并给出理由；8 天后重做一道错题，系统自动标为已订正；设置考试日期后，考前两周出现“覆盖缺口”。你的真实数据仓库里没有任何模拟记录。

还没验证的：你本人在宿主里完整走一遍（讲解 → 出题 → 判分 → 记错因 → 今日建议）。

---

# v0.2：独立产品形态（2026-10-24）

## 一个引擎，三种外壳，一份数据

```
            ┌───────────── 外壳 ─────────────┐
 聊天里的界面  Claude 桌面版 / claude.ai / ChatGPT*  ← MCP 服务 + MCP Apps 界面
 纯文字插件    Claude Code / Codex / DeepSeek Harness ← 同一个 MCP 服务，没有界面
 独立网页      浏览器打开 http://127.0.0.1:8765      ← lf serve，同一个界面文件
            └───────────────┬────────────────┘
                 service.py（11 个工具：出题、交卷判分、提示、错因、批改、讲题素材、复习面板、验算……）
                            │
                 lf 引擎（判分、验算、FSRS 排期、统计）
                            │
                 learnforge-data/（本机文件，不上任何服务器）
```

- **数据只在用户电脑上。** MCP 服务是宿主在本机拉起的小程序，不需要服务器，也没有运行成本。换宿主不换数据，所以“记忆存储层”是我们自己设计、自己控制的，宿主管不着。
- **规则写在工具里，不写在提示词里。** 题目下发时不带答案；判分只能走 `lf_submit`；错因只能从 7 个固定词表里选（`lf_tag_error` 会拒绝词表外的值）；讲题必须先拿 `lf_explain_context` 里的验算过程。宿主模型想绕也绕不过去。
- **谁出模型钱，用户自己选。** 在聊天宿主里用的是用户自己订阅里的模型；独立网页需要讲题时，读环境变量 `DEEPSEEK_API_KEY`（OpenAI 兼容接口，`learnforge.yaml` 里 `llm:` 可以改 base_url、model、变量名）；两样都没有，就给一段提示词，复制到任何 AI 聊天里（DeepSeek 网页版、豆包都行）。判分、记账、排期永远不调模型。
- 引擎从不主动调用宿主的模型，只被调用。

## 协议依据

MCP Apps 规范 2026-01-26 版（`specification/2026-01-26/apps.mdx`，github.com/modelcontextprotocol/ext-apps）和官方 SDK 源码 `src/app.ts`，2026-10-24 下载核对：

- 工具用 `_meta.ui.resourceUri` 指向 `ui://` 资源（同时写了已弃用的 `_meta["ui/resourceUri"]` 兼容旧宿主），资源 MIME 是 `text/html;profile=mcp-app`。
- 界面和宿主之间是 postMessage 上的 JSON-RPC：界面发 `ui/initialize`，收到结果后发 `ui/notifications/initialized`；宿主推 `ui/notifications/tool-result`；界面用 `tools/call` 调工具、用 `ui/message`（content 是数组）往聊天里发话、用 `ui/notifications/size-changed` 报高度。
- 宿主给的颜色变量是 `light-dark(浅, 深)`，取哪一边由页面的 `color-scheme` 决定。界面必须按宿主的 `theme` 设 `color-scheme`（官方 SDK 的 `applyDocumentTheme` 就是这么做的）；没设时一律取浅色，2026-10-24 桌面版深色模式下题卡发白就是这个原因。宿主没给主题时 `color-scheme: light dark`，跟随系统。
- 宿主默认 CSP 不允许外部脚本，所以界面是一个零依赖的单文件（`src/learnforge/ui/app.html`），桥接代码手写，不引 SDK。

## 各宿主的接入状态

| 宿主 | 方式 | 状态 |
|---|---|---|
| Claude Code | `claude mcp add --scope user` | 已接入，`claude mcp list` 显示 Connected；纯文字 |
| Claude 桌面版 | 桌面扩展包 `/Users/raelon/Drives/D-DevWorkspace/01-活跃项目/07-算法学习与教育/learnforge/dist/learnforge.mcpb`（双击安装，由桌面版自己管理） | 已用官方 `mcpb validate` / `mcpb pack` 校验打包，2026-10-24 安装成功，11 个工具全部连上；题卡能否显示随聊天所用的模型变化（实测两次，同一个服务进程）：Sonnet 5.5 的对话里只出现一行带 🖥 图标的工具调用、没有题卡；Opus 5.5 的对话里题卡直接显示。服务端两次完全一样，差别在宿主或模型一侧；样本只有各一次，原因未确认。**不要手改 `claude_desktop_config.json`**：2026-10-24 写进去的 `mcpServers` 三分钟后被运行中的桌面版用内存里的设置覆盖掉了 |
| Codex | `~/.codex/config.toml` 的 `[mcp_servers.learnforge]` | 已写入（备份 `config.toml.bak-时间戳`），`codex mcp list` 显示 enabled；纯文字 |
| DeepSeek Harness | 设置 → 插件 → MCP 管理，stdio | 没自动改：配置写在 `cordis.patch.yml`，格式没有公开文档，用 GUI 加更稳 |
| ChatGPT | 只连公网 HTTPS 的远程 MCP | 没做：需要把服务放到公网或做内网穿透，数据会离开本机，要另行设计 |
| DeepSeek 网页版、豆包电脑版 | 没找到能加载第三方 MCP 的公开资料 | 用独立网页里的“复制提示词”兜底 |
| WorkBuddy | 未核实 | 接之前要实测 |
| 四个 SKILL.md | `~/.claude/skills`、`~/.dsh/skills`、`~/.agents/skills`、`~/.openclaw/skills` 软链接 | 已更新：有 `lf_` 工具时优先用工具 |

## 已验证 / 未验证

已验证（2026-10-24，全部在数据副本上跑，你的真实账本没有被写入测试数据）：

- 用脚本按 MCP 协议驱动 `lf mcp`：initialize、tools/list（带 `_meta.ui`）、resources/read（22 KB 界面）、出题不泄露答案、批量交卷判分记账、词表外错因被拒、提示、讲题素材带验算过程、主观题记分。
- 独立网页：复习面板、整组作答、未答校验、“不会，跳过”记 0 分、错因按钮写入错题本、无 API key 时给可复制提示词。
- 宿主模拟器（`lf serve` 后打开 `/host-test`）：握手顺序、宿主主题、卡片内 `tools/call` 交卷和提示、“讲讲这题 / 请 AI 批改”以 `ui/message` 发到聊天。

已验证（实机）：Claude 桌面版普通聊天（Opus 5.5）里题卡直接显示，选项、填空框正常。
未验证：桌面版题卡里交卷能否写入账本；配了 API key 后的网页讲题（我不能替你填 key）。

## 下一步

1. 双击安装 `learnforge.mcpb`，在普通聊天里说“用 learnforge 出 OS 诊断卷”，看卡片是否出现、能不能点。
2. 给别人用的版本：扩展包改成 `uv` 类型（manifest 0.4），把引擎源码和 pyproject 一起打进去，宿主自己装依赖；首次运行自动建数据仓库并带上学科包。现在这个包只是调用本机已装的 `lf`。
3. 桌面软件：用 Tauri 把 `lf serve` 包成一个双击就开的应用（期末后）。
4. 远程版（给 ChatGPT 和手机）：数据要离开本机，等有人要用再设计。
