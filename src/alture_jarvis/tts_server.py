"""**목소리 서버를 우리가 켠다** — 포장본(스토어판)에는 켜 줄 사람이 없다 (2026-09-18).

## 무엇이 있었나

아버님 노트북 진단 파일에 `[WinError 10061]` 이 찍혀 있었다. 음성 서버(:7788)가 아예 안 떠 있었던 것이다.
개발 PC 에서는 작업 스케줄러가 켜 준다(`config.supertonic_task_name`). 그런데 **포장본에는 그 작업이
없다** — 스토어에서 받은 앱은 exe 하나가 백엔드를 띄울 뿐이다. 그래서 설정에는 「소리 내어 답하기: 켜짐」
이라고 적혀 있는데 실제로는 한마디도 못 했다. 켜짐이라 적힌 것이 실제로는 못 쓰는 상태 — 그게 제일 나쁘다.

목소리 코드(`supertonic`)는 **이미 포장본에 실려 있다.** 켤 사람만 없었다. 그래서 여기서 켠다.

## 규율

- **먼저 물어본다.** 이미 떠 있으면(스케줄러가 켰든 사람이 켰든) 아무것도 하지 않는다. 두 개를 띄우면
  포트가 부딪히고, 부딪힌 쪽은 조용히 죽는다.
- **밖으로 열지 않는다.** 이 서버는 127.0.0.1 만 듣는다. 이 PC 는 위성에게 빌려주려고 0.0.0.0 으로 열지만
  (`scripts/start_supertonic.ps1`), 남의 PC 에 깔리는 판이 스스로 포트를 여는 것은 다른 이야기다.
- **막지 않는다.** 못 켜면 조용히 실패하고 화면이 「이 판에서는 음성이 안 됩니다」라고 말한다.
  음성 때문에 대화가 늦어지면 그건 고장이다.

목소리 파일(약 385MB)은 처음 말할 때 `~/.cache/supertonic3` 로 내려받는다. 사용자 폴더라 스토어판의
앱 전용 칸 문제(2026-09-18 Ollama 사고)와는 무관하다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import environment_for_our_own_child

#: 같은 순간에 두 번 켜지 않기 위한 자물쇠. 화면·자가점검·첫 발화가 동시에 부를 수 있다.
_LOCK = threading.Lock()
#: 우리가 띄운 프로세스. 살아 있으면 다시 띄우지 않는다.
_CHILD: subprocess.Popen[bytes] | None = None
#: 마지막 시도 시각 — 못 켜는 PC 에서 매번 30초를 버리지 않게 한다.
_LAST_TRY = 0.0
_RETRY_AFTER_SEC = 120.0


def available() -> bool:
    """이 판에 목소리 코드가 실려 있는가. 「켜짐」을 말할 자격이 여기서 갈린다."""
    return importlib.util.find_spec("supertonic") is not None


def answering(base_url: str, timeout: float = 2.0) -> bool:
    """실제 왕복으로 본다 — 켜져 있다는 기록이 아니라 지금 답하는지."""
    try:
        reply = httpx.get(f"{base_url.rstrip('/')}/v1/health", timeout=timeout)
        return reply.status_code == 200
    except Exception:  # noqa: BLE001 — 안 떠 있으면 그냥 안 떠 있는 것이다
        return False


def ensure(base_url: str, *, wait_sec: float = 25.0) -> dict[str, Any]:
    """안 떠 있으면 띄운다. 돌려주는 값은 **무엇을 했는지**.

    `started` 는 우리가 띄웠다는 뜻이고, `already` 는 남이(스케줄러가) 띄워 둔 것이다.
    """
    global _CHILD, _LAST_TRY

    if answering(base_url):
        return {"ok": True, "already": True}
    if not available():
        return {"ok": False, "error": "supertonic_not_bundled"}
    with _LOCK:
        if answering(base_url):
            return {"ok": True, "already": True}
        if _CHILD is not None and _CHILD.poll() is None:
            # 우리가 띄운 것이 아직 뜨는 중이다. 두 번째를 띄우면 포트가 부딪힌다.
            return {"ok": False, "error": "starting"}
        now = time.monotonic()
        if now - _LAST_TRY < _RETRY_AFTER_SEC and _LAST_TRY:
            return {"ok": False, "error": "waiting_before_retry"}
        _LAST_TRY = now
        port = urlparse(base_url).port or 7788
        command = [
            sys.executable, "-m", "alture_jarvis.tts_server",
            "--host", "127.0.0.1", "--port", str(port),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            _CHILD = subprocess.Popen(  # noqa: S603 — 명령은 코드에 박혀 있다
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
                env=environment_for_our_own_child(),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    # 떴다고 말하기 전에 **실제로 답하는지** 기다려 본다(생존 검사는 실제 왕복으로).
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        if answering(base_url):
            return {"ok": True, "started": True}
        if _CHILD is not None and _CHILD.poll() is not None:
            return {"ok": False, "error": f"exited_{_CHILD.returncode}"}
        time.sleep(1.0)
    # 아직 안 떴다고 죽이지는 않는다 — 처음 켤 때는 목소리 파일을 받느라 오래 걸린다.
    return {"ok": False, "error": "not_answering_yet"}


def main() -> int:
    """`python -m alture_jarvis.tts_server --host 127.0.0.1 --port 7788`.

    `supertonic serve` 를 그대로 부른다. 포장본에는 `Scripts\\supertonic.exe` 가 없다(포장이 Scripts 를
    안 싣는다) — 그래서 콘솔 스크립트 대신 모듈로 부르는 이 한 칸이 필요하다.
    """
    from supertonic.cli import main as supertonic_main

    argv = sys.argv[1:]
    sys.argv = ["supertonic", "serve", *argv]
    return int(supertonic_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
