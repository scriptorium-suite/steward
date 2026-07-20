[English](README.md) | 中文

# Steward（文献管家）

> 对你已有的 Zotero 文献库做安全、可审计、可回滚的治理。

> 英文版为正本，中文版可能滞后。

## 相关文档

[README](README.md) · [中文 README.zh](README.zh.md) · [Skills](skills/) · [CHANGELOG](CHANGELOG.md)

**Suite / 套件:** [scriptorium-spec](https://github.com/scriptorium-suite/scriptorium-spec) (contract SSoT) · [steward](https://github.com/scriptorium-suite/steward) · [Provenance](https://github.com/foxsplendid/Provenance) · [Academic-Slides-Agent / Lectern](https://github.com/foxsplendid/Academic-Slides-Agent) · [.github](https://github.com/scriptorium-suite/.github)
> Contract facts are canonical in **scriptorium-spec/README**; other repos mirror, never fork them.

## 概览

Steward 是一个命令行工具，用于**治理 Zotero 文献库**——而不是"和论文聊天"。市面上的 Zotero AI 工具大多在对话；Steward 操作的是**库本身**：先备份、只读盘点、把每一处改动写成**离线的、人可审阅的提案文件**、审过才执行，并为所有写操作保留回滚基线。它是 [Scriptorium 套件](https://github.com/scriptorium-suite)的成员，面向那些既想要 AI / agent 协助维护文献库、又不愿交出数据控制权的研究者。

核心代码为纯 Python 标准库实现，**零运行时依赖**。每个写入阶段都遵循"先 dry-run、备份为前置、写日志、可回滚"的原则。

## 功能

- **带验证的备份**——数据目录全量快照、字节核对、SQLite `PRAGMA integrity_check`、恢复说明清单；若检测到 journal/WAL 残留（Zotero 仍在运行）则拒绝执行，除非强制。
- **只读盘点**——库体检报告（按类型计数、collection 树、标签卫生、阅读状态直方图、PDF 覆盖率、重复 DOI 分组），**零凭据**即可运行。
- **提案工作流**——生成 `proposal/1.0` 提案文件（条目 + 元数据 + 你的目标 collection 树）及填写说明；可由 LLM、agent，**或你用文本编辑器**填入目标，随后 `apply` 校验并写入。
- **并发安全的 apply**——默认 dry-run；`--run` 要求存在近期经验证的备份，写入前先记录原始状态到 journal，按对象级版本号重新归属 collection，并发改动会显式中止（HTTP 412）而非被覆盖。
- **AI 打标签**——scaffold/填写/apply，将 `ai:` 前缀标签、一行 TLDR、阅读状态写入 `extra` 字段，并记日志。
- **导出**——生成 KB JSON（`library-kb/1.1`）与可重复运行的 Obsidian 库（`Literature/` 笔记 + MOC）。
- **挑选（pick）**——把论文 PDF 连同 handoff 元数据暂存，供下游幻灯片生成（Lectern）使用：单篇 → `handoff/1.0`，多篇 → 多篇 `handoff/1.1` 报告（`papers[]` + `report_type`）。
- **解析（parse）**——把 PDF 解析成 `parsed-paper/1.0`（结构化 `sections[]` + `references[]` + `metadata`），用一个**本地**解析器。默认后端是 **GROBID**（你在 `localhost:8070` 本地跑的 Java 服务）；解析器可插拔（`--parser`），更重的可选后端（Docling/MinerU）日后可接入。全程本地——无云出口；这层本地解析一旦被 Lectern 采用，即可去掉 Lectern 现有的 cloud-MinerU 上传出口。
- **脉络（lineage）**——把一**组**已解析论文生成 `lineage-graph/1.0`，即某研究方向的**库内引用图**。确定性、纯标准库：把每篇论文已解析的 `references` 与该组中其他论文相匹配（先按 DOI，否则按规范化标题），产出 `cites` 边（evidence = 匹配到的参考文献原文），外加按年份排序的 `nodes` 与 `timeline`。**仅限库内**——指向集合之外论文的引用不产生边。带类型的关系（extends / supersedes / method-of / contrasts）与聚类留给 **agent** 在综合阶段补充；`lineage` 只搭出引用骨架。
- **文献综述**——按 collection 路径前缀从 KB 中收集某主题的论文（或用 `--since` / `--since-days` / `--unread` 收集「库内新进展」what's-new digest），由 LLM/agent/人撰写正文——可在会话内通过 `review-fill` skill 交互式撰写，也可手写——再组装成库内笔记；其**参考文献表权威地来自 KB**（key/作者/年份/DOI/阅读状态），因此引用无法被伪造。
- **作品集（portfolio）**——从 `Projects/*.md` 刷新作品集面板（总纲），可选择并入各 `linked_repo` 的 git 状态；只重写其标记界定的快照块，Dataview 块与手写内容保持不动。
- **回滚（rollback）**——重放任意 journal（apply 或 tag）以还原 collections/tags/extra；默认 dry-run、按库匹配，且回滚本身也记日志。
- **多 profile 配置**——交互式 `setup` 向导；环境变量（`ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID` / `ZOTERO_LIBRARY_TYPE` / `ZOTERO_LOCAL`）优先于配置文件。

## 安装

需要 **Python ≥ 3.11** 和 **uv 0.11.16**。安装包（`scriptorium-steward`）尚未发布到 PyPI，请在锁定的源码环境中运行：

```sh
git clone https://github.com/scriptorium-suite/steward
cd steward
uv sync --locked
uv run --locked steward --version
```

开发模式（附带 pytest）：

```sh
uv sync --locked --extra dev
uv run --locked --extra dev pytest
```

`audit` 与 `backup` **不需要 API key**——它们读取本地 Zotero 数据目录。写入类命令（`apply`、`tag apply`、`rollback`）需要 Zotero Web API key 和 library ID，可通过 `steward setup` 或 `ZOTERO_*` 环境变量提供。

## 用法

入门：

```sh
steward setup      # 交互式配置向导（多 profile）
steward backup     # Zotero 数据目录的经验证快照
steward audit      # 只读体检报告（无需凭据）
steward status     # 配置、路径、schema、最近备份
```

**文献循环**（Zotero 侧）：

```sh
steward backup
steward propose --tree targets.txt --out proposal.json   # 生成提案（零凭据）
# 用 LLM / agent / 编辑器填入 proposal.json 的 targets，审阅后：
steward apply proposal.json            # dry-run 计划
steward apply proposal.json --run      # 执行（以备份为前置、记日志）
steward tag scaffold --vocab vocab.txt # AI 标签 + TLDR + 阅读状态
steward tag apply tag-plan.json --run
steward export --vault /path/to/vault  # KB JSON + Obsidian Literature/ 笔记
steward pick "标题或key" --kb kb/library.json   # 暂存 PDF + handoff/1.0
steward pick KEY1 KEY2 --kb kb/library.json     # 多篇 handoff/1.1 报告
steward parse paper.pdf                          # PDF -> parsed-paper/1.0（本地 GROBID）
steward parse CITEKEY --kb kb/library.json       # 用 citekey/key/标题解析出 PDF 再解析
steward lineage --papers parsed/ --query "你的方向"   # 已解析论文 -> lineage-graph/1.0（库内引用图）
steward lineage-render --graph lineage.json --vault VAULT   # lineage-graph/1.0 -> Reviews/<slug>.lineage.md（Mermaid + 时间线 + 关系表）
steward read-render reading-notes/CITEKEY.json --vault VAULT --kb kb/library.json   # reading-note/1.0 -> reading-notes/<id>.md（可浏览 Obsidian 笔记）
steward read-index --vault VAULT --kb kb/library.json   # reading-notes/*.json -> reading-notes/_index.md（阅读状态总览；--kb 补标题/年份）
steward rollback --list                # 列出 journal；可随时重放某个
```

**库循环**（无需 Zotero 凭据）：

```sh
steward review scaffold --topic 01_ML --kb kb/library.json   # 收集主题论文
steward review scaffold --since-days 7 --unread --kb kb/library.json   # 库内新进展 digest
# 在会话内通过 review-fill skill 交互式撰写 review.draft.json，或按 REVIEW-PROMPT.md 手写：
steward review assemble --input review.input.json --draft review.draft.json --out Reviews/ml.md
steward portfolio --vault /vault --git --run   # 刷新总纲面板
```

运行 `steward --help` 或 `steward <命令> --help` 查看完整选项。每个写入阶段都会先打印 dry-run 计划，只有加 `--run` 才会真正写入。

## 文献阅读（P1）配置

Steward 治理文献库；**`read-paper`** skill（在 `skills/`、与 `review-fill` 并列）按四档逐级、按需深度读任一篇——`glance` / `close` / `deep` / `situate`——并写一份以 Better BibTeX citekey 为键的 `reading-note/1.0`。阅读与成文全由 **agent（Claude Code / Codex）在会话内完成**，套件不接任何 LLM。启用需采用以下四个插件，全程**本地优先、只读**——Steward 与 skill 绝不写 Zotero。

- **zotero-mcp** —— agent 读库的窗口。注册为 **MCP server**、指向你的**本地 Zotero API**（只读、**无需 key**）；语义检索强制**本地嵌入或关闭——绝不走云**。`close`/`deep` 档靠它读全文/标注/笔记。
- **PDF++**（Obsidian）—— vault 内读 PDF、标注存成**库内 markdown**（合文件契约、插件没了也在）；`read-paper` 把标注并入 close/deep 档。
- **zotero-reading-list**（已用）—— **深度驱动器**：Zotero Read-Status（`New`/`To Read`/`In Progress`/`Read`/`Not Reading`，在 `Extra` 字段）映射档位——`To Read`→glance、`In Progress`→close、`Read`→situate。skill 只*建议*改状态，写回归你/同步层。
- **Better BibTeX** —— **稳定 citekey** = `reading-note` 的 id 与文件名（跨系统通用 join）；保持 citekey 生成稳定，笔记跨次重读仍同键。

解读笔记落在 vault 的 **`reading-notes/`** 目录（与导出的 `Literature/`、`Reviews/` 并列）。skill 守与 `review assemble` 同样的**反编造**保证：图/数据/引文均来自解析文件、MCP 读到的全文、`library-kb` 或你的标注——绝不编造；源不可达就明说、不猜。

### 本地解析层 —— `steward parse` + GROBID

`steward parse` 把论文 PDF 解析成 `parsed-paper/1.0` 文件——结构化的 `sections[]`、`references[]` 与 `metadata`（标题/作者/年份/doi/摘要）——`read-paper` skill 在 `close`/`deep` 档会**优先**用它而非实时读全文（结构化、可缓存、全程本地）。默认解析器是 **GROBID**，一个**本地** Java 服务：

```sh
# 本地运行 GROBID（完全在你的机器上；无云出口）
docker run --rm --init -p 8070:8070 grobid/grobid:0.8.0

steward parse paper.pdf                            # -> parsed/<stem>.json
steward parse CITEKEY --kb kb/library.json         # 从 library-kb 解析出 PDF 再解析
steward parse paper.pdf --grobid-url http://localhost:8070 --out parsed/x.json
```

GROBID 基础 URL 的解析优先级：**命令行 `--grobid-url` > `STEWARD_GROBID_URL` 环境变量 > 默认 `http://localhost:8070`**。若 GROBID 未启动，`parse` 会打印清晰可操作的错误（如何启动 Docker 服务）而非崩溃报栈。解析器**可插拔**（`--parser`，默认 `grobid`）：stdlib-clean 的 GROBID 路径无需额外依赖，更重的可选后端（Docling/MinerU）日后可注册接入而不动核心。因为解析是本地的，一旦 **Lectern** 也采用这层，即可去掉 Lectern 当前的 cloud-MinerU PDF 上传出口（净的信任改进，见 scriptorium-spec `specs/trust-model.md`）。

### 脉络层 —— `steward lineage`（库内引用图）

`steward lineage` 构建方向综合的**引用图那一半**：给它一组 `parsed-paper/1.0` 文件（来自 `steward parse`），它产出一个 `lineage-graph/1.0`——这些论文如何相互引用的脉络。

```sh
steward lineage --papers parsed/                          # 一个装着已解析文件的目录
steward lineage --papers parsed/a.json parsed/b.json      # 显式列出文件
steward lineage --papers parsed/ --query "[SYNTHETIC] XQ-17 校准脉络" --out lineage.json
```

它**确定性且全程本地**（无 LLM，纯标准库）：对每篇论文遍历其已解析的 `references`，凡是匹配到**同组中另一篇论文**的（先按 DOI，否则按规范化标题）就加一条 `cites` 边，并把匹配到的参考文献原文记入边的 `evidence`（反捏造：边读自真实参考文献数据，绝不凭空生成）。指向集合**之外**论文的引用不产生边（仅限库内）。节点带 citekey/title/year，`timeline` 按年份排列。

**带类型的关系**（`extends` / `supersedes` / `method-of` / `contrasts`）与聚类有意留给 **agent**——它在综合阶段（`synthesize-direction` skill）用本套件从不接入 LLM 的那部分推理来丰富这张图。`lineage` 只铺好确定性的 `cites` 骨架供 agent 推理。

### 脉络渲染 —— `steward lineage-render`（图 → 自包含笔记）

`steward lineage-render` 是把（经 agent 丰富的）`lineage-graph/1.0` **确定性投影**为一篇自包含 Markdown 笔记。JSON 仍是机器权威源，笔记是可重新生成的视图。

```sh
steward lineage-render --graph lineage.json --vault <vault>     # -> <vault>/Reviews/<slug>.lineage.md
steward lineage-render --graph lineage.json --out path.md       # 显式输出路径
steward lineage-render --graph lineage.json --vault <vault> --stamp-notes
```

笔记含一张**原生 Mermaid 流程图**（每条图边一条带 relation 标签的边，有聚类时用 subgraph 分组），在 **vanilla Obsidian 无需插件**即可渲染；一段按年份的**时间线**；以及一张纯 **关系表**（from | relation | to | evidence——对 Dataview 友好，没有 Dataview 也能当表格渲染）。输出落到 `Reviews/`（scriptorium-spec `specs/vault-layout.md` 规定的工具自有派生视图）；覆盖自己产出的派生笔记是幂等的。渲染**自包含**——不依赖每篇论文笔记是否存在（lean-vault）。

`--stamp-notes` 是**可选开关**（默认关）：它**额外**把 Breadcrumbs 兼容 frontmatter（relationship-field 约定的 `cites` / `extends` / `supersedes` / `method-of` / `contrasts` 键）盖到每篇论文笔记上——但**仅当该笔记已存在**于 `Literature/` 或 `reading-notes/` 时。它**合并、绝不覆盖**，绝不新建论文笔记，也绝不碰人写区；笔记不存在则静默跳过（它在 Provenance 里，lean-vault）。

### 解读渲染 —— `steward read-render`（reading-note → 可浏览 Obsidian 笔记）

`steward read-render` 把一份 `reading-note/1.0`（`read-paper` skill 写的逐篇分阶段笔记）渲染成**一篇自包含、可浏览的 Obsidian 笔记**——即每篇论文的长期归档。JSON 仍是机器权威源，`.md` 是可幂等重新生成的规范浏览视图。

```sh
steward read-render reading-notes/CITEKEY.json --vault <vault>                 # -> <vault>/reading-notes/<id>.md
steward read-render reading-notes/CITEKEY.json --vault <vault> --kb kb/library.json   # 用 title/authors/year 丰富 frontmatter
steward read-render reading-notes/CITEKEY.json --out path.md                   # 显式输出路径
```

笔记含 **YAML frontmatter**（Obsidian 属性——citekey、read_status、doi、created、glance 标签），**每个已填阶段**对应一个双语 `## ` 小节（速览·Glance / 精读·Close read / 深读·Deep read / 串联定位·Situate——未填的阶段跳过），situate 的 `lineage_refs` 渲染为 `[[citekey]]` **wikilink**，一个独立的 **`## 标注 · Annotations`** 小节，一个指向库笔记 + 解析文件/Zotero 来源的链接块，以及标注 JSON 权威源的页脚。因为 `reading-note/1.0` 不带 title/authors/year（它们在 `library-kb/1.x` 里），加 **`--kb`** 即按笔记的 citekey 在 KB 中匹配来丰富 frontmatter；不加则只渲染笔记自身携带的内容。输出默认取 `--out`，否则有 `--vault` 时落 `<vault>/reading-notes/<id>.md`，再否则落 `<json-dir>/<id>.md`；覆盖派生 `.md` 是**幂等**的。

两点渲染辅助：

- **标注内联。** 当 `sources.annotations` 非空时单独成 `## 标注 · Annotations` 小节。形似 URI/路径的条目（带 `scheme:` 前缀，或含 `/`/`#` 且无空格）渲染为链接/`code` 引用；纯文本条目渲染为 `> 引用块`，让**高亮文字直接内联显示**（把有意义的高亮文字而非仅引用记入 `sources.annotations` 即可启用）。
- **图片内嵌。** `close_read.figures[]` 中形似**图片路径**的条目（以 `.png`/`.jpg`/`.jpeg`/`.gif`/`.webp` 结尾、可带前导路径）渲染为 Obsidian 内嵌 `![[path]]`；标题字符串仍渲染为 `- caption` 列表项。这只是**渲染辅助**——真正的图片需要能产出图片文件的版面解析器（本地 **MinerU**）；**GROBID / `parsed-paper` 只携带图题文字**，所以仅当产图解析填入图片路径时内嵌才生效。Steward 不伪造抽取。

### 阅读索引 —— `steward read-index`（reading-notes → 状态总览）

`steward read-index` 扫描 `<vault>/reading-notes/*.json`（reading-note/1.0 权威源文件），生成一篇总览笔记 `<vault>/reading-notes/_index.md`——阅读状态面板，让你一眼看完所有有解读笔记的论文。

```sh
steward read-index --vault <vault>                      # -> <vault>/reading-notes/_index.md
steward read-index --vault <vault> --kb kb/library.json # 用 library-kb 补全表格的标题/年份
steward read-index --vault <vault> --out path.md        # 显式输出路径
```

它对同一集合给出四种视图，**有无插件都好用**：**按状态分组的小节**（`## To Read` / `## In Progress` / `## Read` / `## Not Reading` / `## (no status)`），每条是 `- [[citekey]] — title year (glance·close)` 的 wikilink 列表，附已填阶段；一张**完整静态表**（citekey | title | year | status | stages | tags）；以及给插件用户的 **Dataview 代码块**（静态视图对其他人照样渲染）。排序确定（先状态生命周期、再 citekey）；目录里的非 reading-note JSON 会被跳过并告警；空/不存在的 `reading-notes/` 打印清晰提示（不崩溃、不写文件）。它只覆盖 `_index.md`（幂等）；`.json` 文件仍是机器权威源。

解读笔记以 `[[citekey]]` 链接其库笔记。要让该 wikilink 解析，`steward export` 现在会把 Better BibTeX **citekey** 写到每篇 `Literature/` 笔记上——它从 Zotero 条目 `extra` 字段的 `Citation Key:` 行解析出 citekey，存入 `library-kb/1.1` item 的可选 `citekey`，并在存在时把 `aliases: ["<citekey>"]` + `citekey:` 属性盖进笔记 frontmatter。于是 `[[citekey]]`（来自解读笔记、谱系边或手写）在套件内可解析到库笔记。没有 `Citation Key:` 行的条目不受影响（citekey 为空、无 alias）。

## 项目结构

```
steward/
├── pyproject.toml          # 构建元数据、命令行脚本、dev 附加依赖（核心仅标准库）
├── CHANGELOG.md            # 里程碑历史（M0–M3 + Phase D 综述）
├── LICENSE                 # Apache-2.0
├── src/steward/
│   ├── cli.py              # argparse 入口；全部子命令（main = 命令行脚本）
│   ├── config.py           # ~/.config/scriptorium/steward/config.toml 多 profile；环境变量覆盖
│   ├── zotero_api.py        # 标准库 urllib 客户端（web + 本地只读两种模式）
│   ├── backup.py           # 经验证的数据目录快照 + 恢复清单
│   ├── audit.py            # 只读体检报告
│   ├── proposal.py         # proposal/1.0 scaffold + 摘要
│   ├── apply.py            # plan/execute/rollback，含 journal 与版本检查
│   ├── tagging.py          # tag-plan/1.0 scaffold/校验/执行
│   ├── export.py           # library-kb/1.1 JSON + Obsidian 库写入
│   ├── pick.py             # 暂存 PDF + handoff/1.0 或 1.1 元数据
│   ├── parse.py            # PDF -> parsed-paper/1.0（本地 GROBID；可插拔解析器 seam）
│   ├── lineage.py          # 已解析论文 -> lineage-graph/1.0（库内引用图）
│   ├── lineage_render.py   # lineage-graph/1.0 -> 自包含 Reviews/ 笔记（Mermaid + 时间线 + 关系表）
│   ├── read_render.py      # reading-note/1.0 -> 可浏览 Obsidian 笔记（frontmatter + 分阶段小节 + wikilink + 标注）
│   ├── read_index.py       # reading-notes/*.json -> reading-notes/_index.md（状态面板：分组小节 + 表格 + Dataview）
│   ├── portfolio.py        # project/1.0 -> 总纲面板快照
│   ├── review.py           # 综述 scaffold/assemble（review-draft/1.0）
│   └── yamlmini.py         # 极简的纯标准库 YAML 子集解析器
├── skills/                 # 三个可移植、宿主中立的 agent Skills
└── tests/                  # pytest 测试（每个命令一个模块）
```

## 状态

活跃开发中，**v0.2.0**，开发状态：3 - Alpha。功能已完成到里程碑 M3，外加 Phase D 文献综述层与按需文献刷新（见 `CHANGELOG.md`）；尚未发布到 PyPI。

已实现的交换格式（依据 [scriptorium-spec](https://github.com/scriptorium-suite/scriptorium-spec)）：
- **产出：** `library-kb/1.1`、`handoff/1.1`（单篇 `1.0` 子集）、`proposal/1.0`、`parsed-paper/1.0`、`lineage-graph/1.0`
- **消费：** `proposal/1.0`、`tag-plan/1.0`、`project/1.0`、`library-kb/1.0` 与 `library-kb/1.1`、`review-draft/1.0`

## 安全契约

1. 任何写入阶段前必有经验证的备份（字节核对 + `PRAGMA integrity_check` + 恢复清单）。
2. 写操作只触及 `collections`、`tags`、`extra` 三类字段，**永不删除**。
3. 全部写入经 Zotero Web API v3，按对象级版本号做并发保护（冲突显式报 412，不覆盖）。
4. 机器标签带 `ai:` 前缀；一行主旨与阅读状态按公开约定写入 `extra` 字段。
5. 下游工具只消费导出文件（`library-kb/1.0` 或 `library-kb/1.1`），绝不直连你的实时库。

## 公开样例数据说明

三个可复用 Skill 位于中立的 `skills/` 目录：`read-paper`、`review-fill` 与 `synthesize-direction`。它们不依赖某个 agent 宿主的私有配置目录。

测试和 Skill 契约示例中可能具有识别性的论文身份、作者、DOI、题名、测量值及研究领域，均已替换为明确标注的 **`[SYNTHETIC] XQ-17` 合成数据**；其余短值仅为结构占位符。所有示例均不来自真实 Zotero 文献库、研究项目或个人资料。

## License

Apache-2.0（见 [LICENSE](LICENSE)）。
