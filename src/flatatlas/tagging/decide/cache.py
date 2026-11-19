"""The answer cache ``local_decision`` (PLAN §4.4): one row per question asked.

Key: ``(work_id, question, option_order, model_sha256, prompt_version)``. ``question`` is ``l0`` for
the choice question and a topic ID for a yes/no question. ``probabilities`` of ``l0`` are indexed
by level-0 topic (in the order of the taxonomy file, whatever order the options were shown in);
those of a yes/no question are ``[p_yes, p_no]``. Each row also keeps a hash of the exact prompt:
if the topic text changed, the row is a miss and is replaced.

Local only (it lives under ``warehouse/local/``): prompts can contain abstracts (hard rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

from flatatlas.db import replace_table

TABLE = "local_decision"
L0 = "l0"
_S = pa.string()
SCHEMA = pa.schema(
    [
        ("work_id", _S),
        ("question", _S),
        ("option_order", pa.int16()),
        ("probabilities", pa.list_(pa.float32())),
        ("model_sha256", _S),
        ("prompt_version", _S),
        ("prompt_sha256", _S),
        ("model_file", _S),
        ("quantisation", _S),
        ("runtime", _S),
    ]
)

Key = tuple[str, str, int, str, str]


@dataclass(frozen=True)
class ModelInfo:
    """What provenance records about the model (D-98)."""

    file: str
    sha256: str
    quantisation: str
    runtime: str
    prompt_version: str


@dataclass
class WorkAnswers:
    """What the cache says about one work, by DAG topic index."""

    l0: dict[int, float] | None = None  # averaged over the option orders, sums to 1
    child: dict[int, float] = field(default_factory=dict)  # p(yes) per topic


class DecisionCache:
    def __init__(self, rows: dict[Key, dict] | None = None) -> None:
        self.rows: dict[Key, dict] = rows or {}
        self.dirty = 0

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def load(cls, con: duckdb.DuckDBPyConnection) -> DecisionCache:
        have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if TABLE not in have:
            return cls()
        rows: dict[Key, dict] = {}
        for r in con.sql(f"SELECT * FROM {TABLE}").to_arrow_table().to_pylist():
            rows[
                _key(
                    r["work_id"],
                    r["question"],
                    r["option_order"],
                    r["model_sha256"],
                    r["prompt_version"],
                )
            ] = r
        return cls(rows)

    def get(self, key: Key, prompt_sha: str) -> list[float] | None:
        row = self.rows.get(key)
        if row is None or row["prompt_sha256"] != prompt_sha:
            return None
        return list(row["probabilities"])

    def put(self, key: Key, prompt_sha: str, probs, info: ModelInfo) -> None:
        self.rows[key] = {
            "work_id": key[0],
            "question": key[1],
            "option_order": key[2],
            "probabilities": [float(p) for p in probs],
            "model_sha256": key[3],
            "prompt_version": key[4],
            "prompt_sha256": prompt_sha,
            "model_file": info.file,
            "quantisation": info.quantisation,
            "runtime": info.runtime,
        }
        self.dirty += 1

    def save(self, con: duckdb.DuckDBPyConnection, path: Path) -> None:
        ordered = sorted(
            self.rows.values(), key=lambda r: (r["work_id"], r["question"], r["option_order"])
        )
        replace_table(con, TABLE, pa.Table.from_pylist(ordered, schema=SCHEMA), path)
        self.dirty = 0

    def answers(
        self,
        info_sha: str,
        prompt_version: str,
        *,
        n_orders: int,
        l0_topics: list[int],
        topic_index: dict[str, int],
    ) -> dict[str, WorkAnswers]:
        """The answers of this model and prompt version, by work.

        ``l0_topics`` are the DAG indexes of the level-0 topics (the order of the stored
        probabilities); ``topic_index`` maps a topic ID to its DAG index.

        A work's level-0 answer counts only when all ``n_orders`` orders are cached.
        """
        per_work: dict[str, WorkAnswers] = {}
        orders: dict[str, list[np.ndarray]] = {}
        for key, row in self.rows.items():
            work, question, order, sha, version = key
            if sha != info_sha or version != prompt_version:
                continue
            wa = per_work.setdefault(work, WorkAnswers())
            if question == L0:
                if order < n_orders:
                    orders.setdefault(work, []).append(
                        np.asarray(row["probabilities"], dtype=float)
                    )
            elif question in topic_index:
                wa.child[topic_index[question]] = float(row["probabilities"][0])
        for work, arrs in orders.items():
            if len(arrs) == n_orders:
                m = np.mean(np.vstack(arrs), axis=0)
                m = m / m.sum()
                per_work[work].l0 = {t: float(p) for t, p in zip(l0_topics, m, strict=True)}
        return per_work


def _key(work: str, question: str, order: int, sha: str, version: str) -> Key:
    return (work, question, int(order), sha, version)


make_key = _key
