import json


def test_live_agent_scenario_uses_ten_decisions_without_rule_fallback(tmp_path):
    from scripts.live_agents import run_scenario

    class ScriptedModel:
        model = "scripted-decision-model"
        configured = True
        api_key = ""
        max_calls = 10

        def __init__(self):
            self.calls = 0

        async def complete(self, context):
            self.calls += 1
            query = context["player_input"]
            if "介绍" in query:
                return {"intent": "intro", "evidence_ids": [], "action_id": None}
            if "具体口令" in query:
                return {"intent": "unknown", "evidence_ids": [], "action_id": None}
            if "借给我" in query:
                return {"intent": "act", "evidence_ids": [], "action_id": "borrow:key"}
            if "修复配电箱" in query:
                return {"intent": "act", "evidence_ids": [], "action_id": "repair:"}
            if "归还" in query:
                return {
                    "intent": "act",
                    "evidence_ids": [],
                    "action_id": "return_item:key",
                }
            if "维修线索" in query:
                return {
                    "intent": "act",
                    "evidence_ids": [],
                    "action_id": "reveal:maintenance",
                }
            if "登记簿线索" in query:
                return {
                    "intent": "act",
                    "evidence_ids": [],
                    "action_id": "reveal:registry",
                }
            if "来源" in query:
                fact = next(f for f in context["facts"] if f["source"] == "周衡")
                return {
                    "intent": "source",
                    "evidence_ids": [fact["id"]],
                    "action_id": None,
                }
            raise AssertionError(query)

    model = ScriptedModel()
    summary = run_scenario(model, tmp_path)

    assert model.calls == 10
    assert summary["logical_calls"] == 10
    assert summary["all_required_checks_passed"] is True
    assert summary["rule_fallbacks"] == 0
    assert (tmp_path / "session-debug.json").is_file()
    records = [json.loads(line) for line in (tmp_path / "checks.jsonl").read_text().splitlines()]
    source = next(record for record in records if record["name"] == "source-maintenance")
    assert source["passed"] is True
    assert source["decision"]["intent"] == "source"
