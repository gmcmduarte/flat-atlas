"""Entity resolution (P1-04, PLAN §8): staging tables in, ``core_*`` tables out.

Everything except ``stage`` is a pure function over plain rows, so each rule is tested with small
synthetic inputs. ``stage.run`` is the only module that touches DuckDB, the ID registry and files.
"""
