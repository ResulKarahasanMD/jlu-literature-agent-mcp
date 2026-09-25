"""İçe aktarma önerisi: RIS dosyası + liste CSV'si (Phase 4)."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path

from litlib.config import paths
from litlib.models import TaskState
from litlib.state import State


def _authors_ris(authors: list[dict]) -> list[str]:
    out = []
    for a in authors:
        family = a.get("family") or ""
        given = a.get("given") or ""
        if not family and not given:
            continue
        out.append(f"AU  - {family}, {given}" if given else f"AU  - {family}")
    return out


def work_to_ris(work_id: str, title: str, doi: str | None, year: int | None,
                journal: str | None, volume: str | None, issue: str | None,
                pages: str | None, authors: list[dict], publisher: str | None,
                pdf_path: str = "") -> list[str]:
    lines = ["TY  - JOUR"]
    lines.append(f"TI  - {title}")
    lines.extend(_authors_ris(authors))
    if year:
        lines.append(f"PY  - {year}")
    if volume:
        lines.append(f"VL  - {volume}")
    if issue:
        lines.append(f"IS  - {issue}")
    if pages and "-" in pages:
        sp, _, ep = pages.partition("-")
        lines.append(f"SP  - {sp.strip()}")
        lines.append(f"EP  - {ep.strip()}")
    elif pages:
        lines.append(f"SP  - {pages}")
    if journal:
        lines.append(f"JO  - {journal}")
    if publisher:
        lines.append(f"PB  - {publisher}")
    if doi:
        lines.append(f"DO  - {doi}")
    if pdf_path:
        lines.append(f"L1  - {pdf_path}")
    lines.append(f"N1  - work_id: {work_id}")
    lines.append("ER  -")
    return lines


def build_proposal(st: State, out_dir: Path = paths.output,
                   work_ids: set[str] | None = None) -> tuple[Path, Path]:
    tasks = st.list_tasks(limit=1000)
    if work_ids is not None:
        tasks = [t for t in tasks
                 if t["work_id"] in work_ids
                 and t["state"] in (TaskState.READY.value, TaskState.PROPOSAL_GENERATED.value)]
    else:
        tasks = [t for t in tasks if t["state"] == TaskState.READY.value]
    if not tasks:
        raise ValueError("proposal üretilebilecek READY görev yok")
    records = []
    for task in tasks:
        work = st.get_work(task["work_id"])
        if not work or not work.title:
            raise ValueError(f"görev {task['id']} için eksiksiz metadata yok, proposal üretilemez")
        files = st.get_files(work.work_id)
        if not files or not Path(files[0]["path"]).exists():
            raise ValueError(f"görev {task['id']} için kullanılabilir PDF yok, proposal üretilemez")
        records.append((task, work, files[0]["path"]))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_dir.mkdir(parents=True, exist_ok=True)
    ris_path = out_dir / f"proposal_{stamp}.ris"
    csv_path = out_dir / f"proposal_{stamp}_manifest.csv"
    ris_buffer = io.StringIO(newline="\n")
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["work_id", "title", "doi", "year", "journal", "pdf_path", "ris_file"])
    for _task, work, pdf_path in records:
        lines = work_to_ris(
            work.work_id, work.title, work.doi, work.year, work.journal,
            work.volume, work.issue, work.pages, work.authors, work.publisher,
            pdf_path=pdf_path,
        )
        ris_buffer.write("\n".join(lines) + "\n")
        writer.writerow([
            work.work_id, work.title, work.doi, work.year,
            work.journal, pdf_path, ris_path.name,
        ])

    ris_part = ris_path.with_suffix(ris_path.suffix + ".part")
    csv_part = csv_path.with_suffix(csv_path.suffix + ".part")
    ris_created = False
    csv_created = False
    try:
        ris_part.write_text(ris_buffer.getvalue(), encoding="utf-8", newline="\n")
        csv_part.write_text("\ufeff" + csv_buffer.getvalue(), encoding="utf-8", newline="")
        if ris_path.exists() or csv_path.exists():
            raise FileExistsError("proposal output already exists")
        os.link(ris_part, ris_path)
        ris_created = True
        ris_part.unlink()
        os.link(csv_part, csv_path)
        csv_created = True
        csv_part.unlink()
        st.mark_proposal_generated([task["id"] for task, _work, _pdf in records])
    except Exception:
        ris_part.unlink(missing_ok=True)
        csv_part.unlink(missing_ok=True)
        if ris_created:
            ris_path.unlink(missing_ok=True)
        if csv_created:
            csv_path.unlink(missing_ok=True)
        raise
    return ris_path, csv_path
