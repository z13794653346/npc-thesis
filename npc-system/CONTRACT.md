# 第一版开发契约

范围：Python FastAPI / Vue 3 TypeScript / SQLite，本机单用户，三个NPC。
原始论文不修改。真实模型与测试替身严格分离；默认无假模型。

## REST API（前端同源 /api，开发时 Vite 代理到 127.0.0.1:8000）

- GET /api/health -> {status:"ok", model_configured:bool, model:string, debug_enabled:bool, dialogue_version:2}
- POST /api/sessions，无body -> State
- GET /api/sessions/{id} -> State
- POST /api/sessions/{id}/reset，无body -> 新State（原存档保留）
- POST /api/sessions/{id}/interactions，body {request_id:string,npc_id:string,text:string} -> Result
- POST /api/sessions/{id}/actions，body {request_id:string,npc_id:string,action:{kind:string,target?:string,evidence_id?:string}} -> Result
  确定性操作无需模型，不作为模拟聊天。允许 assist, confirm_promise, borrow, repair, return_item, notify, share, reveal, conclude。
- GET /api/sessions/{id}/debug，header X-Debug-Token -> {state,requests}，默认404，错误token403。
- GET /api/sessions/{id}/export，header X-Debug-Token -> 脱敏JSON，同上。

State = {id,version,round,scene:{title,intro},npcs:[{id,name,role,description,trust}],messages:[{id,npc_id,speaker:"player"|"npc"|"system",text}],clues:[{id,title,text,source,verified}],inventory:[{id,name}],commitments:[{id,npc_id,text,status,due_round:number|null}],tasks:[{id,title,npc_id,done}],available_actions:[{npc_id,kind,target,label}],ending:string|null}
Result = {request_id,status:"completed"|"failed"|"processing",reply:string,action_result:{ok:bool,message:string}|null,state:State,error:{code,message}|null}
HTTP validation/errors -> {detail:string} or FastAPI validation detail list; failed model calls return Result with status=failed. In-progress returns202. Conflict returns409.
NPC ids: owner（林掌柜）, mechanic（周衡）, traveler（沈岚）。
Actions UI: display backend available_actions filtered by selected npc; POST /actions directly for these actions. Explicit promise confirmation is a button from available_actions; never auto-confirm model suggestion. Sharing uses kind=share,target=selected clue id (recipient npc_id). Notifications offered via available_actions with target event id.
Save only session id in localStorage; render text with Vue interpolation, never v-html. New game confirm dialog clarifies old save kept.
Debug token typed in password input, kept in memory only; never localStorage. Debug tab warns of spoilers and excludes data from player notebook. No frontend key input.

## 后端边界

app/scene.json 持有角色与故事，app/game.py 纯状态/规则/检索，app/storage.py SQLite事务和请求幂等，app/llm.py DeepSeek适配，app/main.py REST编排。
记忆先隔离再排序；最近8轮，最多6条；0.6关键词+0.2时效+0.2重要性。
初始信任50，协助+5/任务仅一次，守约+10，失信-15，0..100；60可借。
两项店主协助任务无钥匙依赖。接受承诺后可借钥匙。维修后下一次有效操作结束为归还期限。角色获知失信事件后才扣分。
对话版本2采用三个逻辑NPC Agent，每轮按`(session_id,npc_id)`从存档恢复角色可见状态，不使用进程全局可变Agent实例。模型一次只返回严格结构`{intent,evidence_ids,action_id}`：事实编号必须来自该角色本轮候选，行动编号必须来自本轮可用行动；模型返回`reply`或任何额外字段均拒绝。
玩家可见NPC文字由程序生成：事实回答逐字使用候选事实并附来源/核实状态，行动回复使用规则实际执行结果，未知信息与澄清使用固定安全文本。玩家输入和历史台词可用于理解当前请求，但不能成为事实候选。未领取剧情线索不进入候选，合法`reveal`后才交付并写入笔记；转述事实保留原来源并标为未核实。
普通交互一次逻辑模型调用，与内部至多一次暂态HTTP重试共用默认30秒截止时间。承诺只能由显式UI操作确认；状态提交保持请求幂等和版本CAS。旧版自由`reply`与二次事实审查仅供实验基线使用，不在生产对话路径中。旧存档保留但因缺少`dialogue_version=2`而只读。
SQLite用单会话JSON快照保存实体集合（事件/知识/记忆/承诺/贡献序列），请求表独立，便于毕业设计阅读与原子提交。

## 工作分配与进度

- 主代理：后端、测试、实验工具和文档。
- 前端代理：仅 frontend/ 内实现与测试，遵守本契约。
- 完成后独立只读审查；不提交git，不部署公网。
- 当前：后端规则/API和前端已实现。后端44项、前端7项、浏览器4项测试已运行通过；最终验证见 VERIFICATION.md。
- 恢复会话后子任务工具不可恢复，主代理接管前端收尾，没有重复创建同类子任务。
- 审查修复：模型动作须精确匹配本次context.actions；补协议异常保护、提前归还防卡关、分享操作与前端幂等重试。
- 审查裁定：A/B只对模型上下文隔离，完整候选trace保留供诊断且不发给模型；人工评分对分组盲化但保留标准答案；泄漏率按成功回答为分母，失败另列。这些遵循论文既定实验方案。
