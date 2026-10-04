"""Offline smoke for actual embedding retrieval; not a benchmark or model call."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.game import build_context, event, new_state
from app.memory import DEFAULT_CACHE_DIR, HybridMemoryRetriever


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", default="artifacts/framework-modernization/semantic-smoke.json")
    args = parser.parse_args()
    state = new_state()
    target = event(state, "fixture", "配电箱修好后，客栈恢复了供电。", ["owner"])
    event(state, "fixture", "旅客在大厅登记了姓名。", ["owner"])
    secret = event(state, "fixture", "只向维修员披露的秘密记录。", ["mechanic"])
    stale = event(state, "fixture", "配电箱仍然没有修好，客房停电。", ["owner"])
    stale["valid"] = False
    retriever = HybridMemoryRetriever(cache_dir=args.cache_dir)
    payload, trace = build_context(state, "owner", "电力恢复了吗", retriever=retriever)
    ids = [memory["id"] for memory in payload["memories"]]
    checks = {
        "real_semantic_model_used": trace["retrieval_strategy"] == "semantic_hybrid",
        "relevant_memory_first": ids[0] == target["id"],
        "other_role_excluded": secret["id"] not in ids,
        "invalid_event_excluded": stale["id"] not in ids,
    }
    report = {
        "kind": "offline_smoke_not_benchmark",
        "model": trace.get("embedding_model"),
        "retrieval_strategy": trace["retrieval_strategy"],
        "query": "电力恢复了吗",
        "checks": checks,
        "ranked_candidates": trace["candidates"],
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "report": str(path)}, ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit("Semantic smoke failed; inspect the recorded result.")


if __name__ == "__main__":
    main()
