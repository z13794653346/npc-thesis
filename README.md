# 基于大语言模型的游戏NPC记忆与信任交互系统

> 毕业论文与配套实现 · · 大数据技术

一个以「雨夜旅店调查」为演示场景的文字冒险系统。三个 NPC（店主林掌柜、维修员周衡、旅客沈岚）各自拥有独立的知识范围与长期记忆；大语言模型**不能**直接生成玩家可见台词，也不能直接修改游戏状态——它只返回意图、事实依据编号和动作编号，由后端完成权限校验、确定性回复生成与原子化状态提交。

**核心结论**：在预注册的 216 次真实模型请求中，开启角色范围长期记忆后关键事实正确率由 **0/54 提升到 54/54**（McNemar 双侧精确检验 `p = 1.11×10⁻¹⁶`），108 次跨角色安全查询中未观测到隐藏标记泄漏。该结论仅适用于本项目固定合成用例与当前模型配置，不等同于开放世界中的零幻觉或零泄漏证明。

---

## 目录

- [论文信息](#论文信息)
- [问题与设计思路](#问题与设计思路)
- [核心设计](#核心设计)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [测试与验证](#测试与验证)
- [正式实验](#正式实验)
- [结论与有效性限制](#结论与有效性限制)
- [数据与证据材料说明](#数据与证据材料说明)
- [本仓库不包含的内容](#本仓库不包含的内容)
- [文档索引](#文档索引)

---

## 论文信息

| 项目 | 内容 |
| --- | --- |
| 论文题名 | 基于大语言模型的游戏NPC记忆与信任交互系统设计与实现 |
| 学校 |  |
| 专业 / 班级 | 大数据技术 /  |
| 学号 |  |
| 姓名 |  |
| 指导教师 |  讲师 |
| 完成时间 | 2026-09-20（封面「所在系」「完成时间」「作者签名」仍待作者本人填写） |
| 篇幅 | 25 页，7 章正文，6 张表、5 张图、7 条参考文献 |

> 说明：题名长度超过学校规范文件建议的 20 字，但与任务书修正版保持一致。若导师要求缩短题名，需同步修改任务书、论文封面、正文源文件与文档元数据。

## 问题与设计思路

文字冒险游戏中，NPC 交互面临三个具体问题：

1. **长期记忆中断** —— 只发送最近若干轮对话时，早期承诺在上下文截断后消失。
2. **知识边界不清** —— 把全部剧情秘密塞进提示词，角色可能说出它本未获知的信息。
3. **合作行为缺少可追溯依据** —— 若模型能直接宣布「钥匙已经交给你」或直接改信任值，自然语言生成的错误会进一步破坏游戏状态。

因此本系统的重点不是提高文案自然度，而是建立**记忆范围、事实依据、动作权限与状态提交之间的约束关系**：模型是受限的决策组件，而不是数据库写入者或最终叙事者。

## 核心设计

### 三 NPC Agent 与知识隔离

每次交互只恢复目标角色的会话快照，不共享进程级可变对象。角色的知识、记忆、承诺与物品归属都带角色范围，历史事件不会通过全局状态进入模型上下文。

### 受控决策协议（三字段）

模型按严格 JSON 协议只返回三个字段：

| 字段 | 含义 |
| --- | --- |
| `intent` | 介绍 / 回答 / 追问来源 / 执行动作 / 不知道 / 需要澄清 |
| `evidence_ids` | 本轮可见事实编号，最多 3 个 |
| `action_id` | 只能从后端提供的可用动作中选择 |

程序使用严格数据模型拒绝多余字段、重复依据、越权编号与非法动作，再依据已验证事实生成固定格式回复。原始记录中不含自由 `reply` 字段。

### 记忆检索与上下文控制

保留目标 NPC 最近 **8 轮**历史，并在角色范围内检索最多 **6 条**长期记忆。排序评分为

```
S = 0.6R + 0.2T + 0.2I     （相关性 / 新近程度 / 重要性）
```

相关性由查询字符命中与场景别名共同计算，新近程度随有效交互轮数衰减，重要性由事件类型配置；同分按稳定编号处理。上下文预算按 Unicode 字符计算（Agent 内部上限 12000 字符，检索调用预算 10000 字符）。

> 局限：这是可解释的字符与别名匹配，**不是向量检索，也不涉及模型训练**；对同义表达的覆盖依赖别名配置。

### 信任规则

三个 NPC 信任值独立保存，初始值均为 50。系统严格区分「玩家陈述」与「程序确认的事件」：玩家声称已归还钥匙不会改变物品状态，只有归还动作成功才产生有效事件；角色还必须**获知**该事件，规则才会影响它——由此表达「失信已经发生，但店主尚未得知」。失信扣分在店主处主动告知后才生效，且重复告知不重复扣分。

### 一致性与异常处理

SQLite 会话 JSON 快照 + 独立请求账本；请求去重与内容冲突检测、并发版本比较（过期结果不覆盖新状态）、事务失败回滚、原子提交。模型超时或服务错误时返回明确错误并保留有效状态。

## 仓库结构

```
.
├── README.md                                   # 本文件
├── .gitignore
├── 毕业论文_NPC记忆与信任交互系统_完成稿.md        # 论文正文源文件（Markdown）
├── 毕业论文_NPC记忆与信任交互系统_完成稿.docx      # 按学校模板生成的成品
├── 毕业论文_NPC记忆与信任交互系统_完成稿_预览.pdf  # Word 导出的排版预览
├── 毕业论文_NPC_使用说明与待补清单.md             # 交付说明、待补信息、重生成方式
├── NPC系统_参考文献核验说明.md                    # 参考文献构成与核验要点
│
├── npc-system/                                 # 系统实现
│   ├── app/
│   │   ├── agents.py                           # 三角色 Agent：隔离视图、结构化决策校验、确定性回复
│   │   ├── game.py                             # 记忆检索、游戏事件与信任规则
│   │   ├── storage.py                          # SQLite 事务、请求去重、版本检查
│   │   ├── llm.py                              # DeepSeek HTTP 适配（HTTPS 校验、截止时间、重试）
│   │   ├── main.py                             # API 编排、输出验证与调试保护
│   │   ├── experiments.py                      # 旧版自由生成对照实验工具（历史基线）
│   │   ├── agent_experiments.py                # V2 受控决策实验工具（当前）
│   │   └── scene.json                          # 「雨夜旅店」故事配置
│   ├── tests/                                  # pytest：规则、接口、并发、模型协议、统计
│   ├── frontend/                               # Vue 3 + TypeScript + Vite
│   │   ├── src/                                # App / Notebook / DebugPanel / store / api
│   │   └── e2e/game.spec.ts                    # Playwright 端到端测试
│   ├── scripts/                                # 真实模型冒烟与接地性脚本
│   ├── artifacts/                              # 实验与测试证据（55 文件 / 3.8 MB）
│   │   ├── agents-v2-formal-20260920/          # 正式实验原始记录 records.jsonl + report.json/md
│   │   ├── agents-v2-formal-fixtures-20260920.json   # 预注册固定夹具
│   │   ├── agents-v2-pilot-20260920/           # 试点实验
│   │   ├── live-grounding-*/ live-agents-*/ live-smoke-*/  # 接地性、真实模型联调与冒烟记录
│   │   └── backend-tests*.xml                  # 各次后端测试 JUnit 报告
│   ├── docs/superpowers/                       # 设计规格与实施计划
│   ├── README.md                               # 代码级说明（启动、演示流程、限制）
│   ├── CONTRACT.md                             # 接口约定
│   ├── EXPERIMENTS.md                          # 实验工具使用与评分规则
│   ├── VERIFICATION.md                         # 交付与验证记录（含历史版本说明）
│   ├── AGENTS_V2_EXPERIMENT_PLAN.md            # 预注册实验方案
│   ├── AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md   # 正式实验报告
│   ├── AGENTS_V2_REPORT.md                     # 工程验收报告
│   ├── GROUNDING_REPORT.md                     # 旧版事实审查器误拒/漏判报告
│   ├── REGRESSION_REPORT.md                    # 缺陷定向修复复测报告
│   ├── LIVE_TEST_REPORT.md                     # 真实模型联调报告
│   └── uv.lock / requirements.txt              # 锁定依赖
│
├── 论文制作_NPC/                                # 论文构建与验收工具链
│   ├── build_thesis.py                         # 生成 Word 与配图
│   ├── finalize_word.ps1                       # 更新目录、分页、导出 PDF（Windows）
│   ├── verify_thesis.py                        # 结构与版式检查 + 分页缩略图
│   ├── build_taskbook.py / verify_taskbook.py  # 任务书生成与检查（任务书本身未纳入本仓库）
│   ├── 结构与内容检查.json                      # 结构化检查结果
│   └── 预览_第*.png / 分页检查_*.png             # 逐页复核图
│
└── 论文配图_NPC/                                # 论文配图
    ├── 图1_系统架构.png
    ├── 图2_数据关系.png
    └── 图3_交互流程.png
```

## 快速开始

### 环境要求

Python **3.12+**、[uv](https://docs.astral.sh/uv/)、Node.js **22.12+ 或 24 LTS**（含 npm）。系统在 Windows 11 的 WSL 环境中完成验证。

### Windows

```powershell
cd npc-system
Copy-Item .env.example .env
notepad .env          # 仅在本机填写 DEEPSEEK_API_KEY，不要把密钥提交或发送给别人
powershell -NoProfile -File .\start.ps1
```

若系统策略阻止脚本运行，可手动执行（**无需修改系统执行策略**）：

```powershell
py -3 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm ci; npm run build; cd ..
.\.venv-win\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

> WSL 下生成的 `.venv` 不能用于 Windows，因此 Windows 使用独立的 `.venv-win`。

### Linux / WSL

```bash
cd npc-system
cp .env.example .env      # 填入 DEEPSEEK_API_KEY
bash start.sh
```

已安装并构建后可直接启动：

```bash
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

访问 <http://127.0.0.1:8000>；API 文档在 `/docs`。前端热更新开发：另开终端进入 `frontend` 执行 `npm run dev`，访问 5173 端口。

### 没有 API 密钥也能验证的内容

页面与所有显式标注的规则操作均可使用：协助任务、确认承诺、借还钥匙、维修、取得/转述线索、通知事件、完成调查——这些是确定性游戏机制，不是模拟 AI 聊天。自然语言聊天必须配置真实 DeepSeek 密钥，缺密钥会明确提示，**不会用固定回答冒充模型输出**。

数据默认保存在 `data/npc.sqlite3`。重开游戏创建新存档，不删除旧记录；浏览器只保存当前存档编号。备份前请停止后端并整体备份 `data/` 目录。

> ⚠️ 本版本没有多用户账号系统，**请勿将服务绑定到公网**。

### 一次完整演示

1. 选择林掌柜，完成核对登记与搬运沙袋，两次各 `+5`，信任由 50 → 60。
2. 明确确认归还承诺后，借备用钥匙。
3. 切换周衡修复配电箱；下一次有效行动结束前需归还。切换角色与阅读页面不算行动。
4. 立即切回林掌柜归还：承诺完成，店主信任升到 70。
5. 分别取得三位角色线索，选择「整理三条线索，完成调查」。

失信分支：维修后先做另一项有效动作或聊天，期限到达——此时店主尚未获知，**不扣分**；在店主处点击告知失信事件才扣 15，重复通知不再扣分。晚归还不抹去已发生的失信。模型失败、被拒绝的动作与页面切换均不消耗归还期限。

## 测试与验证

自动化测试使用**显式模型替身**，不产生付费调用；受控实验使用真实模型。

```bash
cd npc-system

# 后端
uv sync --group dev --frozen
uv run pytest -q                     # 75 项通过
uv run ruff check app tests          # 静态检查通过

# 前端
cd frontend
npm ci
npm test                             # 7 项通过
npm run typecheck
npm run build

# 浏览器端到端（需先构建前端，并确保 8000 端口空闲）
npx playwright install chromium
npm run test:e2e                     # 4 项通过
```

| 检查项 | 结果 |
| --- | --- |
| 后端 pytest | **75 项通过** |
| 前端单元测试 | **7 项通过** |
| 浏览器端到端（Playwright） | **4 项通过** |
| Python 静态检查（ruff） | 通过 |
| TypeScript 类型检查与生产构建 | 通过 |

主要功能验收覆盖 12 项：三角色知识与记忆隔离、历史承诺检索、显式线索转述、协助/借用/维修/守约、失信知情条件、请求重复与内容冲突、并发版本冲突、非法结构与越权依据、模型超时与服务错误、存档保存恢复与旧协议只读、调试鉴权与脱敏、桌面与移动端完整流程——**全部通过**。

> 运行中出现 2 条来自上游依赖的弃用警告（Starlette TestClient 建议迁移 httpx2、AnyIO BlockingPortal 别名弃用），不影响测试结论；未为消除警告引入新的生产依赖。

浏览器测试使用独立数据库、强制空密钥、不调用付费服务，结束后自动关闭测试服务器。

## 正式实验

**预注册**：假设、样本量、成功阈值、随机种子（`20260920`）与停止条件在运行前固定，见 [`npc-system/AGENTS_V2_EXPERIMENT_PLAN.md`](npc-system/AGENTS_V2_EXPERIMENT_PLAN.md)。

**设计**：记忆实验 18 个用例（覆盖三个 NPC × 承诺内容/线索来源/历史物品交接三类事实），安全实验 18 个跨角色隐藏信息用例。每个用例在 A（关闭长期记忆）、B（开启角色范围检索）两组各重复 3 次，两组除主要变量外完全相同。总计 **216 次逻辑请求**，2026-09-20 完成 **216/216**。

**模型配置**：DeepSeek `deepseek-flash`，温度 `0.2`，最大输出 1200 token，总截止 30 秒，暂态故障最多重试一次。

| 指标 | A 组：关闭长期记忆 | B 组：开启长期记忆 | 结果解释 |
| --- | --- | --- | --- |
| 关键事实正确率 | 0/54，0.00% | **54/54，100.00%** | 差值 100 个百分点 |
| Wilson 95% 置信区间 | 0.00% – 6.64% | 93.36% – 100.00% | 小样本区间估计 |
| 结构化决策有效率 | 108/108，100% | 108/108，100% | 协议护栏通过 |
| 隐藏标记泄漏 | 0/54 | 0/54 | 本次实验未观测到泄漏 |
| memory 请求中位数 / p95 | 763.30 / 1074.51 ms | 784.19 / 1038.31 ms | 仅作运行记录 |
| leak 请求中位数 / p95 | 713.25 / 1032.33 ms | 753.79 / 1011.27 ms | 未作性能优劣检验 |

54 个配对中 A 组独有正确 0 个、B 组独有正确 54 个，配对 McNemar 双侧精确检验 `p = 1.11×10⁻¹⁶`。B 组正确率不低于预注册的 50%、组间差值超过 30 个百分点且 `p < 0.05`，主假设得到支持。

安全实验两组合计 0/108 次泄漏；合并 108 次的 Wilson 95% 置信区间上界约 3.43%，单组 54 次上界约 6.64%。由于最终回复由程序依据已验证事实渲染，该结果主要验证**角色隔离与确定性输出边界**，而非证明底层模型不会尝试猜测秘密。

## 结论与有效性限制

系统达成了论文设定的工程目标：受控决策与程序渲染能够形成有效的信息边界，角色范围长期记忆检索显著改善历史事实调用。同时也说明可靠的 NPC 交互不能只依赖提示词，还需要外部记忆、权限边界、结构化协议与确定性状态机共同约束。

**限制（不可省略）**：

1. 每次记忆实验只注入**一个**目标事件，主要验证记忆可用性，未测量大量相似、矛盾或过期记忆之间的困难排序。
2. 用例由作者构造，角色、问题与答案分布较窄，**不能外推到所有游戏或模型**。
3. 安全指标只检测唯一隐藏标记，不覆盖暗示、近义改写或世界知识猜测。
4. 尚未开展真实玩家可用性研究，无法据此判断剧情吸引力与长期游玩体验。
5. 延迟实验未针对组间差异做统计功效设计，仅作为本次环境记录。
6. 记忆检索是可解释的字符与别名匹配，不是向量检索或训练模型；上下文预算按 Unicode 字符而非模型 token 计数。
7. 论文中的多表关系图是概念设计，实际实现为 SQLite 会话 JSON 快照 + 独立请求账本。
8. 受控输出能阻止模型把自由编造的句子写入存档，但模型仍可能**选错**相关事实或行动。

## 数据与证据材料说明

论文附录 B 列出三项正式实验材料的 SHA-256。这三份材料**已随仓库一同托管**（`npc-system/artifacts/`，55 个文件 / 3.8 MB），可直接按下表核对：

| 材料 | 仓库内路径 | SHA-256（已核对一致） |
| --- | --- | --- |
| 固定夹具 | `npc-system/artifacts/agents-v2-formal-fixtures-20260920.json` | `154356224e2ad56f4d620cf7e2abf890d7a9120b637ce43a2aa4fa7ed32d699f` |
| 原始记录 | `npc-system/artifacts/agents-v2-formal-20260920/records.jsonl` | `dda7d84a0ae292aec55496af88d6ae41e227805e2e2373f50d3a38d636ef30af` |
| 机器报告 | `npc-system/artifacts/agents-v2-formal-20260920/report.json` | `543a021871b982f2bdfc16e85cd67646f339da1859f6075834396102f5c8ea6c` |

核对方式：

```bash
cd npc-system/artifacts
sha256sum agents-v2-formal-fixtures-20260920.json \
          agents-v2-formal-20260920/records.jsonl \
          agents-v2-formal-20260920/report.json
```

`artifacts/` 除正式实验外还包含开发冒烟、缺陷复测、接地性与试点实验的记录，以及各次后端测试的 JUnit XML。**前两类数据不并入正式统计**，仅作过程留存。

> `output/`（浏览器截图与 Playwright 输出）与 `data/`（本机个人存档）仍不被跟踪：前者可由 `npm run test:e2e` 重新生成，后者属于本机运行数据，不应入库。

复现实验会再次产生费用，且**不得覆盖原始数据**：

```bash
cd npc-system
uv run python -m app.agent_experiments prepare --output new-fixtures.json
uv run python -m app.agent_experiments run --split test --kind all --repeats 3 \
  --max-requests 216 --output new-run/records.jsonl --confirm-paid
uv run python -m app.agent_experiments report new-run/records.jsonl --output new-run/report.md
```

工具默认不运行付费实验，只有在显式提供 `--confirm-paid` 后才会调用模型；已存在的输出文件不会被覆盖。

### 论文重生成方式

先运行 `论文制作_NPC/build_thesis.py` 生成 Word 与配图，再在 Windows 中执行 `论文制作_NPC/finalize_word.ps1` 更新目录、分页并导出 PDF，最后运行 `论文制作_NPC/verify_thesis.py` 生成结构检查与分页缩略图。

> Markdown 是正文内容源。**若直接修改 Word，重新生成会覆盖手工改动。**

### 调试模式

在 `.env` 中设置 `NPC_DEBUG=true` 与较长的 `NPC_DEBUG_TOKEN` 并重启后端，可在调试面板（口令仅存内存）查看检索候选、评分、实际上下文、事件、角色获知时间、信任变化与请求耗时，并导出 JSON。导出会遮盖已配置密钥、常见密钥字符串与鉴权字段，但**对自由文本中的个人信息不能保证完整识别**——分享附件前请人工检查。调试内容含剧透，不会送入 NPC 上下文。

## 本仓库不包含的内容

以下内容按 `.gitignore` 明确排除（如需上传，请先编辑该文件）：

- `.env` —— 含 `DEEPSEEK_API_KEY` 等本机配置，**任何情况下都不得提交**
- `.venv/`、`.venv-win/`、`frontend/node_modules/`、各类缓存与构建产物
- `output/`、`data/` —— 浏览器测试输出与本机个人存档（`artifacts/` 已纳入仓库，见上一节）
- 学校下发或第三方提供的政策与模板文件（三方协议、安全责任书、知情同意书、管理办法、教务〔2026〕88 号通知等）
- 任务书各版本（含修正版 docx 与预览 PDF）—— 论文与任务书已保持题名一致，但本轮未纳入仓库
- `.agents/`、`.omx/`、`PROJECT_MEMORY.md` —— 工具产物，不属于论文交付物

### 安全约定

- 密钥只写在本地 `.env`，不进前端配置、不进版本库、不进论文附件。
- 接口地址仅接受 HTTPS，不跟随重定向。
- 调试接口默认关闭，且需开关与口令同时有效。
- 提交前已对入库文件执行通用密钥模式扫描（`sk-` / `github_pat_` / `ghp_` 及本机实际密钥值），未发现泄漏。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`npc-system/README.md`](npc-system/README.md) | 代码级启动说明、演示流程、接口与实现限制 |
| [`npc-system/CONTRACT.md`](npc-system/CONTRACT.md) | 前后端接口约定 |
| [`npc-system/EXPERIMENTS.md`](npc-system/EXPERIMENTS.md) | 实验工具用法、评分规则、历史基线说明 |
| [`npc-system/AGENTS_V2_EXPERIMENT_PLAN.md`](npc-system/AGENTS_V2_EXPERIMENT_PLAN.md) | 预注册实验方案 |
| [`npc-system/AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md`](npc-system/AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md) | 正式实验报告（216 次真实请求） |
| [`npc-system/AGENTS_V2_REPORT.md`](npc-system/AGENTS_V2_REPORT.md) | 工程验收报告 |
| [`npc-system/VERIFICATION.md`](npc-system/VERIFICATION.md) | 交付与验证记录（含历史版本轨迹） |
| [`npc-system/GROUNDING_REPORT.md`](npc-system/GROUNDING_REPORT.md) | 旧版事实审查器误拒与漏判分析 |
| [`npc-system/REGRESSION_REPORT.md`](npc-system/REGRESSION_REPORT.md) | 缺陷定向修复复测 |
| [`npc-system/LIVE_TEST_REPORT.md`](npc-system/LIVE_TEST_REPORT.md) | 真实模型联调记录 |
| [`毕业论文_NPC_使用说明与待补清单.md`](毕业论文_NPC_使用说明与待补清单.md) | 交付内容、学校模板落实方式、**仍需作者确认的信息**、重生成方式 |
| [`NPC系统_参考文献核验说明.md`](NPC系统_参考文献核验说明.md) | 参考文献构成与核验要点 |

## 引用

```bibtex
@misc{zhang2026npc,
  title  = {基于大语言模型的游戏NPC记忆与信任交互系统设计与实现},
  author = {},
  year   = {2026},
  note   = {毕业论文},
  url    = {https://github.com//npc-thesis}
}
```

---

本仓库为**私有**毕业论文存档，内容仅供作者本人、指导教师与评审使用。论文中引用的第三方文献、模型服务与上游依赖分别遵循其原有许可。
