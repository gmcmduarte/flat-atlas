"""Local-only tables keyed by work: one abstract and one vector per work (PLAN §4.2, D-70).

``local_abstract`` and ``local_embedding`` stay keyed by ``dblp_key``: the harvest and embed
stages write them before any work exists. After resolving, later stages read these two tables,
which have one row per work. When a work has several versions, the primary version's row wins,
then the others in key order.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from flatatlas.resolve.inputs import Inputs
from flatatlas.resolve.works import Resolved


def build_work_locals(
    inputs: Inputs, resolved: Resolved
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keys_of: dict[str, list[str]] = defaultdict(list)
    for key, work_id in resolved.work_of_key.items():
        keys_of[work_id].append(key)

    def ordered(work_id: str) -> list[str]:
        primary = resolved.primary_key_of_work[work_id]
        return [primary, *sorted(k for k in keys_of[work_id] if k != primary)]

    abstracts: list[dict[str, Any]] = []
    embeddings: list[dict[str, Any]] = []
    for work_id in sorted(keys_of):
        for key in ordered(work_id):
            if key in inputs.abstracts:
                source, text = inputs.abstracts[key]
                abstracts.append(
                    {
                        "work_id": work_id,
                        "dblp_key": key,
                        "source": source,
                        "text": text,
                        "n_chars": len(text),
                    }
                )
                break
        for key in ordered(work_id):
            row: Mapping[str, Any] | None = inputs.embeddings.get(key)
            if row is not None:
                embeddings.append(
                    {
                        "work_id": work_id,
                        "dblp_key": key,
                        "model": row.get("model"),
                        "source": row.get("source"),
                        "s2_corpus_id": row.get("s2_corpus_id"),
                        "input_kind": row.get("input_kind"),
                        "abstract_source": row.get("abstract_source"),
                        "vector": list(row["vector"]),
                    }
                )
                break
    return abstracts, embeddings
