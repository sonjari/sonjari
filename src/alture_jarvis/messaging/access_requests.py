"""허용 목록 밖 사람이 봇에게 말을 건 기록 — PC 화면의 「가족 · 동료 추가」 카드 (2026-10-18).

## 왜

가족 · 동료를 들이려면 그 사람의 디스코드 사용자 ID 가 필요했다(개발자 모드 → 오른쪽 클릭 → ID 복사). 보통 사람은 못 한다.
그래서 거꾸로 한다: 그 사람이 봇에게 먼저 말을 걸면, 다리는 **일을 시작하지 않고** 여기에 「허용 요청」을 남긴다.
주인이 PC 화면에서 「허용」을 누르면 그때 허용 목록에 들어간다. **주인 말고 다른 사람에게 일을 맡기는 문은 그 버튼 하나뿐이다.**

- 그 사람에게는 같은 사람 하루 한 번만 「주인이 PC 에서 허용하면 답합니다」를 보낸다(`NOTICE_EVERY_SEC`).
- 「무시」한 사람은 다시 말해도 카드를 띄우지 않고 답도 하지 않는다.
- 남기는 것: 사용자 ID · 표시 이름 · 사용자명 · 처음 말한 시각 · 첫 메시지 앞 80자. 비밀은 없다(`discord_access_requests.json`).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

REQUESTS_FILE = "discord_access_requests.json"
NOTICE_EVERY_SEC = 24 * 3600.0
FIRST_TEXT_CHARS = 80
#: 요청이 끝없이 쌓이지 않게 — 오래된 것부터 버린다.
MAX_REQUESTS = 200
MAX_IGNORED = 1000


def clean_user_id(value: Any) -> str:
    uid = str(value or "").strip()
    return uid if uid.isdigit() and 5 <= len(uid) <= 25 else ""


class AccessRequestBook:
    def __init__(self, data_dir: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(data_dir) / REQUESTS_FILE
        self._clock = clock
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        requests = data.get("requests") if isinstance(data.get("requests"), dict) else {}
        ignored = [str(uid) for uid in data.get("ignored") or [] if clean_user_id(uid)]
        return {"requests": {str(k): v for k, v in requests.items() if isinstance(v, dict) and clean_user_id(k)},
                "ignored": ignored}

    def _write(self, data: dict[str, Any]) -> None:
        requests = dict(sorted(data["requests"].items(), key=lambda kv: float(kv[1].get("first_seen") or 0))[-MAX_REQUESTS:])
        body = {"requests": requests, "ignored": data["ignored"][-MAX_IGNORED:]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")

    def record(self, user_id: str, *, display_name: str = "", username: str = "", text: str = "") -> dict[str, Any]:
        """말을 건 기록 하나. {"notify": 그 사람에게 안내를 보낼까, "new": 처음 온 요청인가, "ignored", "request"}."""
        uid = clean_user_id(user_id)
        if not uid:
            return {"notify": False, "new": False, "ignored": False, "request": None}
        now = self._clock()
        with self._lock:
            data = self._read()
            if uid in data["ignored"]:
                return {"notify": False, "new": False, "ignored": True, "request": None}
            entry = data["requests"].get(uid)
            new = entry is None
            if new:
                entry = {"user_id": uid, "display_name": "", "username": "", "first_seen": now,
                         "first_text": " ".join(str(text or "").split())[:FIRST_TEXT_CHARS], "count": 0,
                         "last_seen": now, "last_notified": 0.0}
            entry["display_name"] = str(display_name or entry.get("display_name") or "").strip()[:100]
            entry["username"] = str(username or entry.get("username") or "").strip()[:100]
            entry["count"] = int(entry.get("count") or 0) + 1
            entry["last_seen"] = now
            last = float(entry.get("last_notified") or 0)
            notify = not last or now - last >= NOTICE_EVERY_SEC   # 한 번도 안 알렸으면 지금
            if notify:
                entry["last_notified"] = now
            data["requests"][uid] = entry
            self._write(data)
        return {"notify": notify, "new": new, "ignored": False, "request": public(entry)}

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read()
        rows = sorted(data["requests"].values(), key=lambda row: float(row.get("first_seen") or 0))
        return [public(row) for row in rows]

    def ignored_count(self) -> int:
        with self._lock:
            return len(self._read()["ignored"])

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._read()["requests"].get(clean_user_id(user_id))
        return public(entry) if entry else None

    def pop(self, user_id: str) -> dict[str, Any] | None:
        uid = clean_user_id(user_id)
        with self._lock:
            data = self._read()
            entry = data["requests"].pop(uid, None)
            if entry is not None:
                self._write(data)
        return public(entry) if entry else None

    def ignore(self, user_id: str) -> bool:
        uid = clean_user_id(user_id)
        if not uid:
            return False
        with self._lock:
            data = self._read()
            data["requests"].pop(uid, None)
            if uid not in data["ignored"]:
                data["ignored"].append(uid)
            self._write(data)
        return True


def public(entry: dict[str, Any]) -> dict[str, Any]:
    """화면 · 이벤트에 싣는 모양 — 안내를 언제 보냈는지 같은 안쪽 칸은 뺀다."""
    return {key: entry.get(key) for key in ("user_id", "display_name", "username", "first_seen", "first_text",
                                            "count", "last_seen")}
