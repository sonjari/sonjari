"""그 대화에서 이미 한 답을 **통째로 다시 낸** 직답은 내보내지 않고 보러 간다 (2026-10-06 대표 실사용).

「깃허브에서 README 보고 말해 줘」를 잘못 알아들은 뒤, 「레포 들어가면 뜰 건데」·「전체 레포를 보라니까」에 0걸음으로
같은 글을 세 번 냈다. 운영 기록을 그 턴 직전으로 되감아 다시 넣자(`bench/repeat_answer/replay.py`) 이번에는 **네 턴 앞의
다른 답**을 4.7초 만에 글자 그대로 냈다 — 「방금 실제 레포 페이지를 열어 확인했다」까지. 새로 생각한 것이 아니라
기록 속 자기 글을 베낀 것이다.

낱말(「아니」·「다시」)로 가르지 않는다. **이번 초안이 이 대화의 지난 답과 거의 같다**는 사실에 건다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import COPIED_ANSWER_SIMILARITY, copied_from

FOUND = (
    "찾았다. 요청하신 레포다.\n\n`sonjari/sonjari` — GitHub 로그인 계정의 조직 `sonjari` 에 있는 레포. 방금 실제 레포 페이지를 "
    "열어 확인했다.\n\n- 주소: https://github.com/sonjari/sonjari\n- 설명: a local AI work assistant for Windows.\n"
    "- 주요 폴더: src, bench, packaging, recipes, scripts, skills, tests, ui\n\n더 자세히 보고 싶은 파일이 있으면 여는 대로 정리해 주마."
)
RENAME = (
    "깃허브에서 커밋 이력만 확인했다.\n\n- 파일: `src/alture_jarvis/brand.py`\n- 커밋 개수: 1건 (Initial import)\n"
    "- 이름을 바꾼 커밋: 없음. 이 파일은 처음부터 `brand.py` 로 한 번에 올라왔다.\n\n결론: 이름 바꾼 이력은 없다."
)


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _Model:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {"content": self.content, "tool_calls": []}

    chat_message_stream = chat_message


def _talked(runtime, session: str) -> None:
    for role, text in (
        ("user", "내가 레포에 올렸다 한번 봐줘"), ("assistant", FOUND),
        ("user", "깃허브에서 리네임만 보고 말해줘"), ("assistant", RENAME),
    ):
        runtime.memory.add_message(session, role, text)


def test_a_draft_that_copies_an_earlier_answer_is_noticed() -> None:
    assert copied_from(FOUND, [RENAME, FOUND]) == 2
    assert copied_from(FOUND + "\n", [RENAME, FOUND]) == 2, "끝의 빈 줄 하나로 비켜 가면 안 된다"


def test_a_new_answer_is_not_a_copy() -> None:
    fresh = "README 를 보면 손자리는 윈도우용 로컬 AI 작업 도우미다. 조사해서 파일로 만드는 일을 내 PC 에서 하고, 읽은 근거를 남긴다. " * 2
    assert copied_from(fresh, [RENAME, FOUND]) == 0


def test_short_answers_may_repeat() -> None:
    """「네, 알겠습니다」 같은 한 줄은 같아도 이상하지 않다."""
    assert copied_from("네, 알겠습니다.", ["네, 알겠습니다."]) == 0


def test_the_router_does_not_deliver_a_copy(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _talked(runtime, "s1")
    runtime.ollama = _Model(FOUND)   # 직전 답이 아니라 **두 답 앞**의 글을 다시 낸다

    route, answer, observation = runtime._general_route("머라노 레포들어가면 뜰건데", "s1", job_id="job-1")

    assert route == "agent" and answer == ""
    assert (observation or {}).get("route_reason") == "copied_earlier_answer"
    assert (observation or {}).get("turns_back") == 2


def test_a_fresh_answer_still_goes_out(tmp_path: Path) -> None:
    """역방향 — 지난 답과 다른 평범한 직답은 그대로 나간다."""
    runtime = _runtime(tmp_path)
    _talked(runtime, "s1")
    runtime.ollama = _Model("아, README 를 말씀하신 거군요. 제가 이름 바꾼 기록으로 잘못 알아들었습니다. 무엇이 궁금하신지 다시 말씀해 주세요.")

    route, answer, _ = runtime._general_route("머라노 레포들어가면 뜰건데", "s1", job_id="job-1")

    assert route == "answer" and answer.startswith("아, README")


def test_another_conversation_is_not_compared(tmp_path: Path) -> None:
    """다른 대화방에서 같은 글이 나온 것은 베낀 것이 아니다."""
    runtime = _runtime(tmp_path)
    _talked(runtime, "other")
    runtime.ollama = _Model(FOUND)

    route, _, _ = runtime._general_route("레포 한번 설명해줘", "s1", job_id="job-1")

    assert route == "answer"


def test_a_copied_frame_with_swapped_names_is_still_a_copy() -> None:
    """고친 뒤 재생에서 나온 모양 — 지난 답의 틀에 이름만 바꿔 끼웠다(「머라노」를 저장소 이름으로 읽음). 0.76 이었다."""
    swapped = FOUND.replace("sonjari/sonjari", "merrano/merrano").replace("`sonjari`", "`merrano`")
    assert swapped != FOUND
    assert copied_from(swapped, [RENAME, FOUND]) == 2


def test_the_threshold_is_what_the_records_showed() -> None:
    """운영 기록 69판: 0.60 위 여덟은 전부 베낀 답, 아래 61. 바꾸려면 그 표본을 다시 세고 바꾼다."""
    assert COPIED_ANSWER_SIMILARITY == 0.60
