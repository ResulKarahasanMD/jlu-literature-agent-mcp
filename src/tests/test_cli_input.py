from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from litlib import cli
from litlib.cli import _read_input_file
from litlib.state import State


def test_read_input_file_uses_doi_column_from_csv(tmp_path: Path):
    path = tmp_path / "works.csv"
    path.write_text("doi,title\n10.1000/example,Example title\n", encoding="utf-8")

    assert _read_input_file(str(path)) == ["10.1000/example"]


def test_read_input_file_keeps_plain_text_lines(tmp_path: Path):
    path = tmp_path / "works.txt"
    path.write_text("10.1000/one\n10.1000/two\n", encoding="utf-8")

    assert _read_input_file(str(path)) == ["10.1000/one", "10.1000/two"]


def test_verify_empty_is_not_success(monkeypatch, tmp_path: Path):
    state = State(tmp_path / "empty.db")
    monkeypatch.setattr(cli, "State", lambda: state)
    assert cli.cmd_verify(Namespace(task="")) == 1


def test_import_requires_lookup_before_opening_state():
    args = Namespace(lookup=False)
    assert cli.cmd_import(args) == 2


def test_queue_add_rejects_empty_input():
    args = Namespace(file="", inputs=[], source="test")
    assert cli.cmd_queue_add(args) == 2


def test_run_metadata_partial_failure_is_nonzero(monkeypatch):
    class FakeState:
        def close(self):
            pass

    async def partial(_state, limit=100):
        return {"processed": 2, "ok": 1, "failed": 1}

    import litlib.pipeline as pipeline

    monkeypatch.setattr(cli, "State", FakeState)
    monkeypatch.setattr(pipeline, "run_metadata", partial)
    args = Namespace(stage="fetch-metadata", limit=100, access_mode="auto")
    assert cli.cmd_run(args) == 1


def test_run_oa_empty_is_nonzero(monkeypatch):
    class FakeState:
        def close(self):
            pass

    async def empty(_state, limit=100):
        return {"processed": 0, "ok": 0, "requires_inst": 0, "failed": 0}

    import litlib.pipeline as pipeline

    monkeypatch.setattr(cli, "State", FakeState)
    monkeypatch.setattr(pipeline, "run_oa", empty)
    args = Namespace(stage="oa", limit=100, access_mode="auto")
    assert cli.cmd_run(args) == 1
