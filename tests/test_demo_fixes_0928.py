"""09-28 새벽 데모에서 잡은 셋.

1. 클로드 세션이 본체 재시작 중에 붙으면 온텔릭 도구가 **0개**로 기록돼, 그 세션은 끝까지 온텔릭을 못 썼다(연결됨 · tool_count 0).
2. 「방금 만든 큐브 되돌려 줘」에 도구 0번·1초로 「삭제했습니다」. 큐브는 그대로였다.
3. 이어서 「에디터에서 그 큐브 지워 줘」에 도구 0번으로 「이미 삭제된 상태입니다」 — 앞 판의 거짓말을 믿었다.
   → 에디터 안을 바꾸거나 보라는 요청은 에디터 도구 기록을 요구로 세운다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.agent import _DONE_CLAIM
from alture_jarvis.mcp_server import JarvisMcpBridge
from alture_jarvis.plan import extract

REPO = Path(__file__).resolve().parents[1]


class _DownClient:
    async def get(self, url: str, **kwargs: Any) -> Any:
        raise ConnectionError("backend restarting")


def test_the_delegation_doors_are_listed_even_when_the_backend_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("alture_jarvis.mcp_server.asyncio.sleep", no_wait)
    bridge = JarvisMcpBridge("http://127.0.0.1:1", "t", client=_DownClient())
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert names == ["sonjari_task", "sonjari_task_status", "sonjari_guide"], "0개로 굳으면 그 세션은 끝까지 온텔릭을 못 쓴다"
    assert bridge._allowed is None, "못 본 것을 「금지」로 굳히지 않는다 — 다음 호출 때 다시 본다"


@pytest.mark.parametrize(("said", "claims"), [
    ("OntelicDemoCube를 삭제했습니다.", True),
    ("큐브를 만들었습니다", True),
    ("설정을 바꿨어요", True),
    ("되돌렸습니다", True),
    ("안녕하세요, 잘 지내셨나요?", False),
    ("원하시면 삭제해 드릴게요", False),
])
def test_done_claims_are_recognised(said: str, claims: bool) -> None:
    assert bool(_DONE_CLAIM.search(said)) is claims


def test_a_done_claim_with_no_tool_call_is_pushed_back_once_in_both_branches() -> None:
    source = (REPO / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert source.count("done_claim_pushed = False") == 2, "새 판·이어 가는 판 둘 다 — 한쪽만 두면 UnboundLocalError(09-21)"
    gate = source.index("if not done_claim_pushed and not steps and _DONE_CLAIM.search(answer)")
    assert gate < source.index("and PROMISED_ACTION.search(answer)", gate)


@pytest.mark.parametrize(("prompt", "targets"), [
    ("열려 있는 유니티 에디터에서 아까 만든 OntelicDemoCube 지워 줘. 저장은 하지 마.", ["unity_editor_change"]),
    ("유니티 에디터에서 방금 바꾼 거 되돌려 줘", ["unity_editor_undo"]),
    ("열려 있는 유니티 에디터(OntelicPlayground)에서 지금 씬 계층을 보고, (0, 3, 0) 위치에 큐브를 하나 만들어 줘. 씬 저장은 하지 마.",
     ["unity_editor_change", "unity_editor_look"]),
    ("에디터 콘솔에 에러 있나 확인해줘", ["unity_editor_look"]),
    ("유니티 프로젝트 텍스처 점검해줘", ["unity_run_recipe"]),
    ("유니티 설치 링크 한번 주라", []),
])
def test_editor_requests_require_editor_tools(prompt: str, targets: list[str]) -> None:
    assert [str(item.target) for item in extract(prompt) if item.kind == "action"] == targets


def test_editor_requirements_are_dropped_when_the_pack_is_off() -> None:
    source = (REPO / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert "str(item.target) in (UNITY_TOOL_NAMES | EDITOR_TOOL_NAMES)" in source, "못 부르는 도구를 요구로 세우면 영원히 못 채운다"


def test_the_unity_stage_takes_the_browser_stage_layout() -> None:
    app = (REPO / "ui" / "src" / "WorkspaceApp.tsx").read_text(encoding="utf-8")
    assert "browser_|site_|unity_editor_" in app and '(workspaceMode === "cowork" || unityInJob)' in app
    css = (REPO / "ui" / "src" / "workspace.css").read_text(encoding="utf-8")
    assert ".stage-browser .computer-body .unity-stage-frame" in css, "무대 모드에서 유니티 화면이 칸을 채운다"
    assert ".unity-stage-frame > img { width: 100%; height: 100%; object-fit: contain;" in css, "비율은 그대로"
