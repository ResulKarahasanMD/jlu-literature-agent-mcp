"""Testler: içe aktarma önerisi üretimi (RIS + liste)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from litlib.importer import build_proposal, work_to_ris
from litlib.models import TaskState
from litlib.state import State


class TestRis:
    def test_work_to_ris_full(self):
        lines = work_to_ris(
            work_id="w1", title="A Study", doi="10.1000/xyz", year=2024,
            journal="J of X", volume="5", issue="2", pages="10-20",
            authors=[{"family": "Zhang", "given": "San"}, {"family": "Li"}],
            publisher="Pub Co",
        )
        joined = "\n".join(lines)
        assert "TY  - JOUR" in joined
        assert "TI  - A Study" in joined
        assert "AU  - Zhang, San" in joined
        assert "AU  - Li" in joined
        assert "PY  - 2024" in joined
        assert "SP  - 10" in joined and "EP  - 20" in joined
        assert "DO  - 10.1000/xyz" in joined
        assert "N1  - work_id: w1" in joined
        assert "ER  -" in joined

    def test_build_proposal_only_ready(self, tmp_path: Path):
        st = State(tmp_path / "t.db")
        st.queue_add(["PMID: 12345678"])
        task = st.list_tasks()[0]
        for s in (TaskState.METADATA_FETCH, TaskState.DEDUPED, TaskState.OA_OK,
                  TaskState.DOWNLOADING, TaskState.VERIFYING, TaskState.READY):
            st.set_state(task["id"], s)
        work = st.get_work(task["work_id"])
        work.title = "A Ready Paper"
        work.authors = [{"family": "Wang", "given": "Wu"}]
        st.update_work(work)
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        st.add_file(task["work_id"], str(pdf), "a" * 64, pdf.stat().st_size, "openalex")

        ris, manifest = build_proposal(st, out_dir=tmp_path)
        assert ris.exists() and manifest.exists()
        content = ris.read_text(encoding="utf-8")
        assert "TI  - A Ready Paper" in content
        with open(manifest, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["pdf_path"].endswith("x.pdf")
        assert rows[0]["ris_file"] == ris.name
        assert st.state_counts()[TaskState.PROPOSAL_GENERATED.value] == 1
        st.close()

    def test_proposal_prevalidation_avoids_partial_files_and_states(self, tmp_path: Path):
        st = State(tmp_path / "t.db")
        st.queue_add(["First proposal item", "Second proposal item"])
        tasks = st.list_tasks()
        for index, task in enumerate(tasks):
            st.set_state(task["id"], TaskState.METADATA_FETCH)
            work = st.get_work(task["work_id"])
            work.title = f"Proposal paper {index}"
            work.year = 2024
            work.authors = [{"family": f"Author{index}"}]
            st.update_work(work)
            for state in (
                TaskState.DEDUPED, TaskState.OA_OK, TaskState.DOWNLOADING,
                TaskState.VERIFYING, TaskState.READY,
            ):
                st.set_state(task["id"], state)
            pdf = tmp_path / f"paper-{index}.pdf"
            if index == 0:
                pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            st.add_file(task["work_id"], str(pdf), str(index) * 64, 20, "test")

        with pytest.raises(ValueError, match="kullanılabilir PDF yok"):
            build_proposal(st, out_dir=tmp_path / "out")

        assert not list((tmp_path / "out").glob("proposal_*"))
        assert all(task["state"] == TaskState.READY.value for task in st.list_tasks())
        st.close()

    def test_proposal_never_deletes_existing_outputs(self, monkeypatch, tmp_path: Path):
        st = State(tmp_path / "t.db")
        st.queue_add(["10.1000/proposal"])
        task = st.list_tasks()[0]
        st.set_state(task["id"], TaskState.METADATA_FETCH)
        work = st.get_work(task["work_id"])
        work.title = "No clobber proposal"
        work.year = 2024
        work.authors = [{"family": "Author"}]
        st.update_work(work)
        for state in (
            TaskState.DEDUPED, TaskState.OA_OK, TaskState.DOWNLOADING,
            TaskState.VERIFYING, TaskState.READY,
        ):
            st.set_state(task["id"], state)
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        st.add_file(task["work_id"], str(pdf), "a" * 64, 20, "test")

        class FixedNow:
            def strftime(self, _format):
                return "fixed"

        class FixedDatetime:
            @classmethod
            def now(cls):
                return FixedNow()

        import litlib.importer as importer
        monkeypatch.setattr(importer, "datetime", FixedDatetime)
        ris = tmp_path / "proposal_fixed.ris"
        manifest = tmp_path / "proposal_fixed_manifest.csv"
        ris.write_text("existing ris", encoding="utf-8")
        manifest.write_text("existing manifest", encoding="utf-8")

        with pytest.raises(FileExistsError):
            build_proposal(st, out_dir=tmp_path)

        assert ris.read_text(encoding="utf-8") == "existing ris"
        assert manifest.read_text(encoding="utf-8") == "existing manifest"
        assert st.get_task(task["id"])["state"] == TaskState.READY.value
        st.close()
