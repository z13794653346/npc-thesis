# 框架升级验证记录

日期：2026-10-04。运行环境：WSL/Linux、Python 3.12、Node.js 24。项目原测试基线75项。

## 实际交付

- LangGraph 1.2.12：恢复角色视图 → 单次结构化模型决策 → 依据/动作校验。节点耗时进入调试记录，非法决策或超时保留已完成阶段。游戏状态仍由Store统一提交，未启持久图检查点或自主规划。全局游戏快照不发送到外部LangSmith追踪。
- SQLAlchemy 2.0.54 / Alembic 1.20.0：兼容原sessions/requests及JSON快照；SQLite BEGIN IMMEDIATE、PostgreSQL reserve行锁、commit版本条件更新。旧库副本upgrade/downgrade/upgrade保留数据；没有迁移个人存档。
- FastEmbed 0.8.1：BAAI/bge-small-zh-v1.5，512维、本地CPU。模型已显式下载并通过实际检索；角色授权和有效事件过滤先于向量排序。模型缺失透明回退，查询期间不下载。向量采用2048项有界进程内LRU，不持久存数据库，重启重算。
- 保留Vue3/FastAPI；PostgreSQL为可选部署，附Docker配置和锁定驱动清单。没有加入pgvector或近似索引。

## 验证结果

| 检查 | 结果 |
|---|---|
| 后端pytest完整回归 | 100 passed，1个上游AnyIO弃用警告 |
| Ruff（app/tests/migrations/新脚本） | 通过 |
| 前端单测 | 7 passed |
| Vue类型检查与生产构建 | 通过 |
| Playwright真实浏览器 | 4 passed；完整规则故事、存档恢复、获知后信任更新、转述及移动端 |
| 旧SQLite副本迁移往返 | 通过，保留会话与请求记录 |
| 真实中文语义检索冒烟 | 相关记忆首位，其他角色及撤销事件未进入候选 |

后端报告：[backend-tests.xml](artifacts/framework-modernization/backend-tests.xml)。实际嵌入记录：[semantic-smoke.json](artifacts/framework-modernization/semantic-smoke.json)。浏览器新截图单独保存在 `artifacts/framework-modernization/browser-screenshots/`，原论文截图保持不变。

“电力恢复了吗”查询对“配电箱修好后，客栈恢复了供电”的实际余弦相似度约0.6151，对无关登记记录约0.2409。该人工冒烟用于证明真实向量路径可运行，不构成困难检索对照实验或优越性结论。此前216次正式实验仍属于旧词法基线，不重命名为本次新版成绩。

## 运行与限制

在npc-system目录运行 `bash start.sh` 或Windows的 `start.ps1` 会安装锁定依赖。语义模型已在当前工作区准备好；其他机器首次执行 `python scripts/prepare_embeddings.py` 下载后重启服务。详见[README](README.md)。

本次未运行真实PostgreSQL服务，也未验证Windows安装；PostgreSQL URL与迁移配置通过无连接单测。没有真实付费聊天调用；模型输出协议和图编排通过明确标注的测试替身验证。异步与浏览器测试在沙箱外执行，沙箱内socketpair/IPC权限会导致卡住或EPERM。
