"""Explicitly download/prepare the local Chinese embedding model for requests."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory import DEFAULT_CACHE_DIR, MODEL_NAME, QUERY_PREFIX


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()
    from fastembed import TextEmbedding

    model = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=args.cache_dir,
        local_files_only=False,
        providers=["CPUExecutionProvider"],
        threads=2,
    )
    query = next(iter(model.embed([QUERY_PREFIX + "电力恢复了吗"])))
    documents = list(model.embed(["配电箱修好后，客栈恢复了供电。", "旅客在大厅登记了姓名。"]))
    scores = [float(query @ vector) for vector in documents]
    print(
        json.dumps(
            {"model": MODEL_NAME, "dimensions": len(query), "smoke_similarity": scores},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
