"""판의 첫 걸음 `site_list` 는 날 JSON 이 아니라 사람이 읽는 표로 보인다 (2026-10-30 · 10-29 촬영 판 e943efe4).

보낸 직후 손자리 칸이 열리며 「Current step · Result · site_list · json 3,386 chars」 — 레시피 JSON 이 5초 동안 본문을 차지했다.
사이트마다 할 일 목록이 중첩돼 「dict 목록이면 표」가 표를 포기했기 때문이다.
"""

from __future__ import annotations

from alture_jarvis.observations import shape

RESULT = {
    "sites": [
        {
            "site": "naver_blog",
            "description": "네이버 블로그 SmartEditor ONE. 2026-08-05 실전 성공한 절차를 데이터로 옮긴 것",
            "hosts": ["blog.naver.com", "admin.blog.naver.com"],
            "actions": [{"action": "save_draft", "risk": "L2", "params": ["title", "body"], "description": "임시저장"}],
        },
        {
            "site": "wikipedia_ko",
            "description": "위키백과 검색",
            "hosts": ["ko.wikipedia.org"],
            "verification": "verified",
            "usage": {"runs": 3, "succeeded": 3},
            "actions": [{"action": "search", "risk": "L0", "params": ["query"], "description": ""},
                        {"action": "open_page", "risk": "L0", "params": ["title"], "description": ""}],
        },
    ]
}


def test_the_known_sites_become_a_table_not_a_json_wall() -> None:
    kind, title, payload, _ = shape("site_list", {}, RESULT)
    assert kind == "table" and title == "site_list · 2"
    assert payload["columns"] == ["site", "actions", "hosts", "verified"]
    assert payload["rows"][1] == ["wikipedia_ko", "search · open_page", "ko.wikipedia.org", "verified"]
    assert "SmartEditor" not in str(payload), "만든 사람용 설명은 표에 싣지 않는다"


def test_other_nested_results_keep_the_old_fallback() -> None:
    """역방향 — 다른 도구의 중첩 결과는 예전처럼 통째로(JSON) 보인다. 이 고침은 site_list 한 곳만이다."""
    kind, _, payload, _ = shape("some_new_tool", {}, RESULT)
    assert kind == "note" and payload["language"] == "json"


def test_an_empty_list_does_not_crash() -> None:
    kind, _, _, _ = shape("site_list", {}, {"sites": []})
    assert kind == "note"
