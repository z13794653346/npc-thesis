# NPC记忆与信任交互系统

框架升级版。Vue 3 + FastAPI + LangGraph + SQLAlchemy 2 / Alembic + FastEmbed，以《第五位住客》雨夜旅店为演示场景。
三个NPC具有独立知识和记忆；物品、承诺和信任由后端规则管理，大模型不能直接修改数据库。

当前对话版本采用三个按角色隔离的NPC Agent。每轮从SQLite快照恢复所选角色的知识、记忆和可用行动；大模型只返回意图、事实编号和行动编号，不能直接编写玩家可见台词。LangGraph按恢复角色视图、模型决策、依据校验三个节点执行；后端校验编号后，用原始事实、来源标签或实际动作结果生成最终回复。图只计算决策，游戏状态仍通过Store原子提交。旧版自由生成与二次事实审查仅保留为历史实验基线，旧存档保留查看但不能继续交互。V2正式合成实验完成216/216次请求，结果与边界见[正式实验报告](AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md)。

## 启动

### Windows

需要 Python 3.12 或更新版本、Node.js 22.12+ 或24 LTS（含 npm）。在本目录终端运行：

```powershell
Copy-Item .env.example .env
notepad .env
# 仅在本机填写 DEEPSEEK_API_KEY，不要把密钥发送给别人。
powershell -NoProfile -File .\start.ps1
```

已有 `.env` 时不要重复复制。若系统策略阻止脚本运行，使用下面的手动启动命令，**不需要改变系统执行策略**：

```powershell
py -3 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv-win\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>，Ctrl+C停止服务。WSL环境生成的 `.venv` 不能用于Windows，因此Windows脚本单独使用 `.venv-win`。

### Linux / WSL

需要 Python、uv、Node.js。配置 `.env` 后运行 `bash start.sh`。已安装并构建时可快速启动：

```bash
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

开发界面：后端运行后，另一终端进入 `frontend` 执行 `npm run dev`，访问5173端口。
数据默认保存在 `data/npc.sqlite3`。重开游戏创建新存档，不删除旧记录；浏览器只保存当前存档编号。
备份数据库前停止后端，备份整个 `data/` 目录。请勿将服务绑定公网，此版本没有多用户账号系统。

## 新版框架与语义记忆

- **LangGraph**：明确的三节点流程，调试导出包含节点耗时；模型失败或校验拒绝时保留已完成阶段的依据。不开图检查点，避免和游戏存档产生双重权威；不宣称自主规划。图的全局快照不发送至外部追踪服务。
- **SQLAlchemy 2 + Alembic**：ORM管理原有 `sessions` / `requests` 表，保留请求幂等、版本检查及原子提交。SQLite默认；支持PostgreSQL。每个操作独立Session。
- **FastEmbed**：本地CPU运行中文 `BAAI/bge-small-zh-v1.5`（512维），先排除其他角色和失效事件，再混合语义、词法、时间和重要性。向量使用有界进程内缓存，重启后重新计算。

首次使用语义记忆，在 `npc-system` 目录执行一次：

```bash
uv run python scripts/prepare_embeddings.py
uv run python scripts/verify_semantic_memory.py
```

Windows使用 `.venv-win/Scripts/python.exe` 运行相同脚本。首次下载需要联网，准备好后重新启动服务。模型文件保存在 `artifacts/embedding-models/`，不入Git。聊天密钥继续用于DeepSeek；嵌入不需要新密钥。

默认 `NPC_MEMORY_MODE=hybrid`；请求期间禁止自动下载模型。未准备或模型故障时回退为原词法检索，调试记录明确标注 `lexical_fallback` 和原因。用 `NPC_MEMORY_MODE=lexical` 可运行旧检索基线。`/api/health` 中的 `memory_mode` 表示配置，实际每次策略以调试记录 `retrieval_strategy` 为准。自定义缓存时，预热脚本传 `--cache-dir`，服务设置同一 `NPC_EMBEDDING_CACHE`。

### 数据库迁移与PostgreSQL选项

升级保留旧表与JSON存档。Alembic首个版本可接纳未stamp的旧SQLite；降级只回退版本，不删除旧业务表。迁移前停止服务并备份数据库；本次验证只使用临时测试副本，没有迁移个人存档。

```bash
uv run alembic upgrade head
```

此命令默认操作 `alembic.ini` 的 `data/npc.sqlite3`；自定义数据库明确使用 `-x database_url=...`，Alembic不会读取 `.env`。服务配置 `NPC_DATABASE_URL` 时优先于旧 `NPC_DB_PATH`。

需要共享数据库时，安装 `uv sync --extra postgres`（Windows使用 `requirements-postgres.txt`），设置 `NPC_POSTGRES_PASSWORD` 后用 `docker compose up -d postgres` 启动本地PostgreSQL，并配置服务：

```dotenv
NPC_DATABASE_URL=postgresql+psycopg://npc:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5432/npc
```

标准 `postgresql://` 也会规范化为psycopg3。密码中的保留字符必须URL编码。首次运行前对同一URL执行 `uv run alembic -x database_url=YOUR_DATABASE_URL upgrade head`。这里是新数据库部署选项，不自动把SQLite存档复制到PostgreSQL；保留原库可随时切回。

此版语义排序使用已授权候选集合的精确余弦相似度，尚未采用pgvector或近似索引。当前固定故事不需要向量数据库服务；以后有大量记忆和性能测量结果时再加入。真实模型冒烟记录见 `artifacts/framework-modernization/semantic-smoke.json`，不替代正式困难检索实验。

## 没有密钥也能验证哪些内容？

页面与所有明确标注的规则操作可使用：协助任务、确认承诺、借还钥匙、维修、取得/转述线索、通知事件与完成调查。
这些是确定性游戏机制，不是模拟AI聊天。自然语言聊天必须配置真实DeepSeek密钥；无密钥会明确提示，绝不偷偷用固定回答代替模型。
接口地址和模型可通过 `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 配置。仅接受HTTPS地址，不跟随重定向。

## 一次完整演示

1. 选择林掌柜，完成核对登记、搬运沙袋，两次各加5，信任由50变60。
2. 明确确认归还承诺，再借备用钥匙。
3. 切换周衡，修复配电箱。下一次有效行动结束前需还钥匙；切换角色和阅读页面不算行动。
4. 立即切回林掌柜归还：承诺完成，店主信任升到70。维修前提前归还不奖励，但允许再次借用。
5. 分别取得三位角色线索，选择“整理三条线索，完成调查”。

失信分支：维修后先做另一项有效动作或聊天，期限到达；此时店主尚未获知，不扣分。
在店主处点击告知失信事件，才扣15。重复通知不能重复扣分。晚归还不会抹去已经发生的失信。
模型失败、被拒绝的动作和页面切换不消耗归还期限。

## 调试与论文附件

在 `.env` 设置 `NPC_DEBUG=true` 和较长的 `NPC_DEBUG_TOKEN`，重启后端。在调试面板输入口令（仅存在内存中）。
可查看检索候选、评分、实际上下文、事件、角色获知时间、信任变化及请求耗时，导出JSON。调试包含剧透，不会送入NPC上下文。
导出会遮盖已配置密钥、常见密钥字符串和鉴权字段，但对自由文本中的个人信息不能保证完整识别；分享附件前人工检查。

附件应包含源码、锁定依赖、真实截图、配置示例、测试记录和实验数据；**不要打包 `.env`、虚拟环境、node_modules 或个人存档**。
对照实验说明见 [EXPERIMENTS.md](EXPERIMENTS.md)，预注册方案见[AGENTS_V2_EXPERIMENT_PLAN.md](AGENTS_V2_EXPERIMENT_PLAN.md)，当前交付状态见 [VERIFICATION.md](VERIFICATION.md)。

## 代码结构与验证

- `app/agents.py`：三个角色Agent的隔离视图、结构化决策校验和确定性回复；`app/game.py`：记忆检索、游戏事件和信任规则；`scene.json`：故事配置。
- `app/storage.py` / `db_models.py`：SQLAlchemy事务、请求去重、版本检查；`migrations/`：Alembic版本管理；`workflow.py`：LangGraph编排；`memory.py`：语义检索；`llm.py`：DeepSeek HTTP适配。
- `app/main.py`：API编排、输出验证与调试保护；`experiments.py`：独立受控实验工具。
- `frontend/`：Vue界面；`tests/`：规则、接口、并发、模型协议及统计测试。

```bash
uv sync --group dev --frozen
uv run pytest -q
uv run ruff check app tests
cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

浏览器端到端测试（先构建前端，确保8000端口未被占用）：

```bash
npx playwright install chromium
npm run test:e2e
```

测试会自行启动无密钥的后端，使用独立数据库，不调用付费模型。Linux若缺运行库，需安装Playwright所需系统依赖；本次WSL验证使用了临时解压的运行库，没有改动系统安装。截图在 `output/playwright/`。

API自动文档：<http://127.0.0.1:8000/docs>。接口约定见 [CONTRACT.md](CONTRACT.md)。

## 与论文初稿的差异与限制

- 为使第一版易读且能原子提交，SQLite使用会话JSON快照与独立请求表；快照内保留事件、知识、记忆、承诺等实体集合。论文中的多表关系图是概念设计，后续实现章节应如实描述这一差异。
- 新版支持本地嵌入的混合检索；旧实验仍使用字符命中与场景别名基线。未准备模型时透明回退。输入预算按Unicode字符而非模型token计数。
- 信任纠正通过“已验证的替代事件”撤销原贡献并顺序重算；提供底层函数与测试，不向玩家开放任意改事实/改分接口。
- 不承诺自然语言零幻觉或零秘密猜中；后端隔离与模型输出泄漏分别测试。自动测试使用显式测试替身，不代表真实模型效果。
- 受控输出能阻止模型把自由编造的句子直接写入存档，但模型仍可能选错相关事实或行动；真实模型小规模验收与限制记录在 `AGENTS_V2_REPORT.md`。
- 最新测试依赖可能产生上游弃用警告，详见验证记录；固定版本由 `uv.lock` 和 `frontend/package-lock.json` 管理。

官方接口参考：[DeepSeek JSON输出](https://api-docs.deepseek.com/guides/json_mode/)、[FastAPI测试](https://fastapi.tiangolo.com/tutorial/testing/)、[HTTPX传输测试](https://www.python-httpx.org/advanced/transports/)。
