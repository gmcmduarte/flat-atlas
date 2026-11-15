from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from flatatlas import ids
from flatatlas.ids import IdRegistry, RegistryError, choose_anchor, mint_id
from flatatlas.settings import Paths

NOW = datetime(2026, 11, 15, 12, 0)


def now() -> datetime:
    return NOW


# -- determinism -------------------------------------------------------------------------------


def test_same_anchor_gives_same_id_and_shape() -> None:
    a = mint_id("work", "dblp", "conf/dlt/Doe19")
    assert a == mint_id("work", "dblp", "conf/dlt/Doe19")
    assert a[0] == "W" and len(a) == 1 + ids.BASE_LENGTH
    assert a[1:].isalnum() and a[1:].isupper()


def test_ids_are_pinned() -> None:
    # IDs are published and must never change: a different hash or encoding fails here.
    assert mint_id("work", "dblp", "conf/dlt/Doe19") == "WT3SYS5P77T"
    assert mint_id("venue", "config", "dlt") == "V6JLZ7PKPCJ"
    assert mint_id("work", "doi", "10.1007/abc") == "W4K5UZBEIBA"


def test_kind_and_source_change_the_id() -> None:
    base = mint_id("work", "dblp", "x")
    assert mint_id("author", "dblp", "x")[1:] != base[1:]
    assert mint_id("work", "openalex", "x") != base
    assert {mint_id(k, "dblp", "x")[0] for k in ("work", "author", "venue", "edition")} == set(
        "WAVE"
    )


def test_anchor_spelling_is_normalised() -> None:
    plain = mint_id("work", "doi", "10.1007/abc")
    assert mint_id("work", "DOI", " https://doi.org/10.1007/ABC ") == plain
    assert mint_id("work", "doi", "doi:10.1007/abc") == plain


def test_empty_anchor_is_refused() -> None:
    with pytest.raises(RegistryError):
        mint_id("work", "dblp", "  ")


def test_anchor_preference_order() -> None:
    assert choose_anchor({"openalex": "W1", "doi": "10.1/x", "dblp": "k/1"}) == ("dblp", "k/1")
    assert choose_anchor({"openalex": "W1", "doi": "10.1/x"}) == ("doi", "10.1/x")
    assert choose_anchor({"zbmath": "1", "s2": "9"}) == ("s2", "9")
    with pytest.raises(RegistryError):
        choose_anchor({"orcid": "x"})


# -- registry ----------------------------------------------------------------------------------


def test_get_or_mint_is_stable_and_registers_once() -> None:
    reg = IdRegistry()
    first = reg.get_or_mint("work", "dblp", "k/1", now=now)
    assert reg.get_or_mint("work", "dblp", "k/1", now=now) == first
    assert first == mint_id("work", "dblp", "k/1")
    assert len(reg) == 1


def test_mint_from_uses_preferred_anchor() -> None:
    reg = IdRegistry()
    wid = reg.mint_from("work", {"doi": "10.1/x", "openalex": "W9"}, now=now)
    assert wid == mint_id("work", "doi", "10.1/x")
    assert reg.mint_from("work", {"doi": "10.1/x"}, now=now) == wid
    assert len(reg) == 1


def test_a_better_anchor_appearing_later_does_not_change_the_id() -> None:
    reg = IdRegistry()
    wid = reg.mint_from("work", {"doi": "10.1/x"}, now=now)
    # DBLP is preferred over DOI, but the work already has an ID anchored on its DOI.
    assert reg.mint_from("work", {"dblp": "conf/dlt/Doe19", "doi": "10.1/x"}, now=now) == wid
    assert len(reg) == 1


def test_mint_from_refuses_anchors_that_point_to_different_ids() -> None:
    reg = IdRegistry()
    reg.get_or_mint("work", "doi", "10.1/x", now=now)
    reg.get_or_mint("work", "openalex", "W9", now=now)
    with pytest.raises(RegistryError, match="merge them explicitly"):
        reg.mint_from("work", {"doi": "10.1/x", "openalex": "W9"}, now=now)


def test_collision_takes_a_longer_id_and_never_reuses(monkeypatch: pytest.MonkeyPatch) -> None:
    real = ids.mint_id
    # Force every anchor to the same short hash by pinning the 10-character prefix.
    monkeypatch.setattr(
        ids,
        "mint_id",
        lambda kind, source, anchor_id, *, length=ids.BASE_LENGTH: (
            real("work", "dblp", "fixed", length=length)[: 1 + ids.BASE_LENGTH]
            + real(kind, source, anchor_id, length=length)[1 + ids.BASE_LENGTH :]
        ),
    )
    reg = IdRegistry()
    one = reg.get_or_mint("work", "dblp", "a", now=now)
    two = reg.get_or_mint("work", "dblp", "b", now=now)
    assert one != two and len(one) == 1 + ids.BASE_LENGTH and len(two) == len(one) + 1
    assert reg.get_or_mint("work", "dblp", "a", now=now) == one


def test_merge_redirect_chain_and_resolve() -> None:
    reg = IdRegistry()
    a, b, c = (reg.get_or_mint("work", "dblp", k, now=now) for k in ("a", "b", "c"))
    assert reg.resolve(a) == a
    assert reg.merge(a, b) == b
    assert reg.merge(b, c) == c
    assert reg.resolve(a) == c  # a -> b -> c
    assert reg.resolve(b) == c
    assert reg.entry(a).merged_into == b  # history is kept
    assert reg.merge(a, c) == c  # repeating a holding merge (via the chain) is harmless


def test_merging_into_a_merged_id_points_at_the_survivor() -> None:
    reg = IdRegistry()
    a, b, c = (reg.get_or_mint("work", "dblp", k, now=now) for k in ("a", "b", "c"))
    reg.merge(b, c)
    assert reg.merge(a, b) == c
    assert reg.entry(a).merged_into == c


def test_merge_refusals() -> None:
    reg = IdRegistry()
    a, b, c = (reg.get_or_mint("work", "dblp", k, now=now) for k in ("a", "b", "c"))
    v = reg.get_or_mint("venue", "config", "dlt", now=now)
    with pytest.raises(RegistryError, match="itself"):
        reg.merge(a, a)
    with pytest.raises(RegistryError, match="different kinds"):
        reg.merge(a, v)
    reg.merge(a, b)
    with pytest.raises(RegistryError, match="leads to it"):
        reg.merge(b, a)  # would make a cycle
    with pytest.raises(RegistryError, match="already merged into"):
        reg.merge(a, c)
    with pytest.raises(RegistryError, match="unknown atlas ID"):
        reg.resolve("WNOSUCHID00")


def test_merged_id_is_not_reminted_for_its_anchor() -> None:
    reg = IdRegistry()
    a = reg.get_or_mint("work", "dblp", "a", now=now)
    b = reg.get_or_mint("work", "dblp", "b", now=now)
    reg.merge(a, b)
    assert reg.get_or_mint("work", "dblp", "a", now=now) == a  # same ID, not a fresh one
    assert reg.resolve(a) == b
    assert len(reg) == 2


# -- persistence -------------------------------------------------------------------------------


def test_registry_survives_reload(tmp_path: Path) -> None:
    reg = IdRegistry()
    a, b, c = (reg.get_or_mint("work", "dblp", k, now=now) for k in ("a", "b", "c"))
    v = reg.get_or_mint("venue", "config", "dlt", now=now)
    reg.merge(a, b)
    reg.merge(b, c)
    path = reg.save(Paths(tmp_path))
    assert path.name == "core_id_registry.parquet"

    again = IdRegistry.load(Paths(tmp_path))
    assert len(again) == 4
    assert again.resolve(a) == c
    assert again.entry(a).minted_at == NOW
    assert again.lookup("work", "dblp", "a") == a
    assert again.get_or_mint("venue", "config", "dlt", now=now) == v  # no new ID
    # New IDs continue to work after reload, and saving twice gives the same content.
    d = again.get_or_mint("work", "dblp", "d", now=now)
    again.save(Paths(tmp_path))
    assert d in IdRegistry.load(Paths(tmp_path))


def test_missing_file_is_an_empty_registry(tmp_path: Path) -> None:
    assert len(IdRegistry.load(Paths(tmp_path))) == 0


def test_saved_columns_match_plan(tmp_path: Path) -> None:
    reg = IdRegistry()
    reg.get_or_mint("work", "dblp", "a", now=now)
    path = reg.save(tmp_path / "r.parquet")
    assert pq.read_table(path).column_names == [
        "atlas_id",
        "kind",
        "anchor_source",
        "anchor_id",
        "minted_at",
        "merged_into",
    ]
