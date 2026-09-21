"""Opt-in, bounded real-provider smoke checks. No production saves are used."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.experiments import experiment_context, fixtures
from app.llm import GENERATION_TEMPERATURE, REVIEW_TEMPERATURE, DeepSeek, ModelError
from app.main import ROOT, ModelOutput, create_app, redact


class RecordedModel(DeepSeek):
    def __init__(self, output, max_calls=20):
        super().__init__()
        self.output = output
        self.calls = 0
        self.max_calls = max_calls
        self.review_calls = 0
        self.blocked = False

    async def complete(self, context):
        if self.blocked or self.calls >= self.max_calls:
            raise ModelError("smoke_limit", "小规模测试已停止，不再发起模型请求。")
        self.calls += 1
        self.review_calls += int(context.get("task") == "grounding_review")
        entry = {
            "call": self.calls,
            "date": datetime.now(UTC).isoformat(),
            "model": self.model,
            "context": context,
            "temperature": REVIEW_TEMPERATURE
            if context.get("task") == "grounding_review"
            else GENERATION_TEMPERATURE,
            "max_output_tokens": 1200,
            "total_deadline_seconds": self.timeout,
        }
        started = time.monotonic()
        try:
            result = await super().complete(context)
            entry.update(status="received", raw_output=result)
            return result
        except ModelError as exc:
            entry.update(status="failed", error=exc.code, message=str(exc))
            if "密钥" in str(exc) or "余额" in str(exc):
                self.blocked = True
            raise
        finally:
            entry["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            with (self.output / "model-calls.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(redact(entry, self.api_key), ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="10个对话/实验步骤，含事实审查最多20次模型调用，可能产生费用。"
    )
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    parser.add_argument(
        "--regressions", action="store_true", help="用两次线索领取替代记忆对照，复测披露和动作回复"
    )
    args = parser.parse_args()
    assert args.confirm_paid
    load_dotenv(ROOT / ".env", override=False)
    output = (
        ROOT
        / "artifacts"
        / ("live-smoke-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6])
    )
    output.mkdir(parents=True)
    model = RecordedModel(output)
    if not model.configured:
        parser.error("未配置密钥；未发起任何模型调用。")
    app = create_app(db_path=output / "sessions.sqlite3", model=model, debug_token="")
    checks = []

    def record(name, result, passed=None, **details):
        entry = {"name": name, "passed": passed, "result": result, **details}
        checks.append(entry)
        with (output / "checks.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(redact(entry, model.api_key), ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {"check": name, "passed": passed, "calls_used": model.calls}, ensure_ascii=False
            ),
            flush=True,
        )

    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        route = f"/api/sessions/{sid}"

        def talk(name, npc, text):
            response = client.post(
                route + "/interactions",
                json={"request_id": uuid4().hex, "npc_id": npc, "text": text},
            )
            result = response.json()
            record(
                name,
                result,
                response.status_code == 200 and result.get("status") == "completed",
                criterion="真实API返回并通过应用输出验证；不代表角色内容已人工判定正确",
                http_status=response.status_code,
            )
            return result

        def action(npc, kind, target="", fallback=False):
            result = client.post(
                route + "/actions",
                json={
                    "request_id": uuid4().hex,
                    "npc_id": npc,
                    "action": {"kind": kind, "target": target},
                },
            ).json()
            record(
                "rule-" + kind,
                result,
                bool(result.get("action_result", {}).get("ok")),
                rule_fallback=fallback,
                criterion="确定性规则验证，不计作模型动作成功",
            )
            return result

        for npc in ("owner", "mechanic", "traveler"):
            greeting = talk(
                "greeting-" + npc,
                npc,
                "你好。请简短介绍一下你在旅店里做什么，只谈你自己知道的事，不执行任何行动。",
            )
            record(
                "greeting-no-clue-" + npc,
                {"reply": greeting.get("reply")},
                greeting.get("status") == "completed"
                and not any(
                    marker in greeting.get("reply", "")
                    for marker in ("铜铃-731", "十七分钟", "信件保管室", "二十年前", "转印字迹")
                ),
                criterion="仅检查已知剧情标记；仍需人工审阅，不能证明零泄漏",
            )
        secret = talk(
            "unknown-information",
            "owner",
            "你知道维修员的东翼维修记录里写的具体口令吗？如果不知道请直说，不要猜测，不执行任何行动。",
        )
        record(
            "unknown-information-marker",
            {"reply": secret.get("reply", "")},
            None
            if secret.get("status") != "completed"
            else "铜铃-731" not in secret.get("reply", ""),
            criterion="仅检查指定隐藏标记未被披露，不等于证明零泄漏；需人工复核回应",
        )
        low = talk("borrow-low-trust", "owner", "请现在把东翼备用钥匙借给我。")
        record(
            "low-trust-state",
            {"inventory": low.get("state", {}).get("inventory")},
            low.get("state", {}).get("inventory") == [],
            criterion="信任不足时不得实际交付钥匙",
        )
        for task in ("register", "sandbags"):
            action("owner", "assist", task)
        action("owner", "confirm_promise")

        for name, npc, text, kind, target in [
            (
                "borrow-qualified",
                "owner",
                "我已经完成两项协助并确认承诺。请现在把备用钥匙借给我，执行借用。",
                "borrow",
                "key",
            ),
            (
                "repair",
                "mechanic",
                "我带着备用钥匙，请现在和我一起修复配电箱，执行维修。",
                "repair",
                "",
            ),
            ("return", "owner", "我现在把备用钥匙归还给你，请执行归还。", "return_item", "key"),
        ]:
            result = talk(name, npc, text)
            outcome = result.get("action_result")
            ok = bool(outcome and outcome.get("ok"))
            record(
                name + "-execution",
                {"action_result": outcome},
                ok,
                criterion="模型明确提出合法动作且程序实际执行",
            )
            record(
                name + "-reply-consistency",
                {"reply": result.get("reply"), "action_result": outcome},
                ok and result.get("reply") == outcome["message"],
                criterion="展示回复与本次已验证执行结果一致；模型草稿不进入对话历史",
            )
            if not ok:
                action(npc, kind, target, fallback=True)

        final = client.get(route).json()
        record(
            "final-return-state",
            {
                "inventory": final["inventory"],
                "commitments": final["commitments"],
                "npcs": final["npcs"],
            },
            final["inventory"] == [] and final["commitments"][0]["status"] == "fulfilled",
            criterion="含明确标注的规则兜底步骤；单独记录模型动作成功情况",
        )

        if args.regressions:
            for npc, cid in [("mechanic", "maintenance"), ("owner", "registry")]:
                result = talk(
                    "reveal-" + cid, npc, "请现在提供并记录你掌握的那条线索，执行揭示线索。"
                )
                clue = next(
                    (c for c in result.get("state", {}).get("clues", []) if c["id"] == cid), None
                )
                record(
                    "reveal-notebook-" + cid,
                    {"reply": result.get("reply"), "clue": clue},
                    bool(
                        clue
                        and clue["text"] in result.get("reply", "")
                        and (result.get("action_result") or {}).get("ok")
                    ),
                    criterion="模型提出揭示动作，实际交付线索正文并同步记录笔记；无规则兜底",
                )

        case = next(c for c in fixtures() if c["split"] == "dev" and c["npc"] == "owner")
        groups = [] if args.regressions else [("A", False), ("B", True)]
        for group, enabled in groups:
            context, trace = experiment_context(case, enabled)
            try:
                raw = asyncio.run(model.complete(context))
                parsed = ModelOutput.model_validate(raw)
                allowed_ids = {k["id"] for k in context["knowledge"] + context["memories"]}
                if not set(parsed.evidence_ids) <= allowed_ids:
                    raise ValueError("invalid evidence")
                record(
                    "memory-" + group,
                    raw,
                    case["expected"] in parsed.reply,
                    group=group,
                    expected=case["expected"],
                    selected_ids=trace["selected_ids"],
                    expected_in_prompt=case["expected"] in json.dumps(context, ensure_ascii=False),
                    criterion="开发样本一次回答的目标标记精确匹配；不是正式准确率",
                )
            except (ModelError, ValueError) as exc:
                record(
                    "memory-" + group,
                    {"error": getattr(exc, "code", "invalid_output")},
                    False,
                    group=group,
                    criterion="调用或结构验证失败",
                )

        debug = redact(app.state.store.debug(sid), model.api_key)
        (output / "session-debug.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {
        "date": datetime.now(UTC).isoformat(),
        "model": model.model,
        "logical_calls": model.calls,
        "review_calls": model.review_calls,
        "max_model_calls": model.max_calls,
        "mode": "regressions" if args.regressions else "memory-smoke",
        "max_http_attempts": model.calls * 2,
        "checks": [{"name": c["name"], "passed": c["passed"]} for c in checks],
        "note": "最多20次模型调用，logical_calls含生成与事实审查；max_http_attempts是含重试的上限而非实际计数；不能作为正式论文实验结论。",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("OUTPUT=" + str(output), flush=True)


if __name__ == "__main__":
    main()
