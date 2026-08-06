"""个人经验库（learn）测试：存储、去重合并、脱敏、查询与渲染。"""

from __future__ import annotations

import pytest

from litlib import experience


@pytest.fixture(autouse=True)
def isolated_experience(tmp_path, monkeypatch):
    """把经验文件隔离到临时目录，避免污染真实运行数据。"""
    target = tmp_path / "experience" / "experiences.json"
    monkeypatch.setattr(experience, "EXPERIENCE_FILE", target)
    return target


def test_record_success_creates_entry(isolated_experience):
    entry = experience.record_success("pubs.acs.org", "institution-login",
                                      url_pattern="https://pubs.acs.org/doi/pdf/{doi}",
                                      doi_prefix="10.1021")
    assert entry["domain"] == "pubs.acs.org"
    assert entry["route"] == "institution-login"
    assert entry["success_count"] == 1
    assert entry["source"] == "auto"
    assert isolated_experience.exists()


def test_record_success_merges_same_domain_route(isolated_experience):
    experience.record_success("pubs.acs.org", "direct-httpx")
    experience.record_success("pubs.acs.org", "direct-httpx")
    experiences = experience.load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success_count"] == 2
    assert experiences[0]["last_success"]


def test_record_success_distinct_routes_separate(isolated_experience):
    experience.record_success("pubs.acs.org", "direct-httpx")
    experience.record_success("pubs.acs.org", "direct-browser")
    assert len(experience.load_experiences()) == 2


def test_record_success_rejects_unsafe_routes(isolated_experience):
    for route in ("PAYWALLED", "HUMAN_REQUIRED", "RATE_LIMITED", "FAILED"):
        with pytest.raises(ValueError):
            experience.record_success("example.com", route)
    assert experience.load_experiences() == []


def test_record_success_sanitizes_url(isolated_experience):
    entry = experience.record_success(
        "example.com", "direct-httpx",
        url_pattern="https://example.com/pdf?token=abc123&x=1")
    assert "abc123" not in entry["url_pattern"]
    assert "redacted" in entry["url_pattern"]


def test_record_success_rejects_empty_domain(isolated_experience):
    with pytest.raises(ValueError):
        experience.record_success("", "direct-httpx")


def test_add_manual_requires_note(isolated_experience):
    with pytest.raises(ValueError):
        experience.add_manual("cnki.net", "cnki-pdf", notes="   ")
    with pytest.raises(ValueError):
        experience.add_manual("", "cnki-pdf", notes="说明")


def test_add_manual_merges_on_same_domain_route(isolated_experience):
    experience.add_manual("cnki.net", "cnki-pdf", notes="第一次说明")
    experience.add_manual("cnki.net", "cnki-pdf", notes="更新后的说明")
    experiences = experience.load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["notes"] == "更新后的说明"
    assert experiences[0]["source"] == "manual"


def test_remove_experience(isolated_experience):
    entry = experience.record_success("example.com", "direct-httpx")
    assert experience.remove_experience(entry["id"]) is True
    assert experience.remove_experience(entry["id"]) is False
    assert experience.load_experiences() == []


def test_find_for_domain_and_prefix(isolated_experience):
    experience.record_success("www.nature.com", "direct-httpx", doi_prefix="10.1038")
    experience.record_success("pubs.acs.org", "institution-login", doi_prefix="10.1021")

    hits = experience.find_for("nature.com")
    assert len(hits) == 1 and hits[0]["domain"] == "nature.com"

    hits = experience.find_for("unknown.com", doi="10.1038/s41586-025-12345-x")
    assert len(hits) == 1 and hits[0]["domain"] == "nature.com"

    assert experience.find_for("unknown.com") == []
    assert experience.find_for("", doi="10.1093/abc") == []


def test_find_for_sorts_by_success_count(isolated_experience):
    experience.record_success("a.com", "r1")
    experience.record_success("b.com", "r1")
    experience.record_success("b.com", "r1")
    hits = experience.find_for("b.com")
    assert len(hits) == 1 and hits[0]["success_count"] == 2


def test_render_markdown_empty(isolated_experience):
    text = experience.render_markdown()
    assert "空" in text
    assert "learn add" in text


def test_render_markdown_with_entries(isolated_experience):
    experience.record_success("pubs.acs.org", "institution-login",
                              url_pattern="https://pubs.acs.org/doi/pdf/{doi}",
                              doi_prefix="10.1021")
    experience.add_manual("cnki.net", "cnki-pdf", notes="需要人工滑块")
    text = experience.render_markdown()
    assert "pubs.acs.org" in text
    assert "cnki.net" in text
    assert "需要人工滑块" in text
    assert "canonical" in text


def test_corrupt_file_returns_empty(isolated_experience):
    isolated_experience.parent.mkdir(parents=True, exist_ok=True)
    isolated_experience.write_text("{not valid json", encoding="utf-8")
    assert experience.load_experiences() == []


def test_ensure_storage_path_respected(monkeypatch, tmp_path, isolated_experience):
    """非 D 盘且要求 D 盘时应拒绝写入经验文件。"""
    from litlib import config

    monkeypatch.setattr(config, "require_d_drive", lambda: True)
    monkeypatch.setattr(config, "on_d_drive", lambda path: False)
    isolated_experience.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        experience._save([{"id": "x"}])
