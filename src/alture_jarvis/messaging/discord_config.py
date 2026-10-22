"""디스코드 다리의 **비밀 아닌** 설정 — 허용 목록 · 홈 채널 · 승인 정책 (2026-10-17).

봇 토큰은 여기 없다(`credentials.py` — 윈도우 자격 증명 관리자). 저장할 때 토큰 모양이 섞였으면 거절한다 —
사용자가 허용 목록 칸에 토큰을 붙여 넣는 실수가 파일로 새지 않게.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .base import Redactor

log = logging.getLogger("sonjari.messaging")

SETTINGS_FILE = "discord_bridge.json"
STATE_FILE = "discord_bridge_state.json"

#: ★ 승인 정책 — 값 하나로 둔다(2026-10-17 결정).
#:   `app_only`: 승인 · 질문 카드는 PC 앱에서만. 디스코드에는 「PC 앱에서 기다리는 중」만 알린다(기본).
#:   `buttons` : 나중에 디스코드 버튼으로 승인하게 열 자리. **아직 연결하지 않았다** — 고르면 app_only 로 돌고 기록에 한 줄 남긴다.
#:              열 때는 `bridge.ApprovalButtonBinder` 로 버튼마다 제 승인을 묶는다(Hermes #135905 를 피한다).
APPROVAL_POLICIES = ("app_only", "buttons")


@dataclass
class DiscordSettings:
    allowed_user_ids: list[str] = field(default_factory=list)
    home_channel_id: str = ""
    discord_approvals: str = "app_only"
    #: 홈 채널 이름 — 화면에 「#일반 에서는 멘션 없이」를 보여 주려고 둔다(마무리 문이 자동으로 고를 때 같이 적는다, 2026-10-18).
    home_channel_name: str = ""
    #: 디스코드에서 쓰는 기본 모델 별명(`model_aliases.py` 표의 이름). 빈 값 = PC 와 같은 모델 (2026-10-18).
    default_model_alias: str = ""

    @classmethod
    def load(cls, path: Path) -> "DiscordSettings":
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            log.warning("디스코드 설정 파일을 읽지 못해 기본값(아무도 안 받음)으로 돕니다: %s", path)
            return cls()
        approvals = str(data.get("discord_approvals") or "app_only")
        return cls(
            allowed_user_ids=[str(uid).strip() for uid in data.get("allowed_user_ids") or [] if str(uid).strip()],
            home_channel_id=str(data.get("home_channel_id") or "").strip(),
            discord_approvals=approvals if approvals in APPROVAL_POLICIES else "app_only",
            home_channel_name=str(data.get("home_channel_name") or "").strip()[:100],
            default_model_alias=str(data.get("default_model_alias") or "").strip()[:12],
        )

    def save(self, path: Path) -> None:
        body = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        if Redactor().redact(body) != body:
            raise ValueError("설정에 토큰처럼 생긴 값이 섞여 있어 저장하지 않았습니다 — 토큰은 자격 증명 관리자에만 둡니다.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
