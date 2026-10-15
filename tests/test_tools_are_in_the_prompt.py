"""도구를 만들어 놓기만 하면 안 쓴다 — 절차에 이름이 없으면 없는 도구다.

## 하루에 세 번 같은 모양으로 났다 (2026-08-12)

    google_drive_read     만들었는데 안 불렀다. 브라우저로 docs.google.com 을 열고
                          로그인 화면만 보고 나왔다.
    browser_site_search   만들었는데 안 불렀다. 잡코리아에 들어가 놓고 본문만 읽고 나왔다.
    browser_load_more     만들었는데 안 불렀다(실측 8판, 0회).

원인은 모델이 아니라 프롬프트다. 절차가 **"기본 순서: search → open_result → extract"**
하나로 못 박혀 있어서 새 도구가 낄 자리가 없었다. 도구 스키마에 설명을 아무리 잘 써도,
절차에 이름이 없으면 그 자리에서 떠오르지 않는다.

인수인계서는 "도구를 만들면 그날 프롬프트 순서에도 넣어라"고 적었다. 그것은 사람의
규율이라 지켜지지 않는다 — 그래서 시험으로 만든다.

## 무엇을 강제하나 (전부가 아니다)

도구 93개를 전부 프롬프트에 적으라고 하면 허용목록만 커지고 시험은 죽는다.
강제하는 것은 **증거를 만드는 도구**뿐이다 — `agent.py` 가 이미 `_LISTING_TOOLS` ·
`_CONTENT_TOOLS` 로 분류해 둔 것들. 그 분류는 답의 출처를 세는 데 쓰이므로,
거기 든 도구는 정의상 "자료를 찾아 읽는 절차"의 일부다. 절차에 이름이 없으면
**세어지기는 하는데 불리지는 않는** 도구가 된다. `google_drive_read` 가 정확히 그랬다.

낱개 조작 도구(`browser_press`·`clipboard_read` 같은)는 여기서 안 본다. 그것들은
절차가 아니라 상황에 따라 쓰는 것이고, 스키마 설명으로 충분하다.
"""

from __future__ import annotations

import re
from pathlib import Path

from alture_jarvis.agent import (
    _CONTENT_TOOLS,
    _INHOUSE_TOOL_HINTS,
    _LISTING_TOOLS,
    AGENT_SYSTEM_PROMPT,
    inhouse_prompt_section,
)
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

# 절차에 이름이 없어도 되는 증거 도구. **비어 있는 게 정상이다** —
# 채울 일이 생기면 "왜 절차에 안 넣었는가"를 여기 적어야 한다. 이유 없이 이름만
# 넣는 것은 시험을 끄는 것과 같다.
UNMENTIONED_ON_PURPOSE: dict[str, str] = {
    # 게임 팩(2026-09-27). 모든 판의 절차에 넣으면 유니티와 무관한 판까지 글이 길어진다. 대신 유니티 낱말이 있을 때만
    # 코드 프로필(`code_runtime.select_code_tool_profile` 의 unity 갈래) 안내와 `game-unity` 스킬이 이름을 댄다.
    "unity_project_info": "유니티 판에만 코드 프로필 안내·game-unity 스킬이 이름을 댄다 — 전역 절차에 넣지 않는다",
    "unity_run_recipe": "유니티 판에만 코드 프로필 안내·game-unity 스킬이 이름을 댄다 — 전역 절차에 넣지 않는다",
    "unity_editor_status": "유니티 판에만 코드 프로필 안내·game-unity 스킬이 이름을 댄다 — 전역 절차에 넣지 않는다",
    "unity_editor_look": "유니티 판에만 코드 프로필 안내·game-unity 스킬이 이름을 댄다 — 전역 절차에 넣지 않는다",
}


def _procedure() -> str:
    """모델이 실제로 받는 절차 전체.

    ★ 2026-08-13: 절차가 더 이상 문자열 **하나**가 아니다. 우리 데이터 도구는
    NAS 가 무엇을 열어 주느냐에 따라 달라지므로, 그 문단은 붙어 있는 도구 목록에서
    만들어진다(`inhouse_prompt_section`). 여기서 정적 문자열만 보면 "절차에 없다"고
    잘못 잡는다 — 실제로는 있다.

    반대 방향도 지킨다: 힌트표에 없는 도구는 문단에 안 실리므로, 이 시험은 여전히
    "만들어 놓고 순서에 안 넣은 것"을 잡는다.
    """
    return AGENT_SYSTEM_PROMPT + inhouse_prompt_section(set(_INHOUSE_TOOL_HINTS))


def _registered_names(tmp_path: Path) -> set[str]:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
        camera_control_enabled=False,
        google_oauth_client_id="test.apps.googleusercontent.com",
        google_write_enabled=True,
    )
    return set(create_app(config, start_services=False).state.jarvis.agent_tools.names)


def test_every_evidence_tool_is_named_in_the_procedure() -> None:
    """증거를 만드는 도구는 절차에 이름이 있어야 한다."""
    procedure = _procedure()
    missing = sorted(
        name
        for name in (_LISTING_TOOLS | _CONTENT_TOOLS)
        if name not in procedure and name not in UNMENTIONED_ON_PURPOSE
    )

    assert not missing, (
        "절차에 이름이 없는 증거 도구가 있다 — 만들어 놓고 안 쓰게 된다:\n  "
        + "\n  ".join(missing)
        + "\n\nAGENT_SYSTEM_PROMPT 의 해당 절차(또는 _INHOUSE_TOOL_HINTS)에 넣거나, "
        "왜 안 넣는지를 UNMENTIONED_ON_PURPOSE 에 적어라."
    )


def test_the_reasons_are_written_down() -> None:
    """면제에는 이유가 붙어야 한다. 이름만 넣는 것은 시험을 끄는 것이다."""
    for name, why in UNMENTIONED_ON_PURPOSE.items():
        assert len(why.strip()) >= 15, f"{name}: 왜 절차에 안 넣었는지가 안 적혀 있다"


# 프롬프트에 적힌 도구 이름을 찾는다.
#
# 뒤에 콜론이 붙은 것은 도구가 아니라 **오류 코드**다(`site_blocked:<호스트>`).
# 프롬프트는 실패 문구도 그대로 인용하기 때문에 이 구별이 필요하다.
# `naver_blog_*` 처럼 별표로 묶어 부르는 곳도 도구 하나를 가리키는 게 아니라 빠진다.
_TOOL_TOKEN = re.compile(
    r"\b((?:browser|google|local|windows|naver_blog|site|schedule|ui|camera|person|clipboard)"
    r"_[a-z0-9_]+)\b(?![:*])"
)


def test_the_procedure_does_not_name_tools_that_do_not_exist(tmp_path: Path) -> None:
    """없는 도구를 시키면 모델은 그것을 부르려다 걸음을 버린다.

    이름을 바꾸거나 도구를 지울 때 프롬프트를 같이 안 고치면 이렇게 된다.
    도구 쪽은 코드가 잡아 주지만 프롬프트는 아무도 안 본다.
    """
    registered = _registered_names(tmp_path)
    named = {match.group(1).rstrip("_") for match in _TOOL_TOKEN.finditer(AGENT_SYSTEM_PROMPT)}
    ghosts = sorted(name for name in named if name not in registered)

    assert not ghosts, (
        "프롬프트가 없는 도구를 시킨다:\n  "
        + "\n  ".join(ghosts)
        + "\n\n이름이 바뀌었으면 프롬프트를 고치고, 설명하려고 쓴 말이면 도구 이름처럼 쓰지 마라."
    )
