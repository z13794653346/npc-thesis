"""Paid, opt-in grounding regression: six reviews and three end-to-end chats."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.game import build_context, new_state
from app.llm import ModelError, grounding_context
from app.main import ROOT, GroundingReview, create_app, redact
from scripts.live_smoke import RecordedModel


def main():
    parser = argparse.ArgumentParser(description="最多12次真实模型调用（含审查），可能产生费用。")
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    output = (
        ROOT
        / "artifacts"
        / ("live-grounding-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6])
    )
    output.mkdir(parents=True)
    model = RecordedModel(output, max_calls=12)
    if not model.configured:
        parser.error("未配置密钥，未调用模型")
    baseline = ROOT / "artifacts/live-smoke-20260920T051338-d4f410/model-calls.jsonl"
    old = [json.loads(line) for line in baseline.read_text(encoding="utf-8").splitlines()]
    records = []

    def record(entry):
        records.append(entry)
        with (output / "checks.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(redact(entry, model.api_key), ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {"case": entry["case"], "passed": entry["passed"], "calls": model.calls},
                ensure_ascii=False,
            ),
            flush=True,
        )

    # Actual old drafts: invented lamp oil duties, a witnessed shadow, and a conversation.
    cases = [
        (
            "baseline-" + str(i + 1),
            grounding_context(old[i]["context"], old[i]["raw_output"]["reply"]),
            False,
        )
        for i in (0, 2, 3)
    ]
    context, _ = build_context(new_state(), "owner", "你好")
    cases.append(
        (
            "supported-identity",
            grounding_context(context, "我是林掌柜，这里的店主。房间里的事，我无法确认。"),
            True,
        )
    )
    mechanic, _ = build_context(new_state(), "mechanic", "你好")
    cases.append(
        (
            "supported-mechanic-identity",
            grounding_context(mechanic, "我是旅店的维修员，姓周。"),
            True,
        )
    )
    # Regression for the first review pass's false negative, retained as a separate case.
    cases.append(
        (
            "unsupported-counter-and-all-guests",
            grounding_context(context, "登记簿放在柜台上，谁来了、谁走了，我都记。"),
            False,
        )
    )
    for name, review_context, expected in cases:
        try:
            raw = asyncio.run(model.complete(review_context))
            review = GroundingReview.model_validate(raw)
            accepted = review.supported and not review.unsupported_claims
            record(
                {
                    "case": name,
                    "passed": accepted == expected,
                    "expected_supported": expected,
                    "review": raw,
                }
            )
        except (ModelError, ValueError) as exc:
            record({"case": name, "passed": False, "error": getattr(exc, "code", "invalid_output")})

    app = create_app(db_path=output / "sessions.sqlite3", model=model, debug_token="")
    with TestClient(app) as client:
        for npc in ("owner", "mechanic", "traveler"):
            sid = client.post("/api/sessions").json()["id"]
            result = client.post(
                f"/api/sessions/{sid}/interactions",
                json={
                    "request_id": uuid4().hex,
                    "npc_id": npc,
                    "text": "你好。请简短介绍一下你在旅店里做什么，只谈你自己知道的事，不执行任何行动。",
                },
            ).json()
            record(
                {
                    "case": "greeting-" + npc,
                    "passed": result.get("status") == "completed",
                    "result": result,
                    "criterion": "实际生成并通过事实审查；仍需人工复核内容，拒绝会记为不通过",
                }
            )
            (output / (npc + "-debug.json")).write_text(
                json.dumps(
                    redact(app.state.store.debug(sid), model.api_key), ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )

    summary = {
        "model_calls": model.calls,
        "review_calls": model.review_calls,
        "max_http_attempts": model.calls * 2,
        "checks": [{"case": r["case"], "passed": r["passed"]} for r in records],
        "note": "固定旧错误样本与少量正常样本的开发复测，不是正式准确率。",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("OUTPUT=" + str(output), flush=True)


if __name__ == "__main__":
    main()
