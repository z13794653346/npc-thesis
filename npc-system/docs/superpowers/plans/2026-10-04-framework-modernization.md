# Framework Modernization Implementation Plan

> **For agentic workers:** Use scoped execution and meaningful regression tests; integrate only after independent slices complete.

**Goal:** 引入 LangGraph、SQLAlchemy 2/Alembic 和可验证的本地中文语义检索，保持原有游戏与API兼容。
**Architecture:** Store 作为游戏唯一提交边界；流程图只计算决策，检索只读取已授权有效记忆。默认本机运行。
**Tech Stack:** Vue3 / FastAPI / LangGraph / SQLAlchemy2 / Alembic / FastEmbed / SQLite；PostgreSQL为可选。
**Spec:** ../specs/2026-10-04-framework-modernization-design.md

## Global Constraints

- Python >=3.12；不读取或输出 .env 内容。
- 不迁移个人数据库，仅使用测试副本；不删除旧数据。
- 图不提交游戏；不共享跨请求Session；所有角色权限检查先于语义排序。

## Task 1: ORM 与迁移

Files: app/storage.py, app/db_models.py, alembic.ini, migrations/, tests/test_storage_modern.py。
- [x] 新增旧表数据保持、重复reserve、事务回滚测试，先运行红灯。
- [x] SQLAlchemy ORM替换实现并保留Store公开接口；提供StorageError以统一主API异常。
- [x] 迁移已有SQLite至head，检查会话/请求未变化；提供PostgreSQL连接支持。

## Task 2: 语义检索

Files: app/memory.py, app/game.py, app/agents.py, scripts/prepare_embeddings.py, tests/test_memory.py。
- [x] 测试同义查询、候选过滤、缓存及模型未准备时透明降级。
- [x] 实现FastEmbed中文模型和仅本地加载；保留原词法模式作为基线。
- [x] 使用可注入retriever连接NPC上下文；异步流程在工作线程完成CPU检索。

## Task 3: 工作流

Files: app/workflow.py, tests/test_workflow.py。
- [x] 测试恢复→决策→校验轨迹、无效决策抛错、无全局状态污染。
- [x] 编译LangGraph并异步调用，保留model_call回调以延续已有超时；不启checkpoint。

## Task 4: 集成、部署和验证

Files: app/main.py, pyproject.toml, uv.lock, requirements.txt, .env.example, README.md, docker-compose.yml。
- [x] 集成新Store异常及图输出，更新调试轨迹和health。
- [x] 锁定依赖并导出Windows requirements；部署配置不携带真实密钥。
- [x] 完整pytest/ruff/frontend检查；真实嵌入smoke及迁移副本验收，报告验证限制。

## 完成证据

2026-10-04：后端100项、前端7项、浏览器4项通过；ruff、类型检查和构建通过。真实512维中文嵌入与权限/失效过滤冒烟通过。PostgreSQL仅验证URL规范化与部署配置，未连接真实服务；向量缓存采用有界进程内LRU，不新增数据库向量表。
