# NPC Agents Implementation Plan

> **For agentic workers:** Use executing-plans task by task. No Git repository exists; do not invent commits/worktrees. Existing persisted agents cannot be reopened by this surface; execute in the root lane.

**Goal:** 三个隔离有状态角色Agent选择合法事实/动作，程序生成所有玩家可见NPC文字。
**Architecture:** 恢复NPC状态视图，构建候选清单，一次模型决策，确定性校验/呈现，复用现有原子提交。
**Tech Stack:** Python/FastAPI/Pydantic/SQLite、Vue3；无新增依赖。
**Spec:** `docs/superpowers/specs/2026-09-20-npc-agents-design.md`

## Global Constraints

- 不修改论文、任务书、.env或已有真实模型测试数据。
- 不增加生产依赖；沿用中文界面、现有端点和规则。
- 对话版本2；旧存档只读可重开，拒绝行为不推进回合。
- 普通交互一次逻辑模型调用，内部暂态重试最多一次，默认总截止30秒。

## Task 1: 状态视图与确定性输出

Files: create `app/agents.py`, `tests/test_agents.py`; modify `app/game.py`。
Interfaces: `NpcAgent.restore(s,npc,query,memory_enabled=True)`; `.context`, `.trace`; `.resolve(raw)->(reply,action,decision)`。

- [x] 写测试并验证失败：
```python
agent = NpcAgent.restore(new_state(), 'mechanic', '介绍自己')
assert '铜铃-731' not in str(agent.context)
reply, action, _ = agent.resolve({'intent':'intro','evidence_ids':[],'action_id':None})
assert '周衡' in reply and action is None
```
- [x] 建立严格Decision Pydantic模型、角色身份模板、候选事实/动作映射；拒绝extra字段、非候选编号、混合intent。
- [x] 测试角色/会话隔离、长记忆A/B、来源标签、撤销事件、新旧版本和深拷贝隔离。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_agents.py tests/test_rules.py`。

## Task 2: API与模型决策集成

Files: modify `app/main.py`, `app/llm.py`, `tests/test_api.py`, `tests/test_llm.py`。
Consumes: Task1.restore/resolve；Produces: 与原Result兼容的受控回复和审计字段。

- [x] 先测试旧自由reply被拒绝、一轮一次模型调用、旧存档只读、动作依旧原子提交。
- [x] 替换生产路径ModelOutput/二次审查：
```python
agent = NpcAgent.restore(s, npc, body.text)
raw = await model_call(agent.context)
reply, action, decision = agent.resolve(raw)
```
- [x] act由apply_action执行并覆盖reply；其他合法意图tick。错误通过原ModelError失败路径返回，非法参数不写状态。
- [x] 原59项测试中更换被替代的协议/审查断言，保留并发409、幂等、回滚、来源、规则和传输测试。
- [x] 运行全部pytest及Ruff，审阅生产路径不存在自由reply回流。

## Task 3: 实测、界面说明与证据

Files: create `scripts/live_agents.py`, `AGENTS_V2_REPORT.md`; modify README/CONTRACT/EXPERIMENTS/VERIFICATION及App.vue提示文本。

- [x] 界面明确“AI选择事实与行动，台词由程序组织”；恢复旧存档时通过后端明确只读原因。
- [x] 新脚本最多10次真实调用：3次身份、未知目击、借用/维修/归还/两次领取、一次来源回答。独立存档，无规则兜底冒充模型成功。
- [x] 不改写旧输出；记录agent_id、决策、最终回复、规则结果与密钥扫描结果。
- [x] 执行pytest、Ruff、前端7项测试、类型检查/构建、浏览器4项回归。实测需单独网络授权，不扩为正式实验。
- [x] 写实际结果、未通过样本与局限，不宣称消除所有模型误解。

## Review / Progress

任务1与2共享resolve契约，先完成1再集成2；任务3消费Result，保持API兼容。各任务无新增依赖，与spec一致。
Ruling: 不使用进程全局持久化Agent实例，每轮从快照恢复，逻辑状态仍按角色隔离；避免并发会话污染。
