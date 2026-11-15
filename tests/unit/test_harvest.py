import pytest

from flatatlas import db
from flatatlas.harvest import Page, get_state, paged
from flatatlas.settings import Settings


class Crash(BaseException):
    """Stands in for a kill: not caught by ``except Exception``."""


def make_fetch(pages: dict[str | None, Page], calls: list, crash_at: str | None = None):
    def fetch(cursor: str | None) -> Page:
        calls.append(cursor)
        if crash_at is not None and cursor == crash_at:
            raise Crash
        return pages[cursor]

    return fetch


PAGES = {
    None: Page(["a", "b"], "c2"),
    "c2": Page(["c", "d"], "c3"),
    "c3": Page(["e", "f"], "c4"),
    "c4": Page(["g"], "c5"),
    "c5": Page(["h"], None),
}


def test_killed_after_page_3_resumes_at_page_4(settings: Settings):
    con = db.connect(settings.paths)
    seen: list[str] = []

    calls: list = []
    with pytest.raises(Crash):
        for page in paged(con, "dblp", "job", make_fetch(PAGES, calls, crash_at="c4")):
            seen += page.items
    assert seen == ["a", "b", "c", "d", "e", "f"]  # pages 1-3
    state = get_state(con, "dblp", "job")
    assert (state.status, state.cursor, state.n_items) == ("interrupted", "c4", 6)

    # A new process: reopen the warehouse and run again.
    con.close()
    con = db.connect(settings.paths)
    calls = []
    for page in paged(con, "dblp", "job", make_fetch(PAGES, calls)):
        seen += page.items
    assert calls == ["c4", "c5"]  # page 1-3 are not fetched again
    assert seen == list("abcdefgh")
    state = get_state(con, "dblp", "job")
    assert (state.status, state.cursor, state.n_items) == ("done", None, 8)


def test_done_job_yields_nothing_unless_restarted(settings: Settings):
    con = db.connect(settings.paths)
    calls: list = []
    assert len(list(paged(con, "dblp", "job", make_fetch(PAGES, calls)))) == 5
    calls.clear()
    assert list(paged(con, "dblp", "job", make_fetch(PAGES, calls))) == []
    assert calls == []
    assert len(list(paged(con, "dblp", "job", make_fetch(PAGES, calls), restart=True))) == 5


def test_stopping_the_loop_early_keeps_the_page_for_next_time(settings: Settings):
    con = db.connect(settings.paths)
    calls: list = []
    gen = paged(con, "dblp", "job", make_fetch(PAGES, calls))
    next(gen)
    next(gen)  # now working on page 2
    gen.close()
    assert get_state(con, "dblp", "job").cursor == "c2"
    calls.clear()
    list(paged(con, "dblp", "job", make_fetch(PAGES, calls)))
    assert calls[0] == "c2"  # the unfinished page is repeated, not skipped


def test_jobs_are_independent(settings: Settings):
    con = db.connect(settings.paths)
    list(paged(con, "dblp", "one", make_fetch(PAGES, [])))
    assert get_state(con, "dblp", "two") is None
    assert get_state(con, "openalex", "one") is None
