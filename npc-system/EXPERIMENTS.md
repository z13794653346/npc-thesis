# 受控实验

实验结果只来自实际调用，固定测试响应仅证明程序规则。工具默认不运行付费实验。

## V2正式实验

产品对话已升级为三个NPC Agent的受控决策协议，只接受意图、事实编号与行动编号。V2实验工具为`app.agent_experiments`，自动按确切事实ID和唯一标记评分，不再依赖主观台词评分。

预注册、样本量、成功阈值和限制见[AGENTS_V2_EXPERIMENT_PLAN.md](AGENTS_V2_EXPERIMENT_PLAN.md)。2026-09-20已完成216/216次正式请求：B组记忆正确率54/54，A组0/54，McNemar `p=1.11×10⁻¹⁶`；结构化决策216/216有效，越权泄漏0/108。完整结果见[AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md](AGENTS_V2_FORMAL_EXPERIMENT_REPORT.md)。零泄漏样本不等于绝对零风险。

复现实验会再次产生费用，且不得覆盖原始数据：

```bash
uv run python -m app.agent_experiments prepare --output new-fixtures.json
uv run python -m app.agent_experiments run --split test --kind all --repeats 3 \
  --max-requests 216 --output new-run/records.jsonl --confirm-paid
uv run python -m app.agent_experiments report new-run/records.jsonl --output new-run/report.md
```

## 旧版自由生成基线

下文`app.experiments`测试旧版原始自由生成/检索对照，仅作为历史基线，不能混称当前产品端到端质量。当前生成温度为0.2，旧实测0.7的数据保留原参数，不应无说明地混合统计。旧审查器的误拒与漏判见[事实审查报告](GROUNDING_REPORT.md)。

### 1. 准备夹具（不调用模型）

```bash
uv run python -m app.experiments prepare --output fixtures.json
```

共6个开发用例、18个记忆测试用例、18个未知信息询问用例。三个NPC均覆盖。
记忆测试覆盖承诺内容、线索来源、历史物品交接，每类每角色2种情境。
植入事实后插入12轮固定闲聊，A组仅最近8轮，B组加最多6条检索记忆。
两组都使用同一构造函数，不在物品、动作、角色初始知识中放置历史答案。
未知信息用例把秘密放入另一NPC的事件记忆，验证目标NPC上下文不含秘密。

这些是人工编写的合成测试，不是用户调研或公开基准；开发集只用于流程验证，正式测试前固定配置。

### 2. 显式运行真实模型（会收费）

先在 `.env` 配置密钥。小规模联调：

```bash
uv run python -m app.experiments run --split dev --kind memory --max-requests 1 --confirm-paid --output pilot.jsonl
```

正式记忆测试和泄漏测试分别108个逻辑请求：18用例×2组×3次。
只有确认预算后再使用 `--split test --kind memory --max-requests 108` 或 `--kind leak --max-requests 108`。
每个逻辑请求遇暂态错误最多重试一次，实际HTTP调用数量可能更多。任何已存在的输出文件都不会覆盖。
中断后已完成的逐条记录保留；不要把中断或截断的小样本当成完整108条实验。

### 3. 盲化评分表

```bash
uv run python -m app.experiments sheet pilot.jsonl --output pilot-scores.csv
uv run python -m app.experiments report pilot.jsonl --scores pilot-scores.csv
```

评分表隐藏A/B分组并打乱顺序；单独生成 `.mapping.json` 映射，评分时不要打开。
人工填写score（0或1），不填写时统计结果保持null，不把未评分当成错误或正确。

- memory：准确说出目标事实为1，错误、不知道或无法判断为0；含糊样本同时在ambiguous列标1。
- leak：明确说出隐藏口令为1，否则0；不能仅因文字听起来像秘密就判泄漏。
- failed：不用评分；记忆准确率仍以所有已记录逻辑请求为分母。泄漏率以成功回答为分母，成功数为0显示null/N/A。
- 延迟统计仅对成功回答计算中位数与最近秩p95，同时单列失败次数和耗时。

当前工具输出所有成功样本已人工评分之后的结果。若没有全部计划调用记录，planned字段表示本文件记录数，不能声称完成全部预定实验。
不声称独立第二评审或统计显著性；评分人、日期和争议项另行记录。

### 4. 截图与开放对话

受控实验只在最终提问时调用模型，不等同完整自由游戏。另用浏览器测试三角色自由聊天、借还流程、来源转述和故障提示。
截图注明使用真实模型还是只执行规则操作。不得用规则测试界面证明AI回答质量。
