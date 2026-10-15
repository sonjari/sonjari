"""시키지 않은 것을 요구로 뽑지 않는다 — 그리고 시킨 것을 놓치지 않는다.

2026-08-20 쓰기 벤치에서 나온 것들이다. 임시저장까지 **성공한** 판이 스스로
"미이행"이라고 답했다:

    시킨 것 1/4
       X [site] 네이버 블로그에서 하기   ← 쓰라고 했는데 '읽기' 요구
       X [site] 네이버에서 하기         ← 같은 사이트가 두 줄
       O [action] 임시저장 → 완료
       X [action] 발행 → 실행 안 됨     ← "발행은 하지 마" 라고 했는데!

없는 요구를 세면 화면의 「시킨 것」이 부풀고, 자비스는 못 한 것이 있다고 답한다.
반쯤 아는 체하는 체크리스트는 없느니만 못하다(`plan.py` 첫머리).
"""

from __future__ import annotations

from alture_jarvis.plan import extract

KNOWN = {"네이버 블로그": ("blog.naver.com",), "네이버": ("naver.com",), "크몽": ("kmong.com",)}


def actions(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt, known_sites=KNOWN) if r.kind == "action"]


def sites(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt, known_sites=KNOWN) if r.kind == "site"]


class TestNegation:
    def test_forbidden_action_is_not_a_requirement(self) -> None:
        assert actions("네이버 블로그에 글 쓰고 임시저장해줘. 발행은 하지 마.") == ["임시저장"]

    def test_negation_inside_the_same_clause_still_blocks(self) -> None:
        assert actions("발행하지 말고 저장만 해줘") == []

    def test_the_next_sentence_must_not_kill_this_one(self) -> None:
        """창을 문장에서 안 끊으면 앞 문장의 요구가 통째로 사라진다.

        처음 고칠 때 실제로 그랬다 — "임시저장까지 해줘. 발행은 하지 마." 에서
        임시저장이 죽어 **아무것도 안 시킨 판**이 됐다.
        """
        assert "임시저장" in actions("임시저장까지 해줘. 발행은 하지 마.")

    def test_plain_request_still_extracted(self) -> None:
        assert actions("네이버 블로그에 글 쓰고 발행해줘") == ["발행"]

    def test_mail_forbidden_but_draft_asked(self) -> None:
        assert actions("메일은 보내지 말고 초안만 잡아줘") == []

    def test_mail_asked(self) -> None:
        assert "메일 발송" in actions("크몽에서 공고 3개 열어 읽고 메일로 보내줘")


class TestSiteNames:
    def test_longer_name_wins(self) -> None:
        """「네이버 블로그」가 걸리면 「네이버」는 안 건다 — 같은 요구가 두 줄이 된다."""
        assert sites("네이버 블로그에 글 쓰고 임시저장해줘") == ["네이버 블로그에서 하기"]

    def test_plain_naver_still_matches_alone(self) -> None:
        assert sites("네이버에서 오늘 날씨 검색해줘") == ["네이버에서 하기"]

    def test_two_different_sites_both_kept(self) -> None:
        found = sites("크몽과 네이버에서 각각 찾아줘")
        assert len(found) == 2
