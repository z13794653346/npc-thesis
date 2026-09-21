import asyncio
import json


def test_trial_context_changes_only_authorized_memory_visibility():
    from app.agent_experiments import build_trial
    from app.experiments import fixtures

    memory = next(c for c in fixtures() if c["split"] == "test" and c["kind"] == "memory")
    leak = next(c for c in fixtures() if c["kind"] == "leak")

    memory_a = build_trial(memory, "A")
    memory_b = build_trial(memory, "B")
    leak_a = build_trial(leak, "A")
    leak_b = build_trial(leak, "B")

    assert memory["expected"] not in str(memory_a["agent"].context)
    assert memory["expected"] in str(memory_b["agent"].context)
    assert leak["expected"] not in str(leak_a["agent"].context)
    assert leak["expected"] not in str(leak_b["agent"].context)
    assert memory_a["expected_fact_id"] == memory_b["expected_fact_id"]


def test_run_trials_scores_exact_ids_and_writes_each_result(tmp_path):
    from app.agent_experiments import run_trials
    from app.experiments import fixtures

    case = next(c for c in fixtures() if c["split"] == "test" and c["kind"] == "memory")

    class RetrievalAwareModel:
        model = "fixture-model"
        base_url = "https://model.invalid"
        api_key = ""

        def __init__(self):
            self.calls = 0

        async def complete(self, context):
            self.calls += 1
            fact = next((f for f in context["facts"] if case["expected"] in f["text"]), None)
            if fact:
                return {"intent": "answer", "evidence_ids": [fact["id"]], "action_id": None}
            return {"intent": "unknown", "evidence_ids": [], "action_id": None}

    output = tmp_path / "records.jsonl"
    model = RetrievalAwareModel()
    asyncio.run(run_trials([case], model, repeats=1, max_requests=2, output=output))
    records = [json.loads(line) for line in output.read_text().splitlines()]

    assert model.calls == 2 and len(records) == 2
    by_group = {record["group"]: record for record in records}
    assert by_group["A"]["correct"] is False
    assert by_group["B"]["correct"] is True
    assert by_group["B"]["selected_ids"] == [by_group["B"]["expected_fact_id"]]
    assert all(record["planned_total"] == 2 for record in records)


def test_analysis_uses_paired_exact_test_and_reports_guardrails():
    from app.agent_experiments import analyze

    records = []
    for i in range(6):
        for group in ("A", "B"):
            records.append(
                {
                    "id": f"memory-{i}-{group}-0",
                    "case": f"memory-{i}",
                    "repeat": 0,
                    "kind": "memory",
                    "group": group,
                    "valid": True,
                    "correct": group == "B",
                    "leaked": False,
                    "elapsed_ms": 10 + i,
                    "planned_total": 16,
                }
            )
    for i in range(2):
        for group in ("A", "B"):
            records.append(
                {
                    "id": f"leak-{i}-{group}-0",
                    "case": f"leak-{i}",
                    "repeat": 0,
                    "kind": "leak",
                    "group": group,
                    "valid": True,
                    "correct": False,
                    "leaked": False,
                    "elapsed_ms": 20,
                    "planned_total": 16,
                }
            )

    result = analyze(records)

    assert result["complete"] is True
    assert result["groups"]["memory/A"]["accuracy"] == 0
    assert result["groups"]["memory/B"]["accuracy"] == 1
    assert result["paired_memory"] == {
        "pairs": 6,
        "a_only": 0,
        "b_only": 6,
        "effect": 1,
        "p_value": 0.03125,
    }
    assert result["srm"]["a"] == result["srm"]["b"] == 8
    assert result["guardrails"]["zero_leaks"] is True
    assert result["guardrails"]["valid_rate_at_least_95pct"] is True
