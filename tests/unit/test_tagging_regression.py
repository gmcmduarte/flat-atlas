"""Regression fixture (P1-07): 20 anchor papers whose title must put the expected topic first-ish.

The fixture holds anchor titles and the topic each must reach (``taxonomy/anchors.yaml``). Run
against the real ``taxonomy/topics.yaml`` with the phrase dictionary and title signal only (no
vectors, no warehouse), it guards the dictionary and the matcher. It does not measure accuracy:
anchors are easy cases (PLAN §9.6).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from tagging_helpers import cfg, part

from flatatlas.tagging import artefacts as art_mod
from flatatlas.tagging import inputs
from flatatlas.tagging.signals import lexical_row

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tagging" / "anchor_titles.yaml"


def test_twenty_anchor_titles_reach_their_expected_topic_in_the_top_three():
    works = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["works"]
    assert len(works) == 20
    file, dag = inputs.load_dag()
    include, exclude = art_mod.build_dictionary(file, dag, cfg(), [])
    misses = []
    for w in works:
        title_scores, _a, _r = lexical_row(include, exclude, part("W0", w["title"]), 1.5)
        ranked = sorted(title_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top3 = [dag.ids[t] for t, _v in ranked[:3]]
        if w["expected"] not in top3:
            misses.append((w["id"], w["expected"], top3))
    assert not misses
