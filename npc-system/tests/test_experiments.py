def test_fixture_sizes_and_historical_answer_has_no_side_channel():
    from app.experiments import experiment_context, fixtures

    cases = fixtures()
    assert len([c for c in cases if c["split"] == "test" and c["kind"] == "memory"]) == 18
    assert len([c for c in cases if c["split"] == "dev"]) == 6
    assert len([c for c in cases if c["kind"] == "leak"]) == 18
    for case in cases:
        a, _ = experiment_context(case, False)
        b, _ = experiment_context(case, True)
        assert case["expected"] not in str(a)
        if case["kind"] == "memory":
            assert case["expected"] in str(b)
        else:
            assert case["expected"] not in str(b)


def test_metrics_keep_failed_calls_in_denominator_and_na_for_no_success():
    from app.experiments import summarize

    records = [
        {"group": "A", "kind": "memory", "status": "ok", "elapsed_ms": 100, "score": 1},
        {"group": "A", "kind": "memory", "status": "failed", "elapsed_ms": 30000, "score": None},
    ]
    summary = summarize(records)["memory/A"]
    assert summary["accuracy"] == 0.5 and summary["planned"] == 2
    assert summary["p95_ms"] == 100 and summary["failed"] == 1
    failed = summarize([{"group": "A", "kind": "leak", "status": "failed", "elapsed_ms": 30000}])
    assert failed["leak/A"]["leak_rate"] is None


def test_leak_metric_uses_successful_responses_not_failed_calls():
    from app.experiments import summarize

    r = summarize(
        [
            {"group": "B", "kind": "leak", "status": "ok", "elapsed_ms": 2, "score": 1},
            {"group": "B", "kind": "leak", "status": "failed", "elapsed_ms": 30},
        ]
    )["leak/B"]
    assert r["leak_rate"] == 1 and r["failed"] == 1 and r["planned"] == 2


def test_blind_sheet_hides_group_but_preserves_rubric(tmp_path):
    import csv

    from app.experiments import write_blind_sheet

    output = tmp_path / "scores.csv"
    write_blind_sheet(
        [
            {
                "id": "record-A",
                "group": "A",
                "kind": "memory",
                "query": "原暗号?",
                "expected": "雨灯",
                "reply": "雨灯",
                "status": "ok",
            }
        ],
        output,
    )
    with output.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert "group" not in rows[0] and "record-A" not in str(rows)
    assert rows[0]["expected"] == "雨灯" and rows[0]["score"] == ""
