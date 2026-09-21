# 三个有状态NPC Agent与受控表达

用户已批准的方向：三个角色独立知识/记忆与工具权限，共享确定性游戏环境；不引入新框架，不让模型编写最终事实文本。

每个角色Agent从SQLite会话快照按session_id/npc_id恢复自己的状态视图，包含角色、可披露知识、已检索记忆和可用动作。实例按请求恢复而非使用进程全局可变状态，防止跨会话混用。只激活玩家选中的角色，一轮一次模型决策。

决策契约：`{intent: intro|answer|source|act|unknown|clarify, evidence_ids: string[], action_id: string|null}`。不接受reply、自由语气文本、自拟参数或额外字段。answer/source引用1至3个本次候选事实编号；act仅引用一个本次候选动作编号且不带事实；其他意图不能带事实或动作。

NpcAgent.restore(state,npc_id,query,memory_enabled=True)构建只读独立视图和候选清单；resolve(raw)返回受控回复、动作建议、已校验决策。最终输出来自已编写身份句式、原始受控事实及来源标签、规则执行结果。不把输入或模型文本填入句式。知识≠披露；不提供未领取线索正文；事件纠正继续生效。转述知识及share事件标为未核实，不能渲染成角色目击。

后端是调度器：加载存档→激活角色→一次模型决策→校验→执行规则/受控表达→原子提交。原REST Result保持兼容，消息新增可选dialogue_version/agent_id/evidence_ids便于审计。承诺仍需按钮确认，模型不能自动接受。非法决策、错误编号或模型失败不改变回合/信任/物品。合法但被规则拒绝的动作仍显示规则原因，不推进回合。

新存档dialogue_version=2。没有此版本的存档只读，保留GET、debug/export和reset，不允许新的交互/操作；旧请求结果属于历史记录，不清除。新对话上下文不使用旧自由台词为事实。原模型生成/审查仅保留为明确标注的离线基线，不走生产聊天路径。

代价：措辞自由度降低，模型仍可能选错意图或答非所问，不保证语义理解绝对正确；保证范围仅为未经授权的模型自由文本无法进入新NPC消息/事实。持久化与场景文件是可信输入边界，不防本机操作者篡改数据库。

研究依据：AgentScope中文核心概念与记忆文档、LangChain Subagents、Park等Generative Agents(2023)、Anthropic Building effective agents(2024)。只借鉴结构，不宣称采用完整SDK，也不把本项目的受控表达称为这些资料证明的零幻觉方法。
