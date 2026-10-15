"""카메라 지름길이 남의 질문을 가로채지 않는다.

2026-08-09 사고. 사용자님이 블로그 초안을 통째로 붙여 넣고 "여기에 UX/UI 사진이랑
캡션까지 넣어서 블로그에 임시저장까지 해줘" 라고 했는데, 자비스는 이렇게 답했다:

    "지금 카메라 영상이 없어서 확인할 수 없습니다. 사무실 태블릿이 꺼져 있거나…"

질문과 아무 상관 없는 답이다. 원인은 둘이 겹쳐 있었다.

**1. 어림짐작이 너무 헐거웠다.** `_requires_fresh_camera` 는 '지금·현재' 와
'이거·보이·상태' 두 목록을 AND 로 묶는다. 둘 다 아주 흔한 낱말이라 글이 길수록
우연히 둘 다 들어 있을 확률이 1 에 수렴한다. 실측한 그 요청에는 '지금'·'현재' 와
'이거'·'보이' 가 전부 들어 있었다 — 카메라 이야기는 한 글자도 없는데.

**2. 순서가 거꾸로였다.** 카메라 검사가 블로그·웹조사보다 **먼저** 있었다. 그
요청은 블로그 낱말을 넷이나 맞췄지만("블로그"·"포스팅"·"임시저장"·"초안") 그
갈래는 도달조차 못 했다. 애매한 쪽이 분명한 쪽을 이기고 있었다.

여기서 지키는 것 셋:

  1. 플랫폼과 행위를 둘 다 댄 요청은 카메라가 못 가로챈다
  2. 짧은 카메라 한마디는 여전히 지름길로 간다 (그러라고 있는 것이다)
  3. "내 얼굴 봐줘" 같은 직접 지시는 글이 길어도 통과한다
"""

from __future__ import annotations

from alture_jarvis.runtime import CAMERA_SHORTCUT_MAX_CHARS, JarvisRuntime

# 실제로 사고를 낸 요청을 줄인 것. 카메라 이야기는 한 글자도 없다.
_BLOG_REQUEST = (
    "[블로그 포스팅 초안] (본문 1: 왜 지금 데이터인가?) 눈에 보이는 리포트는 "
    "학부모에게 신뢰를 줍니다. 현재 이 성적 추이라면 A 대학 전형에 유리하며. "
    "로보메타핏에서 필요한 uxui 사진이나 캡션 넣어서 이거 이제 블로그에 해서 "
    "임시저장까지 해줘"
)

# 카메라 낱말은 없지만 '지금·현재' × '이거·보이·상태' 가 전부 들어 있는 잡담.
_LONG_CHITCHAT = (
    "요즘 학원 운영이 어떤지 정리해보면 지금 학생 수는 늘고 있고 현재 진행 중인 "
    "반은 여섯 개인데 이거 관련해서 리포트가 보이는 부분들을 좀 더 다듬어야 할 것 "
    "같고 상태를 계속 점검해야 할 것 같은데 어떻게 생각해?"
)


def test_a_pasted_blog_request_is_not_taken_for_a_camera_question() -> None:
    assert JarvisRuntime._requires_fresh_camera(_BLOG_REQUEST) is False
    # 그리고 원래 갔어야 할 곳은 여전히 자기를 알아본다.
    assert JarvisRuntime._requires_naver_blog(_BLOG_REQUEST) is True


def test_long_chitchat_does_not_reach_for_the_camera() -> None:
    """블로그 낱말이 없어도 마찬가지다 — 순서만 고쳐서는 이게 안 잡힌다."""
    assert JarvisRuntime._requires_fresh_camera(_LONG_CHITCHAT) is False


def test_short_camera_questions_still_take_the_shortcut() -> None:
    for prompt in ("지금 이거 보여?", "지금 내 표정 어때?", "아까 말한 그거 지금도 그대로 있나 좀 봐줘"):
        assert len(" ".join(prompt.split())) <= CAMERA_SHORTCUT_MAX_CHARS
        assert JarvisRuntime._requires_fresh_camera(prompt) is True, prompt


def test_a_direct_look_at_me_passes_however_long_the_sentence_is() -> None:
    """'내 얼굴'·'카메라로 봐' 는 긴 글에 우연히 섞일 낱말이 아니다."""
    prompt = (
        "오늘 일이 많았는데 계속 앉아만 있었더니 목도 아프고 눈도 침침한데 "
        "혹시 지금 내 얼굴 좀 봐줄 수 있어? 안색이 어떤지 궁금해서 그래"
    )
    assert len(" ".join(prompt.split())) > CAMERA_SHORTCUT_MAX_CHARS
    assert JarvisRuntime._requires_fresh_camera(prompt) is True


def test_saying_no_camera_still_wins() -> None:
    assert JarvisRuntime._requires_fresh_camera("지금 이거 보여?", camera_denied=True) is False
