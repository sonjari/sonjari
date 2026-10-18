"""시키지 않은 파일을 만들게 하지 않는다 (2026-10-19 · 판 029fae29 · arXiv 판 302bf59e).

「…FAQ 문서(docs/faq.md)를 찾아 읽고 … 원문에 적힌 그대로 옮기고 … 파일은 만들지 않아도 되고 답으로만 알려 줘」에
「실제 산출물 파일 만들기」가 섰고, 손자리가 시키지 않은 .md 를 만들었다. arXiv 판(「PDF 파일을 내려받아서 … 첫 문장을
그대로 옮겨 줘」)도 같은 모양으로 정리 .md 를 하나 더 만들었다.

원인 둘(`plan.wants_an_artifact`):
1. 글 전체에서 대상 낱말(문서 · 파일) 하나와 동사(옮기고 · 옮겨) 하나를 아무렇게나 짝지었다. 「옮기다 · 담다 · 달다 · 넣다」는
   **받는 곳**(에 · 로)을 가지는 동사인데, 두 판의 문서 · 파일은 받는 곳이 아니라 **읽을 재료**였다.
2. 「만들지 않아도 · 만들 필요 없 · 안 만들어도」는 금지가 아니라 안 시킨다는 말인데 어디에도 안 걸렸다.

여기 적은 문장은 운영 요청의 모양만 본떴다 — 실제 개인 값은 없다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import plan


def _artifact_kinds(prompt: str) -> list[str]:
    return [req.kind for req in plan.extract(prompt) if req.kind == "artifact"]


# ── (a) 029fae29 모양 — 읽을 문서 · 그대로 옮겨 적기 · 파일은 안 만들어도 된다 ─────────────────────

FAQ_ANSWER_ONLY = (
    "GitHub 의 example-org/example-tool 저장소에서 FAQ 문서(docs/faq.md)를 찾아 읽고, 설정 값을 어떻게 바꾸는지 알려 줘. "
    "구체적으로: (1) 환경 변수를 쓰는 방법(예시 명령 그대로), (2) 기본값이 몇인지. FAQ 원문에 적힌 그대로 옮기고, "
    "읽은 페이지 주소(URL)도 같이 돌려줘. 파일은 만들지 않아도 되고 답으로만 알려 줘."
)


def test_reading_a_faq_and_quoting_it_is_not_a_file_request() -> None:
    assert plan.wants_an_artifact(FAQ_ANSWER_ONLY) is False
    assert _artifact_kinds(FAQ_ANSWER_ONLY) == []


def test_quoting_alone_without_the_no_file_sentence_is_still_not_a_file_request() -> None:
    """거두는 말이 없어도 — 「그대로 옮기고」는 답에 옮겨 적으라는 말이고 문서는 읽을 재료다."""
    ask = "example-tool 저장소의 FAQ 문서(docs/faq.md)를 찾아 읽고, 설정 바꾸는 방법을 원문에 적힌 그대로 옮겨 줘."
    assert plan.wants_an_artifact(ask) is False


@pytest.mark.parametrize(
    "decline",
    ["파일은 만들지 않아도 돼", "파일로 만들 필요는 없어", "파일 안 만들어도 됨", "엑셀 파일로 만들 필요 없이 답으로 줘"],
)
def test_declining_a_file_takes_the_file_request_away(decline: str) -> None:
    ask = f"예시 쇼핑몰에서 상품 세 개를 찾아 이름 · 가격 · 주소를 표로 정리해서 줘. {decline}."
    assert plan.wants_an_artifact(ask) is False


def test_declining_is_not_a_write_ban() -> None:
    """「않아도 된다」는 안 시킨다는 말이지 쓰기 **금지**가 아니다 — 판을 읽기 전용으로 묶으면 안 된다."""
    assert plan.forbids_writes(FAQ_ANSWER_ONLY) is False


# ── (b) 진짜로 파일을 시킨 문장은 그대로 산출물이다(거짓 「안 시킴」 금지) ──────────────────────────

@pytest.mark.parametrize(
    "ask, extension",
    [
        ("FAQ 문서를 찾아 읽고 요약해서 엑셀로 저장해 줘", ".xlsx"),
        ("예시 저장소의 README 문서를 읽고 핵심을 정리해서 워드 파일로 만들어 줘", ".docx"),
        ("구글 드라이브에서 이력서 읽어서 한글 파일에 본문 옮기고 각주로 수정 제안 달아줘", ".hwpx"),
        ("조사한 내용을 엑셀에 넣어줘", ".xlsx"),
        # 거둔 것은 엑셀이고 시킨 것은 워드다 — 거둔 형식이 시킨 형식을 가리면 안 된다.
        ("엑셀은 안 만들어도 되고 결과를 워드 파일에 옮겨 줘", ".docx"),
    ],
)
def test_asked_files_are_still_artifacts(ask: str, extension: str) -> None:
    assert plan.wants_an_artifact(ask) is True
    assert extension in plan.artifact_extensions(ask)


def test_a_comment_added_to_a_named_code_file_is_still_work_on_that_file() -> None:
    """운영 대조에서 걸렸던 꼴 — 이름 붙은 파일에 「넣어라 · 달아」를 시킨 저장소 일은 그 파일이 받는 곳이다."""
    ask = (
        "src/pkg/catalog.py 의 SEED 에 항목 둘을 넣어라. 왜 넣는지 그 파일의 다른 항목들처럼 짧은 주석을 달아라. "
        "다른 파일은 고치지 말고."
    )
    assert plan.wants_an_artifact(ask) is True


def test_a_tidy_table_is_not_a_file_once_the_file_is_declined() -> None:
    """「표로 정리해서 줘」의 표는 거둔 판에서 답에 그리는 표다(`_TIDY_VERB` 규율과 같다)."""
    assert plan.wants_an_artifact("FAQ 문서를 읽고 표로 정리해서 줘. 파일은 만들 필요 없어") is False


# ── (c) 영어 — 같은 두 쌍 ───────────────────────────────────────────────────────────────────────────

def test_english_read_and_answer_with_no_file_is_not_a_file_request() -> None:
    ask = (
        "Find and read the FAQ document (docs/faq.md) in the example-org/example-tool repo on GitHub and tell me how to "
        "change the setting. Copy the exact wording from the FAQ and give me the page URL. No need to create a file."
    )
    assert plan.wants_an_artifact(ask) is False
    assert _artifact_kinds(ask) == []


def test_english_summary_into_a_file_is_still_a_file_request() -> None:
    ask = "Read the FAQ document and summarize it into an Excel file."
    assert plan.wants_an_artifact(ask) is True
    assert ".xlsx" in plan.artifact_extensions(ask)


def test_english_declined_file_in_chat_is_not_a_file_request() -> None:
    assert plan.wants_an_artifact("Summarize the page in chat, no need to create a file.") is False
    assert plan.wants_an_artifact("List the top 3 results as a table, you don't need to save a document.") is False


def test_english_copy_into_a_document_is_still_a_file_request() -> None:
    ask = "Open the release notes page and copy the first paragraph into a Word document."
    assert plan.wants_an_artifact(ask) is True
    assert ".docx" in plan.artifact_extensions(ask)


# ── (d) arXiv 판 모양 — 내려받은 PDF 는 읽을 재료다 ───────────────────────────────────────────────────

ARXIV_QUOTE = "https://arxiv.org/abs/2401.01234 페이지에서 논문 PDF 파일을 내려받아서, 그 PDF 1쪽에 있는 초록(Abstract)의 첫 문장을 그대로 옮겨 줘."


def test_quoting_from_a_downloaded_pdf_is_not_a_file_request() -> None:
    assert plan.wants_an_artifact(ARXIV_QUOTE) is False
    assert _artifact_kinds(ARXIV_QUOTE) == []


def test_quoting_from_a_downloaded_pdf_into_a_markdown_file_is_a_file_request() -> None:
    ask = ARXIV_QUOTE.replace("그대로 옮겨 줘", "그대로 마크다운 파일로 옮겨 줘")
    assert plan.wants_an_artifact(ask) is True
    assert ".md" in plan.artifact_extensions(ask)


def test_english_arxiv_quote_is_not_a_file_request() -> None:
    ask = "Download the PDF from https://arxiv.org/abs/2401.01234 and copy the first sentence of the abstract exactly."
    assert plan.wants_an_artifact(ask) is False
    into_doc = ask.replace("exactly.", "into a Word document.")
    assert plan.wants_an_artifact(into_doc) is True
