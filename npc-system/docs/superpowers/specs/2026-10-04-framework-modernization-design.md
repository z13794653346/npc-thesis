# NPC 后端框架升级设计

用户范围：同时升级 AI 编排、存储和语义检索；默认按本机毕业演示优先，PostgreSQL 作为可选部署。保留 Vue 3 / FastAPI / Pydantic 2 和 DeepSeek HTTP 协议。

## 设计与约束

- LangGraph 将角色视图恢复、模型决策和依据校验编排为三个节点。仅返回决策与可观察轨迹；游戏动作与信任变化仍由现有规则和 Store 原子提交。不开持久 checkpoint，不建立第二份游戏权威，不宣传自主规划或 exactly-once 模型调用。
- SQLAlchemy 2 ORM 管理 sessions/requests，保留已有表名、列和 JSON 快照协议。Alembic 负责版本化迁移；升级旧 SQLite 不丢失会话/请求。SQLite 默认；支持 PostgreSQL URL，并提供 Docker/pgvector 部署说明。任意迁移在副本上验证，现有个人数据库不迁移。
- FastEmbed 使用 BAAI/bge-small-zh-v1.5（中文512维）本地推理；初次下载在显式预热命令中进行，请求路径只允许加载本地已有模型。语义检索先按 npc_id 和事件有效性过滤，再混合语义相似度、字符相关性、时间与重要性。未预热时明确报告 lexical fallback，不能伪称语义检索。向量按文本哈希和模型缓存于有界进程内LRU，重启不保留；失效事实始终在排序前排除。
- 保留原 API、NPC 知识边界、动作前置条件、承诺规则、请求编号幂等及乐观并发；旧版合成实验不冒充新版效果。嵌入真实验证与测试替身分开记录。

## 验收

原75项后端测试继续通过；新增旧库升级、事务回滚/并发、图节点路径和失败不提交、同义记忆排序和越权候选排除测试；ruff、前端类型检查和构建通过。真实中文嵌入至少一次独立 smoke，保留模型与检索结果。PostgreSQL若环境不可用须注明未运行，不能虚报。

## 参考

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
- https://alembic.sqlalchemy.org/en/latest/tutorial.html
- https://qdrant.github.io/fastembed/examples/Supported_Models/
- https://github.com/pgvector/pgvector
