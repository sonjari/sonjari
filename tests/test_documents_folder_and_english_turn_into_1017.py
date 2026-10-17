"""영어 첫 일 측정(2026-10-17)에서 나온 둘.

1. 결과물 폴더: `문서\Sonjari` 가 이미 있으면 옛 `문서\JARVIS` 가 다시 생겨도 새 폴더를 쓴다. 옛 폴더는 새 폴더가 없을 때만 잇는다.
   다른 자리(브라우저 프로필 등)는 옛 자리를 그대로 이어 쓴다 — 거기서 바꾸면 로그인이 끊긴다.
2. 영어 「Turn what you just found into an Excel file」 — 「turn ○○ into」 사이에 낱말이 끼어도 파일 요구로 읽는다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import brand, plan


def test_documents_prefer_the_new_folder_when_both_exist(tmp_path: Path) -> None:
    assert brand.documents_product_dir(tmp_path) == tmp_path / "Sonjari"
    (tmp_path / "JARVIS").mkdir()
    assert brand.documents_product_dir(tmp_path) == tmp_path / "JARVIS"  # 옛 사용자: 새 폴더가 없으면 옛 폴더를 잇는다
    (tmp_path / "Sonjari").mkdir()
    assert brand.documents_product_dir(tmp_path) == tmp_path / "Sonjari"  # 둘 다 있으면 새 폴더


def test_other_places_still_keep_the_legacy_folder(tmp_path: Path) -> None:
    (tmp_path / "JARVIS").mkdir()
    (tmp_path / "Sonjari").mkdir()
    assert brand.product_dir(tmp_path) == tmp_path / "JARVIS"


def test_turn_something_into_an_excel_file_is_a_file_request() -> None:
    kinds = [req.kind for req in plan.extract("Turn what you just found into an Excel file")]
    assert "artifact" in kinds
    assert "artifact" not in [req.kind for req in plan.extract("Turn on dark mode and tell me what changed")]


class _Ollama:
    def __init__(self, reply: str) -> None:
        self.reply, self.calls = reply, 0

    def chat(self, prompt, **kwargs):
        self.calls += 1
        return self.reply


class _Runtime:
    def __init__(self, reply: str) -> None:
        self.ollama = _Ollama(reply)


KOREAN = "이전 대화에서 이미 확인한 내용입니다. 에펠탑의 높이는 330m 이고 1889년에 완공되었습니다. 출처는 위키백과입니다."


def test_a_korean_answer_to_an_english_question_is_rewritten_in_english() -> None:
    """3. 바로 답하는 길이 영어 질문에 한국어로 답했다(운영 e92e3204 · 측정 764adb7e). 에이전트 길과 같은 관문."""
    from alture_jarvis.runtime import JarvisRuntime

    rt = _Runtime("The Eiffel Tower is 330 m tall and was completed in 1889. Source: Wikipedia.")
    out = JarvisRuntime._english_if_asked(rt, "Open the Wikipedia article on the Eiffel Tower and tell me its height", KOREAN)
    assert out.startswith("The Eiffel Tower")


def test_no_rewrite_for_korean_questions_or_english_answers() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    rt = _Runtime("ignored")
    assert JarvisRuntime._english_if_asked(rt, "에펠탑 높이 알려 줘", KOREAN) == ""
    assert JarvisRuntime._english_if_asked(rt, "How tall is the Eiffel Tower?", "It is 330 m tall.") == ""
    assert rt.ollama.calls == 0


def test_a_rewrite_that_is_not_english_keeps_the_original() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    rt = _Runtime(KOREAN)
    assert JarvisRuntime._english_if_asked(rt, "How tall is the Eiffel Tower?", KOREAN) == ""
