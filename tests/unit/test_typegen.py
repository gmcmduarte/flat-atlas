"""JSON Schemas and TypeScript types come from the export models and stay in sync (P1-09)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from flatatlas.export import models, typegen


def test_committed_schemas_and_types_are_current():
    """The "in sync" check of CI: regenerate with `uv run flatatlas export types` after a change."""
    stale = typegen.out_of_date()
    assert not stale, f"out of date: {[p.name for p in stale]}; run `flatatlas export types`"


def test_one_schema_per_file_shape_and_one_interface_per_model():
    names = set(typegen.schemas())
    assert names == {f"{n}.schema.json" for n in models.SCHEMA_MODELS}
    ts = typegen.typescript()
    for model in models.TYPE_MODELS:
        assert f"export interface {model.__name__} {{" in ts


def test_field_kinds_become_the_right_types():
    class Inner(BaseModel):
        x: int

    class Sample(BaseModel):
        """A sample."""

        plain: str
        maybe: str | None
        optional: bool | None = None
        mixed: list[str | int]
        scores: dict[str, float]
        inner: Inner
        kind: models.TagStatus

    ts = typegen.interface(Sample)
    assert "\tplain: string;" in ts
    assert "\tmaybe: string | null;" in ts
    assert "\toptional?: boolean;" in ts
    assert "\tmixed: (string | number)[];" in ts
    assert "\tscores: Record<string, number>;" in ts
    assert "\tinner: Inner;" in ts
    assert "'tagged' | 'low_confidence' | 'untagged'" in ts
    assert ts.startswith("/** A sample. */")


def test_aliased_keys_are_quoted():
    assert "\t'builds-on': TopicEdge[];" in typegen.interface(models.TopicEdges)


def test_a_construct_it_does_not_know_is_an_error():
    class Odd(BaseModel):
        pair: tuple[int, str]

    with pytest.raises(typegen.TypeGenError):
        typegen.interface(Odd)


def test_the_generated_literal_aliases_match_the_models():
    ts = typegen.typescript()
    assert "export type LateralEdgeType = 'related' | 'builds-on' | 'shared-community';" in ts
