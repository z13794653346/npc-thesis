# NPC 记忆与信任交互系统

> 文字冒险游戏中的受控 NPC 交互：三个 NPC 拥有独立知识范围与长期记忆，大语言模型只返回结构化决策，由程序完成校验、确定性回复与原子化状态提交。

## 这是什么

针对文字冒险游戏里 NPC 长期记忆中断、角色间知识边界不清、合作行为缺乏可追溯依据三个问题的一个可运行实现，以「雨夜旅店调查」为演示场景。

- 后端 **FastAPI + LangGraph**：角色视图恢复 → 模型决策 → 依据校验，游戏规则独立执行
- 存储 **SQLAlchemy 2 + Alembic**：默认 SQLite，可选 PostgreSQL，保留请求幂等、并发版本控制和事务回滚
- 记忆 **FastEmbed 中文嵌入**：本地 CPU、512 维语义混合检索，先过滤角色权限及失效事件
- 前端 **Vue 3 + TypeScript + Vite**
- 大模型只返回 `{intent, evidence_ids, action_id}` 三字段，不能直接生成台词、不能直接改状态
- 测试：后端 **100 项** pytest、前端 **7 项**、浏览器端到端 **4 项**
- 实验工具与原始记录在 `npc-system/artifacts/`（固定夹具、216 次模型请求原始记录等）

## 目录结构

```
npc-system/    系统实现（FastAPI 后端 app/ + Vue 前端 frontend/ + 测试 tests/ + 实验工具）
.github/       CI（GitHub Actions）
```

## 快速开始

完整说明见 [npc-system/README.md](npc-system/README.md)，本次升级与验证见 [框架升级报告](npc-system/FRAMEWORK_UPGRADE_REPORT.md)。

### Windows

```powershell
cd npc-system
Copy-Item .env.example .env   # 仅在本机填入 DEEPSEEK_API_KEY
powershell -NoProfile -File .\start.ps1
```

### Linux / WSL

```bash
cd npc-system
cp .env.example .env          # 填入 DEEPSEEK_API_KEY
bash start.sh
```

首次使用语义记忆，在 `npc-system` 目录执行：

```bash
uv run python scripts/prepare_embeddings.py
uv run python scripts/verify_semantic_memory.py
```

Windows使用 `.venv-win/Scripts/python.exe` 运行相同脚本。首次模型下载需要联网，后续检索在本机执行；嵌入不需要新密钥。未准备模型时明确回退为词法检索，已有规则操作仍可运行。

启动后访问 <http://127.0.0.1:8000>，API 文档在 `/docs`。本版本没有多用户账号系统，请勿绑定公网。

## 测试

```bash
cd npc-system
uv sync --group dev --frozen
uv run pytest -q                    # 100 项
uv run ruff check app tests scripts migrations

cd frontend
npm ci
npm test                            # 7 项
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e                    # 4 项
```

## 说明

本仓库只包含系统实现与配套工程，不含论文、学校材料或任何个人身份信息。接口约定见 [npc-system/CONTRACT.md](npc-system/CONTRACT.md)，实验与交付状态见 [npc-system/VERIFICATION.md](npc-system/VERIFICATION.md)。
