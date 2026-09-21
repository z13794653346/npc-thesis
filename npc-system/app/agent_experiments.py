"""Pre-registered evaluation for the production dialogue-version-2 agents."""

import argparse
import asyncio
import hashlib
import json
import math
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.agents import DIALOGUE_VERSION, NpcAgent
from app.experiments import fixtures
from app.game import apply_action, event, message, new_state, tick
from app.llm import GENERATION_TEMPERATURE, DeepSeek, ModelError
from app.main import ROOT, redact

EXPERIMENT_VERSION = "agents-v2.1"
RANDOM_SEED = 20260920


def build_trial(case, group):
    """Build an isolated role snapshot; only group B enables memory retrieval."""
    if group not in {"A", "B"}:
        raise ValueError("实验分组必须是A或B")
    state = new_state()
    npc = case["npc"]
    witness = npc if case["kind"] == "memory" else next(n for n in state["npcs"] if n != npc)
    injected = event(state, "fixture", case["fact"], [witness])
    message(state, witness, "player", case["fact"])
    message(state, witness, "npc", "我记下了。")
    for index in range(12):
        tick(state)
        message(state, npc, "player", f"看看窗外的雨，第{index + 1}次闲聊。")
        message(state, npc, "npc", "雨还没有停。")
    agent = NpcAgent.restore(state, npc, case["query"], memory_enabled=group == "B")
    return {
        "agent": agent,
        "state": state,
        "npc": npc,
        "expected_fact_id": injected["id"],
        "expected_in_context": case["expected"] in json.dumps(agent.context, ensure_ascii=False),
    }


def evaluate_trial(case, trial, raw):
    """Apply the same strict decision and deterministic rendering used in production."""
    agent = trial["agent"]
    try:
        reply, action, decision = agent.resolve(raw)
        outcome = None
        if action:
            outcome = apply_action(trial["state"], trial["npc"], action)
            reply = outcome["message"]
        selected = decision["evidence_ids"]
        correct = (
            case["kind"] == "memory"
            and trial["expected_fact_id"] in selected
            and case["expected"] in reply
        )
        return {
            "status": "ok",
            "valid": True,
            "correct": correct,
            "leaked": case["kind"] == "leak" and case["expected"] in reply,
            "selected_ids": selected,
            "decision": decision,
            "reply": reply,
            "action_result": outcome,
        }
    except (ModelError, ValidationError, ValueError) as exc:
        return {
            "status": "failed",
            "valid": False,
            "correct": False,
            "leaked": False,
            "selected_ids": [],
            "error": getattr(exc, "code", "invalid_output"),
        }


async def run_trials(
    cases,
    model,
    *,
    repeats,
    max_requests,
    output: Path,
    resume=False,
):
    """Run a deterministic shuffled prefix and flush every completed logical request."""
    if repeats < 1 or max_requests < 1:
        raise ValueError("重复次数和请求上限必须大于0")
    trials = [
        (case, group, repeat) for case in cases for group in ("A", "B") for repeat in range(repeats)
    ]
    random.Random(RANDOM_SEED).shuffle(trials)
    selected_trials = trials[: min(max_requests, len(trials))]
    existing = []
    if output.exists():
        if not resume:
            raise FileExistsError("输出文件已存在；请使用新路径或显式续跑")
        existing = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    completed = {record["id"] for record in existing}
    mode = "a" if output.exists() else "x"
    with output.open(mode, encoding="utf-8") as stream:
        for case, group, repeat in selected_trials:
            record_id = f"{case['id']}-{group}-{repeat}"
            if record_id in completed:
                continue
            trial = build_trial(case, group)
            started = time.monotonic()
            record = {
                "id": record_id,
                "case": case["id"],
                "group": group,
                "kind": case["kind"],
                "npc": case["npc"],
                "repeat": repeat,
                "expected": case["expected"],
                "expected_fact_id": trial["expected_fact_id"],
                "expected_in_context": trial["expected_in_context"],
                "query": case["query"],
                "model": model.model,
                "base_url": model.base_url,
                "date": datetime.now(UTC).isoformat(),
                "temperature": GENERATION_TEMPERATURE,
                "dialogue_version": DIALOGUE_VERSION,
                "experiment_version": EXPERIMENT_VERSION,
                "random_seed": RANDOM_SEED,
                "planned_total": len(selected_trials),
                "fixture_hash": hashlib.sha256(
                    json.dumps(case, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
                "context": trial["agent"].context,
            }
            try:
                raw = await model.complete(trial["agent"].context)
                record["raw_output"] = raw
                record.update(evaluate_trial(case, trial, raw))
            except ModelError as exc:
                record.update(
                    status="failed",
                    valid=False,
                    correct=False,
                    leaked=False,
                    selected_ids=[],
                    error=exc.code,
                )
            record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            stream.write(
                json.dumps(redact(record, getattr(model, "api_key", "")), ensure_ascii=False) + "\n"
            )
            stream.flush()


def _wilson(successes, total, z=1.96):
    if total == 0:
        return [None, None]
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return [max(0, center - margin), min(1, center + margin)]


def _mcnemar_exact(a_only, b_only):
    discordant = a_only + b_only
    if discordant == 0:
        return 1.0
    smaller = min(a_only, b_only)
    tail = sum(math.comb(discordant, value) for value in range(smaller + 1)) / (2**discordant)
    return min(1.0, 2 * tail)


def analyze(records):
    """Analyze only pre-registered outcomes; subgroup data remains descriptive."""
    groups = {}
    for kind in ("memory", "leak"):
        for group in ("A", "B"):
            rows = [r for r in records if r["kind"] == kind and r["group"] == group]
            if not rows:
                continue
            valid = sum(bool(r["valid"]) for r in rows)
            correct = sum(bool(r["correct"]) for r in rows)
            leaks = sum(bool(r["leaked"]) for r in rows)
            elapsed = sorted(r["elapsed_ms"] for r in rows)
            groups[f"{kind}/{group}"] = {
                "n": len(rows),
                "valid": valid,
                "valid_rate": valid / len(rows),
                "correct": correct,
                "accuracy": correct / len(rows),
                "accuracy_ci95": _wilson(correct, len(rows)),
                "leaks": leaks,
                "leak_rate": leaks / len(rows),
                "leak_ci95": _wilson(leaks, len(rows)),
                "median_ms": statistics.median(elapsed),
                "p95_ms": elapsed[math.ceil(0.95 * len(elapsed)) - 1],
                "failed": len(rows) - valid,
            }

    paired = {}
    for record in records:
        if record["kind"] == "memory":
            paired.setdefault((record["case"], record["repeat"]), {})[record["group"]] = bool(
                record["correct"]
            )
    complete_pairs = [pair for pair in paired.values() if set(pair) == {"A", "B"}]
    a_only = sum(pair["A"] and not pair["B"] for pair in complete_pairs)
    b_only = sum(pair["B"] and not pair["A"] for pair in complete_pairs)
    a_accuracy = groups.get("memory/A", {}).get("accuracy", 0)
    b_accuracy = groups.get("memory/B", {}).get("accuracy", 0)
    paired_memory = {
        "pairs": len(complete_pairs),
        "a_only": a_only,
        "b_only": b_only,
        "effect": b_accuracy - a_accuracy,
        "p_value": _mcnemar_exact(a_only, b_only),
    }

    a_count = sum(r["group"] == "A" for r in records)
    b_count = sum(r["group"] == "B" for r in records)
    expected = (a_count + b_count) / 2
    chi_square = (
        0
        if expected == 0
        else (a_count - expected) ** 2 / expected + (b_count - expected) ** 2 / expected
    )
    srm = {
        "a": a_count,
        "b": b_count,
        "chi_square": chi_square,
        "p_value": math.erfc(math.sqrt(chi_square / 2)),
        "detected": math.erfc(math.sqrt(chi_square / 2)) < 0.01,
    }
    total = len(records)
    valid_rate = sum(bool(r["valid"]) for r in records) / total if total else 0
    guardrails = {
        "zero_leaks": all(not r["leaked"] for r in records),
        "valid_rate": valid_rate,
        "valid_rate_at_least_95pct": valid_rate >= 0.95,
    }
    planned = max((r.get("planned_total", 0) for r in records), default=0)
    complete = total == planned and len({r["id"] for r in records}) == total
    primary_passed = (
        bool(complete_pairs)
        and b_accuracy >= 0.5
        and paired_memory["effect"] >= 0.3
        and paired_memory["p_value"] < 0.05
    )
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "records": total,
        "planned": planned,
        "complete": complete,
        "groups": groups,
        "paired_memory": paired_memory,
        "srm": srm,
        "guardrails": guardrails,
        "primary_passed": primary_passed,
        "overall_passed": complete
        and not srm["detected"]
        and primary_passed
        and guardrails["zero_leaks"]
        and guardrails["valid_rate_at_least_95pct"],
    }


def render_report(result):
    def percent(value):
        return "N/A" if value is None else f"{value * 100:.2f}%"

    lines = [
        "# 三NPC Agent V2正式实验结果",
        "",
        f"- 完整性：{result['records']}/{result['planned']}，{'完整' if result['complete'] else '不完整'}",
        f"- SRM：A={result['srm']['a']}，B={result['srm']['b']}，p={result['srm']['p_value']:.6g}",
        f"- 总体判定：{'通过' if result['overall_passed'] else '未通过'}",
        "",
        "## 分组指标",
        "",
        "| 分组 | n | 有效率 | 记忆准确率 | 泄漏率 | 中位延迟(ms) | p95(ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, group in result["groups"].items():
        lines.append(
            f"| {name} | {group['n']} | {percent(group['valid_rate'])} | "
            f"{percent(group['accuracy'])} | {percent(group['leak_rate'])} | "
            f"{group['median_ms']:.2f} | {group['p95_ms']:.2f} |"
        )
    paired = result["paired_memory"]
    lines.extend(
        [
            "",
            "## 预注册判定",
            "",
            f"- 记忆差值B-A：{percent(paired['effect'])}",
            f"- McNemar：A独有={paired['a_only']}，B独有={paired['b_only']}，p={paired['p_value']:.6g}",
            f"- 零泄漏护栏：{'通过' if result['guardrails']['zero_leaks'] else '失败'}",
            f"- 决策有效率：{percent(result['guardrails']['valid_rate'])}",
            "",
            "结果只适用于本项目固定合成样本和当前模型配置，不代表真实玩家总体或绝对零风险。",
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="NPC Agent V2预注册实验。run会产生API费用。")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--split", choices=["dev", "test"], default="test")
    run.add_argument("--kind", choices=["memory", "leak", "all"], default="all")
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--max-requests", type=int, required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--confirm-paid", action="store_true", required=True)
    report = sub.add_parser("report")
    report.add_argument("input", type=Path)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = [
        case
        for case in fixtures()
        if case["split"] == getattr(args, "split", "test")
        and (getattr(args, "kind", "all") == "all" or case["kind"] == args.kind)
    ]
    if args.command == "prepare":
        if args.output.exists():
            parser.error("输出文件已存在，请使用新路径。")
        args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已生成固定夹具；未调用模型。")
    elif args.command == "run":
        if args.repeats < 1 or args.max_requests < 1:
            parser.error("重复次数和请求上限必须大于0。")
        load_dotenv(ROOT / ".env", override=False)
        model = DeepSeek()
        if not model.configured:
            parser.error("未配置密钥；未发起任何模型调用。")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(
            run_trials(
                cases,
                model,
                repeats=args.repeats,
                max_requests=args.max_requests,
                output=args.output,
                resume=args.resume,
            )
        )
        print("已逐条保存实际调用记录；中断时可使用相同参数和--resume续跑。")
    else:
        records = [
            json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line
        ]
        result = analyze(records)
        json_output = args.output.with_suffix(".json")
        if args.output.exists() or json_output.exists():
            parser.error("报告文件已存在，请使用新路径。")
        args.output.write_text(render_report(result), encoding="utf-8")
        json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
