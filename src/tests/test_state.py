"""测试：去重顺序、状态机、任务队列。"""

from __future__ import annotations

from pathlib import Path

import pytest

from litlib.models import (
    TaskState,
    Work,
    dedupe_keys_for,
    parse_input_line,
    title_year_author_key,
    transition_allowed,
)
from litlib.state import DedupeConflictError, State


class TestParseInputLine:
    def test_doi(self):
        assert parse_input_line("10.1038/s41586-023-06016-3") == ("doi", "10.1038/s41586-023-06016-3")

    def test_doi_prefix(self):
        assert parse_input_line("DOI: 10.1038/s41586-023-06016-3") == ("doi", "10.1038/s41586-023-06016-3")

    def test_pmid_prefix(self):
        assert parse_input_line("PMID: 12345678") == ("pmid", "12345678")

    def test_pmcid(self):
        assert parse_input_line("PMC1234567") == ("pmcid", "PMC1234567")

    def test_arxiv(self):
        assert parse_input_line("arXiv:2101.00001") == ("arxiv", "2101.00001")
        assert parse_input_line("2101.00001") == ("arxiv", "2101.00001")

    def test_title(self):
        assert parse_input_line("Some Research Paper Title Here") == (
            "title", "Some Research Paper Title Here")

    def test_empty_and_header(self):
        assert parse_input_line("") is None
        assert parse_input_line("doi,title,year") is None


class TestDedupeKeys:
    def test_order_and_values(self):
        w = Work(
            doi="10.1000/XYZ",
            pmid="12345678",
            pmcid="PMC1000001",
            arxiv="2101.00001",
            title="The Title",
            year=2024,
            authors=[{"family": "Zhang", "given": "San"}],
        )
        keys = dedupe_keys_for(w)
        assert list(keys.keys()) == ["doi", "pmid", "pmcid", "arxiv", "title_year_author"]
        assert keys["doi"] == "10.1000/xyz"
        assert keys["pmcid"] == "PMC1000001"

    def test_sha256_included_when_passed(self):
        w = Work(title="Only Title", year=2024, authors=[{"family": "Li"}])
        keys = dedupe_keys_for(w, pdf_sha256="a" * 64)
        assert keys["sha256"] == "a" * 64

    def test_title_year_author_normalization(self):
        w = Work(title="  The! Title... ", year=2024, authors=[{"family": "Zhang"}])
        assert title_year_author_key(w) == "thetitle|2024|zhang"

    def test_chinese_titles_remain_distinct(self):
        first = Work(title="猪流行性腹泻病毒研究", year=2024, authors=[{"family": "张"}])
        second = Work(title="猪繁殖与呼吸综合征研究", year=2024, authors=[{"family": "张"}])
        assert title_year_author_key(first) == "猪流行性腹泻病毒研究|2024|张"
        assert title_year_author_key(first) != title_year_author_key(second)

    def test_missing_first_author_skips_key(self):
        w = Work(title="No Author", year=2024)
        assert title_year_author_key(w) is None


class TestStateMachine:
    def test_valid_transitions(self):
        assert transition_allowed(TaskState.QUEUED, TaskState.METADATA_FETCH)
        assert transition_allowed(TaskState.METADATA_FETCH, TaskState.DEDUPED)
        assert transition_allowed(TaskState.DEDUPED, TaskState.OA_OK)
        assert transition_allowed(TaskState.DEDUPED, TaskState.REQUIRES_INST)
        assert transition_allowed(TaskState.INST_QUEUED, TaskState.DOWNLOADING)
        assert transition_allowed(TaskState.DOWNLOADING, TaskState.VERIFYING)
        assert transition_allowed(TaskState.VERIFYING, TaskState.READY)
        assert transition_allowed(TaskState.READY, TaskState.PROPOSAL_GENERATED)
        assert transition_allowed(TaskState.PROPOSAL_GENERATED, TaskState.USER_REVIEWED)
        assert transition_allowed(TaskState.USER_REVIEWED, TaskState.IMPORTED)
        assert transition_allowed(TaskState.FAILED, TaskState.QUEUED)
        assert transition_allowed(TaskState.DOWNLOADING, TaskState.PAYWALLED)

    def test_invalid_transitions(self):
        assert not transition_allowed(TaskState.QUEUED, TaskState.READY)
        assert not transition_allowed(TaskState.READY, TaskState.IMPORTED)
        assert not transition_allowed(TaskState.IMPORTED, TaskState.QUEUED)
        assert not transition_allowed(TaskState.PAYWALLED, TaskState.QUEUED)


class TestStateDB:
    @pytest.fixture()
    def state(self, tmp_path: Path):
        s = State(tmp_path / "test.db")
        yield s
        s.close()

    def test_queue_add_and_dedupe(self, state: State):
        added, skipped = state.queue_add(["10.1038/s41586-023-06016-3", "PMID: 12345678", "10.1038/s41586-023-06016-3"])
        assert added == 2
        assert skipped == 1
        counts = state.state_counts()
        assert counts[TaskState.QUEUED.value] == 2

    def test_illegal_transition_raises(self, state: State):
        state.queue_add(["10.1038/s41586-023-06016-3"])
        task = state.list_tasks()[0]
        with pytest.raises(ValueError):
            state.set_state(task["id"], TaskState.READY)

    def test_full_pipeline_transition(self, state: State):
        state.queue_add(["PMID: 12345678"])
        task = state.list_tasks()[0]
        for s in (TaskState.METADATA_FETCH, TaskState.DEDUPED, TaskState.OA_OK,
                  TaskState.DOWNLOADING, TaskState.VERIFYING, TaskState.READY):
            assert state.set_state(task["id"], s)
        counts = state.state_counts()
        assert counts[TaskState.READY.value] == 1

    def test_failed_retry(self, state: State):
        state.queue_add(["10.1000/ABC"])
        task = state.list_tasks()[0]
        state.set_state(task["id"], TaskState.METADATA_FETCH)
        state.set_state(task["id"], TaskState.FAILED, error="http 404")
        state.set_state(task["id"], TaskState.QUEUED)
        row = state.get_task(task["id"])
        assert row["state"] == TaskState.QUEUED.value

    def test_recover_incomplete(self, state: State):
        state.queue_add(["10.1000/RECOVER"])
        task = state.list_tasks()[0]
        state.set_state(task["id"], TaskState.METADATA_FETCH)
        recovered, skipped = state.recover_incomplete()
        row = state.get_task(task["id"])
        assert (recovered, skipped) == (1, 0)
        assert row["state"] == TaskState.QUEUED.value
        assert row["attempt_count"] == 0

    def test_recover_respects_attempt_limit(self, state: State):
        state.queue_add(["10.1000/LIMIT"])
        task = state.list_tasks()[0]
        state.set_state(task["id"], TaskState.METADATA_FETCH)
        state._conn.execute(
            "UPDATE tasks SET attempt_count=max_attempts WHERE id=?", (task["id"],))
        state._conn.commit()
        recovered, skipped = state.recover_incomplete()
        assert (recovered, skipped) == (0, 1)
        assert state.get_task(task["id"])["state"] == TaskState.METADATA_FETCH.value

    def test_begin_attempt_respects_limit(self, state: State):
        state.queue_add(["10.1000/ATTEMPT"])
        task = state.list_tasks()[0]
        assert state.begin_attempt(task["id"])
        assert state.begin_attempt(task["id"])
        assert state.begin_attempt(task["id"])
        assert not state.begin_attempt(task["id"])

    def test_paused_state_requires_explicit_recovery(self, state: State):
        state.queue_add(["10.1000/PAUSED"])
        task = state.list_tasks()[0]
        for target in (TaskState.METADATA_FETCH, TaskState.DEDUPED, TaskState.OA_OK,
                       TaskState.DOWNLOADING, TaskState.HUMAN_REQUIRED):
            state.set_state(task["id"], target)
        assert state.recover_incomplete() == (0, 0)
        assert state.recover_incomplete(include_paused=True) == (1, 0)
        assert state.get_task(task["id"])["state"] == TaskState.QUEUED.value

    def test_route_attempt_audit(self, state: State):
        state.queue_add(["10.1000/ROUTE"])
        task = state.list_tasks()[0]
        route_id = state.start_route_attempt(task["id"], "direct-browser", "https://doi.org/10.1000/route")
        state.finish_route_attempt(route_id, "FAILED", "HTTP 403")
        row = state.get_route_attempts(task["id"])[0]
        assert row["route"] == "direct-browser"
        assert row["outcome"] == "FAILED"
        assert row["error"] == "HTTP 403"

    def test_metadata_dedupe_conflict_is_not_silent(self, state: State):
        state.queue_add(["First unique title", "Second unique title"])
        first, second = state.list_tasks()
        work1 = state.get_work(first["work_id"])
        work2 = state.get_work(second["work_id"])
        work1.doi = "10.1000/same"
        state.update_work(work1)
        work2.doi = "10.1000/same"
        with pytest.raises(DedupeConflictError, match="去重冲突"):
            state.update_work(work2)

    def test_readonly_state_does_not_write(self, tmp_path: Path):
        db = tmp_path / "readonly.db"
        writable = State(db)
        writable.queue_add(["10.1000/readonly"])
        writable.close()
        readonly = State(db, readonly=True)
        assert readonly.state_counts()[TaskState.QUEUED.value] == 1
        with pytest.raises(Exception):
            readonly.queue_add(["10.1000/no-write"])
        readonly.close()

    def test_route_attempt_redacts_query_and_webvpn_token(self, state: State):
        state.queue_add(["10.1000/SECRET"])
        task = state.list_tasks()[0]
        attempt_id = state.start_route_attempt(
            task["id"],
            "gateway",
            "https://vpn.jlu.edu.cn/https/secret-host-token/path?a=secret",
        )
        state.finish_route_attempt(attempt_id, "FAILED", "token=abc123")
        row = state.get_route_attempts(task["id"])[0]
        assert "secret-host-token" not in row["url"]
        assert "a=secret" not in row["url"]
        assert "abc123" not in row["error"]

    def test_mark_imported_requires_verified_key(self, state: State):
        state.queue_add(["10.1000/IMPORT"])
        task = state.list_tasks()[0]
        for target in (
            TaskState.METADATA_FETCH,
            TaskState.DEDUPED,
            TaskState.OA_OK,
            TaskState.DOWNLOADING,
            TaskState.VERIFYING,
            TaskState.READY,
            TaskState.PROPOSAL_GENERATED,
            TaskState.USER_REVIEWED,
        ):
            state.set_state(task["id"], target)
        with pytest.raises(ValueError, match="Zotero item key"):
            state.mark_imported(task["work_id"], None, "test")
        assert state.get_task(task["id"])["state"] == TaskState.USER_REVIEWED.value
        state.mark_imported(task["work_id"], "ABCDEFGH", "test")
        assert state.get_task(task["id"])["state"] == TaskState.IMPORTED.value
        assert state.get_zotero_map(task["work_id"])["zotero_key"] == "ABCDEFGH"

    def test_pdf_hash_conflict_is_not_silent(self, state: State):
        state.queue_add(["First hash title", "Second hash title"])
        first, second = state.list_tasks()
        state.add_file(first["work_id"], "first.pdf", "a" * 64, 100, "test")
        with pytest.raises(DedupeConflictError, match="SHA-256"):
            state.add_file(second["work_id"], "second.pdf", "a" * 64, 100, "test")
        assert state.get_files(second["work_id"]) == []
