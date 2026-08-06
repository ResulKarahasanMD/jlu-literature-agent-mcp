from __future__ import annotations

from litlib.cnki import CNKI_CARSI_URL, CNKI_SEARCH_URL, is_cnki_challenge


def test_cnki_challenge_detection():
    assert is_cnki_challenge("https://kns.cnki.net/verify/home", "向右滑动完成验证")
    assert is_cnki_challenge(f"{CNKI_SEARCH_URL}?captchaId=example", "中国知网")
    assert is_cnki_challenge("https://kns.cnki.net/kns8s/defaultresult/index", "请完成安全验证")
    assert not is_cnki_challenge(CNKI_SEARCH_URL, "中国知网专业检索")


def test_cnki_entry_urls():
    assert CNKI_SEARCH_URL.startswith("https://kns.cnki.net/")
    assert CNKI_CARSI_URL == "https://fsso.cnki.net/"
