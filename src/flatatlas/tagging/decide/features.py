"""Put the cached answers into the pair features as the raw ``dm_l0`` and ``dm_child`` columns.

Only works the selection rule sends (``active``) get values; for every other work both columns
stay NaN, even if an ``--all`` run cached answers for them. That keeps the training pairs like the
pairs the cascade will see: the step ran for the unsure works and for no one else.

- ``dm_l0`` of a level-0 pair: the choice probability of that topic, averaged over the option
  orders. Of a deeper pair: the value of its best level-0 ancestor (how likely the branch is).
- ``dm_child`` of a pair: the yes/no probability for that topic, when it was asked.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import numpy as np

from flatatlas.tagging.decide.cache import WorkAnswers
from flatatlas.tagging.inputs import Dag
from flatatlas.tagging.pairs import FEATURES, Pairs

I_L0 = FEATURES.index("dm_l0")
I_CHILD = FEATURES.index("dm_child")


def attach(
    pairs: Pairs,
    dag: Dag,
    work_ids: list[str],
    answers: Mapping[str, WorkAnswers],
    active: Collection[str],
) -> dict[str, int]:
    """Fill the two columns in place; returns counts for the log."""
    pairs.X[:, I_L0] = np.nan
    pairs.X[:, I_CHILD] = np.nan
    n_l0 = n_child = 0
    works_with = set()
    active = set(active)
    for i, (r, t) in enumerate(zip(pairs.work.tolist(), pairs.topic.tolist(), strict=True)):
        w = work_ids[r]
        wa = answers.get(w)
        if wa is None or w not in active:
            continue
        if wa.l0 is not None:
            level = dag.level[t]
            if level == 0:
                v = wa.l0.get(t)
            else:
                vals = [wa.l0[a] for a in dag.ancestors[t] if dag.level[a] == 0 and a in wa.l0]
                v = max(vals) if vals else None
            if v is not None:
                pairs.X[i, I_L0] = v
                n_l0 += 1
                works_with.add(w)
        if dag.level[t] >= 1 and t in wa.child:
            pairs.X[i, I_CHILD] = wa.child[t]
            n_child += 1
            works_with.add(w)
    return {"pairs_l0": n_l0, "pairs_child": n_child, "works": len(works_with)}
