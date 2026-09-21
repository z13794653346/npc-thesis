"""Bounded real-model acceptance run for dialogue version 2."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.main import ROOT, create_app, redact
from scripts.live_smoke import RecordedModel


def run_scenario(model, output: Path):
    """Run ten model decisions plus deterministic setup actions in an isolated save."""
    output.mkdir(parents=True, exist_ok=True)
    app = create_app(
        db_path=output / "sessions.sqlite3",
        model=model,
        debug_token="local-live-agent-audit",
    )
    checks = []

    def record(name, passed, *, result=None, decision=None, required=True, **details):
        entry = {
            "name": name,
            "passed": bool(passed),
            "required": required,
            "decision": decision,
            "result": result,
            **details,
        }
        entry = redact(entry, getattr(model, "api_key", ""))
        checks.append(entry)
        with (output / "checks.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {
                    "check": name,
                    "passed": bool(passed),
                    "calls_used": getattr(model, "calls", None),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return entry

    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        route = f"/api/sessions/{sid}"

        def request_trace(request_id):
            requests = app.state.store.debug(sid)["requests"]
            return next(item["trace"] for item in requests if item["request_id"] == request_id)

        def talk(name, npc, text, predicate):
            request_id = uuid4().hex
            response = client.post(
                route + "/interactions",
                json={"request_id": request_id, "npc_id": npc, "text": text},
            )
            result = response.json()
            trace = request_trace(request_id)
            decision = trace.get("decision")
            passed = (
                response.status_code == 200
                and result.get("status") == "completed"
                and predicate(result, decision)
            )
            record(
                name,
                passed,
                result=result,
                decision=decision,
                agent_id=trace.get("agent_id"),
                dialogue_version=trace.get("dialogue_version"),
                criterion="模型只选择意图、事实编号或动作编号；玩家可见文字由程序生成。",
            )
            return result

        def rule(name, npc, kind, target=""):
            result = client.post(
                route + "/actions",
                json={
                    "request_id": uuid4().hex,
                    "npc_id": npc,
                    "action": {"kind": kind, "target": target},
                },
            ).json()
            passed = bool((result.get("action_result") or {}).get("ok"))
            record(
                name,
                passed,
                result=result,
                required=True,
                mode="deterministic_setup",
                rule_fallback=False,
                criterion="前置状态由明确标注的规则操作建立，不计作模型动作成功。",
            )
            return result

        identities = {"owner": "林掌柜", "mechanic": "周衡", "traveler": "沈岚"}
        for npc, name in identities.items():
            talk(
                "intro-" + npc,
                npc,
                "你好，请只介绍你自己的身份，不执行行动。",
                lambda result, decision, expected=name: (
                    decision == {"intent": "intro", "evidence_ids": [], "action_id": None}
                    and expected in result.get("reply", "")
                ),
            )

        talk(
            "unknown-private-code",
            "owner",
            "维修员的东翼维修记录里写了什么具体口令？不知道就说明没有确切依据。",
            lambda result, decision: (
                decision == {"intent": "unknown", "evidence_ids": [], "action_id": None}
                and "铜铃-731" not in result.get("reply", "")
            ),
        )

        rule("setup-assist-register", "owner", "assist", "register")
        rule("setup-assist-sandbags", "owner", "assist", "sandbags")
        rule("setup-confirm-promise", "owner", "confirm_promise")

        def action_is(action_id):
            return lambda result, decision: (
                bool((result.get("action_result") or {}).get("ok"))
                and (decision or {}).get("action_id") == action_id
            )

        talk(
            "borrow-key",
            "owner",
            "我已完成协助并作出承诺，请现在把备用钥匙借给我。",
            action_is("borrow:key"),
        )
        talk(
            "repair-box",
            "mechanic",
            "我带着备用钥匙，请现在修复配电箱。",
            action_is("repair:"),
        )
        talk(
            "return-key",
            "owner",
            "我现在归还备用钥匙。",
            action_is("return_item:key"),
        )
        maintenance = talk(
            "reveal-maintenance",
            "mechanic",
            "请把你掌握的维修线索交给我并记录。",
            action_is("reveal:maintenance"),
        )
        talk(
            "reveal-registry",
            "owner",
            "请把登记簿线索交给我并记录。",
            action_is("reveal:registry"),
        )

        acquired = {clue["id"] for clue in maintenance.get("state", {}).get("clues", [])}
        if "maintenance" in acquired:
            rule("setup-share-maintenance", "owner", "share", "maintenance")
        else:
            record(
                "setup-share-maintenance",
                False,
                mode="deterministic_setup",
                rule_fallback=False,
                criterion="只有实际领取维修线索后才执行转述。",
            )

        talk(
            "source-maintenance",
            "owner",
            "刚才转述给你的维修信息来自谁？请说明来源和是否已核实。",
            lambda result, decision: (
                (decision or {}).get("intent") == "source"
                and bool((decision or {}).get("evidence_ids"))
                and "来源：周衡" in result.get("reply", "")
                and "未核实" in result.get("reply", "")
            ),
        )

        debug = redact(app.state.store.debug(sid), getattr(model, "api_key", ""))
        (output / "session-debug.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = {
        "date": datetime.now(UTC).isoformat(),
        "model": model.model,
        "dialogue_version": 2,
        "logical_calls": getattr(model, "calls", None),
        "max_model_calls": getattr(model, "max_calls", 10),
        "max_http_attempts": getattr(model, "max_calls", 10) * 2,
        "all_required_checks_passed": all(check["passed"] for check in checks if check["required"]),
        "checks": [{"name": check["name"], "passed": check["passed"]} for check in checks],
        "note": "小规模工程验收，不是正式论文实验；失败项原样保留，不使用规则兜底冒充模型成功。",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="对三个NPC Agent执行最多10次真实模型决策，可能产生费用。"
    )
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    args = parser.parse_args()
    assert args.confirm_paid
    load_dotenv(ROOT / ".env", override=False)
    output = (
        ROOT
        / "artifacts"
        / ("live-agents-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6])
    )
    model = RecordedModel(output, max_calls=10)
    if not model.configured:
        parser.error("未配置密钥；未发起任何模型调用。")
    summary = run_scenario(model, output)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print("OUTPUT=" + str(output), flush=True)


if __name__ == "__main__":
    main()
