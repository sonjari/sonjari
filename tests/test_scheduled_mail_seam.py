"""예약 결과 메일이 **본문을 달고** 나가는지 본다.

왜 따로 만드나. `tests/test_schedule_repeat_and_mail.py` 는 `send_mail` 을 가짜로
갈아끼운다 — 그래서 스케줄러가 "본문이 비면 안 보낸다"는 것까지만 지킬 뿐,
**runtime → google_workspace 이음매**는 한 번도 안 지난다. 그 이음매에서 칸 이름이
`body` ↔ `body_text` 로 갈려 있었고, 검사 1819개가 전부 통과하는 동안 8/22·8/23
아침 자기점검 메일 두 통이 **제목만 있는 빈 메일**로 나갔다. prepare·commit·Gmail
응답이 전부 성공이라 아무 데도 안 찍혔다.

여기서는 진짜 `gmail_prepare_send` 를 부른다. 저장된 payload 에 본문이 들어 있는지만
보면 된다 — 그 값이 그대로 메일이 된다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import GoogleWorkspace
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.runtime import JarvisRuntime


def _workspace(tmp_path: Path) -> tuple[GoogleWorkspace, ExternalActionStore]:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        google_write_enabled=True,
        external_action_ttl_sec=300,
        google_client_secret_path=tmp_path / "google" / "client_secret.json",
        google_token_path=tmp_path / "google" / "token.dpapi",
    )
    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    workspace = GoogleWorkspace(
        config, EventBus(), local_computer=LocalComputerTools(config), actions=actions
    )
    return workspace, actions


def test_the_scheduled_mail_arrives_with_its_body(tmp_path: Path) -> None:
    """`_send_scheduled_mail` 이 부르는 그대로 불러 본문이 살아남는지 본다."""
    workspace, actions = _workspace(tmp_path)
    answer = "오늘 아침 자기점검: 다섯 기관 모두 정상."

    # runtime._send_scheduled_mail 이 만드는 인자와 같은 모양이어야 한다.
    prepared = workspace.gmail_prepare_send(
        {"to": ["someone@example.com"], "subject": "[자비스 예약] 아침 자기점검"[:200], "body_text": answer[:100_000]}
    )

    stored = actions.get_prepared_action(prepared["action_id"])
    assert stored is not None
    assert stored["payload"]["body_text"] == answer
    assert stored["preview"]["body_preview"].startswith("오늘 아침 자기점검")
    assert stored["preview"]["body_preview"] != "(본문 없음)"


def test_runtime_passes_the_body_under_the_name_prepare_reads() -> None:
    """★ 진짜 불변식: 보내는 쪽이 쓰는 칸 이름과 읽는 쪽이 보는 칸 이름이 같은가.

    위 검사는 인자를 이 파일이 직접 쓰므로 runtime 이 다시 `body` 로 돌아가도 안 잡는다.
    그래서 **runtime 의 소스**에서 그 칸 이름을 확인한다.
    """
    source = inspect.getsource(JarvisRuntime._send_scheduled_mail)
    assert "body_text" in source, "예약 메일이 본문 없이 나간다 — gmail_prepare_send 는 body_text 만 읽는다"
    body_keys = {"\"body\":", "'body':"}
    assert not any(key in source for key in body_keys), "`body` 칸은 조용히 버려진다"
