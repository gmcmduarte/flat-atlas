import io
import logging

from flatatlas import log as flog
from helpers import FakeClock


def test_progress_logs_every_n_items_with_eta(caplog):
    clock = FakeClock()
    progress = flog.Progress("works", total=100, every=25, clock=clock.monotonic)
    with caplog.at_level(logging.INFO, logger="flatatlas.progress"):
        clock.sleep(10)
        progress.update(24)
        assert caplog.messages == []
        progress.update(1)  # crosses 25
        progress.update(50)  # crosses 50 and 75
    assert caplog.messages[0] == "works: 25/100 (2.5/s, ETA 30s)"
    assert len(caplog.messages) == 2


def test_setup_logging_writes_stderr_and_file_without_duplicates(tmp_path):
    stream = io.StringIO()
    flog.setup_logging(tmp_path, stream=stream)
    log_file = flog.setup_logging(tmp_path, stream=stream)  # second call replaces the handlers
    logging.getLogger("flatatlas.test").info("hello")
    flog.setup_logging(None, stream=io.StringIO())
    assert stream.getvalue().count("hello") == 1
    assert "hello" in log_file.read_text()
