"""이름 뒤에 괄호 주소를 붙여 「거기에 물어봐」라고 시킨 말도 시킨 말이다 (2026-10-20 · 잡 fc3f8fd4).

AI 큐레이션 기준점을 재려고 「퍼플렉시티(https://www.perplexity.ai)에서 … 물어보고」를 맡겼는데, 입력칸에 쓰는 손이 세 번 다 막혔다.
운영 · 촬영 요청 2,430개에 대 보니 판정이 바뀌는 옛 요청은 0개.
"""

from __future__ import annotations

import pytest

from alture_jarvis.ai_chat_sites import asked_to_use_one


@pytest.mark.parametrize("text", [
    "퍼플렉시티(https://www.perplexity.ai)에서 아래 질문 5개를 하나씩 물어보고 정리해 줘",
    "챗GPT(chatgpt.com)에 이 질문 넣어 줘",
    "퍼플렉시티에서 이 질문 물어봐 줘",
    # 같은 날 제미나이 잡(aa6d18a6): 자리 낱말(화면) + 조사에서 「입력칸」까지 16자가 넘음
    "제미나이(https://gemini.google.com/app) 화면에서 임시 채팅이 켜져 있는지만 확인하고(꺼져 있으면 켜고), 입력칸에 아래 질문 하나를 글자 그대로 넣어 보내 줘",
])
def test_asked_to_use_it_even_with_a_url_in_brackets(text: str) -> None:
    assert asked_to_use_one(text)


@pytest.mark.parametrize("text", [
    "GPT(OpenAI)의 홍보 전략을 조사해서 정리해 줘",
    "퍼플렉시티(Perplexity AI)가 어떤 회사인지 조사해 줘",
    "제미나이 요금제 비교해서 엑셀로 정리해 줘",
    # 멀리 떨어진 흔한 낱말(질문)은 시킨 말이 아니다 — 운영 요청에 대 보다 나온 오탐
    "GPT에서 만든 글을 워드 파일에 넣어 줘",  # GPT 는 출처다
    "챗GPT에서 받은 답을 엑셀에 넣어 줘",
    "클로드에서 사용량 한도로 이어가게 하는거를 되게 한다니 이게 대박이네 나는 문서를 만들어달라는게아니라 이 질문에 답변을 해달라는거였어",
])
def test_asking_about_a_service_is_not_asking_it(text: str) -> None:
    assert not asked_to_use_one(text)


def test_the_site_address_written_out_with_a_send_word_is_asking_it() -> None:
    """이름 · 동사 거리로 재는 꼴은 문장을 조금만 바꿔도 깨졌다(같은 날 세 번) — 주소를 적어 준 것은 분명한 뜻이다(잡 05232da3)."""
    assert asked_to_use_one(
        "제미나이(https://gemini.google.com/app) 화면에서, 화면 위쪽에 「임시 채팅」이라는 표시가 보이지 않으면 오른쪽 위의 임시 채팅 버튼을 "
        "한 번 눌러 켜고, 새 대화 입력칸에 아래 질문 하나를 글자 그대로 넣어 보낸 뒤 답을 끝까지 읽어서 알려 줘."
    )
    assert asked_to_use_one("Open https://chatgpt.com and ask: what is MCP?")


def test_the_site_address_alone_is_not_asking_it() -> None:
    assert not asked_to_use_one("https://gemini.google.com 의 요금제 페이지를 읽고 정리해 줘")
