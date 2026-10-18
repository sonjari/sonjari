"""디스코드 다리 진입점 (2026-10-17).

    python -m alture_jarvis.messaging setup    # 봇 토큰 확인 · 초대 링크 · 허용 목록 (대화형)
    python -m alture_jarvis.messaging check    # 지금 설정 요약 — 토큰 값은 찍지 않는다
    python -m alture_jarvis.messaging [run]    # 다리 실행 (작업 스케줄러 `RoboMetaFit-Sonjari-Discord` 가 부르는 것)

★ 작업 스케줄러는 창 없는 `pythonw.exe` 로 부른다. pythonw 에는 stdout 이 없어서 무엇이든 찍는 순간 조용히 죽는다
  (Plopfit 이 5분마다 재기동 루프였던 사고 P 의 부수 발견). 그래서 실행 모드는 화면이 아니라 **기록 파일**에 쓰고,
  stdout · stderr 가 없으면 기록 파일로 돌린다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

from .base import REDACTOR, AccessPolicy, RedactingFilter, SessionMap
from .discord_config import SETTINGS_FILE, STATE_FILE, DiscordSettings

log = logging.getLogger("sonjari.messaging")
LOCK_FILE = "discord_bridge.lock"
LOG_FILE = "discord_bridge.log"


def _setup_logging(data_dir: Path) -> None:
    folder = data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        sink = open(folder / "discord_bridge.stdout.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — 프로세스 끝까지 연다
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink
    redact = RedactingFilter(REDACTOR)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(folder / LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(redact)   # 처리기에 붙인다 — discord.py 기록까지 같은 가리개를 지난다
        root.addHandler(handler)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class _SingleInstance:
    """다리가 둘 뜨면 같은 메시지에 두 번 답한다(Hermes #18187 — 좀비 클라이언트). 파일 잠금으로 하나만."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")  # noqa: SIM115 — 잠금은 프로세스가 끝날 때까지 쥔다
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    @property
    def held(self) -> bool:
        return self._fh is not None

    def release(self) -> None:
        """쥔 잠금을 놓는다 — 본체 안의 다리(`service.DiscordService`)가 멈출 때 따로 띄우는 다리에 자리를 비켜 준다."""
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()


def compose_bridge(data_dir: Path, base_url: str, control_token: str, token: str) -> tuple[Any, Any]:
    """(어댑터, 본체 연결) — 따로 띄우는 다리(`_run`)와 본체 안의 다리(`service.DiscordService`)가 **같이** 쓰는 조립.

    ★ 2026-10-18: 본체 안에서도 다리를 돌리게 되면서 조립을 한 자리로 모았다. 둘이 따로 조립하면 홈 채널 · 승인 정책 같은
      규칙이 한쪽에만 들어간다(사고 Q 와 같은 모양).
    """
    from .bridge import SonjariBackend, TaskRunner
    from .discord_adapter import DiscordAdapter

    settings = DiscordSettings.load(data_dir / SETTINGS_FILE)
    if not settings.allowed_user_ids:
        log.warning("허용 목록이 비어 있어 아무의 말도 받지 않습니다 — setup 을 다시 돌려 사용자 ID 를 넣어 주세요.")
    path = data_dir / SETTINGS_FILE
    # 허용 목록은 모르는 보낸이가 올 때 파일을 다시 읽는다 — PC 의 「허용」이 다리를 다시 켜지 않고 반영된다.
    policy = AccessPolicy(settings.allowed_user_ids, refresh=lambda: DiscordSettings.load(path).allowed_user_ids)
    sessions = SessionMap(data_dir / STATE_FILE)
    backend = SonjariBackend(base_url, control_token)
    adapter = DiscordAdapter(token, policy=policy, sessions=sessions,
                             free_channels=frozenset({settings.home_channel_id} - {""}))
    runner = TaskRunner(adapter, backend, sessions, approvals=settings.discord_approvals,
                        default_model=lambda: DiscordSettings.load(path).default_model_alias)
    adapter.set_message_handler(runner.handle)
    adapter.set_command_handler(runner.command_reply)
    adapter.set_model_handlers(runner)
    adapter.set_access_handler(runner.access_request)
    return adapter, backend


async def _run(data_dir: Path, base_url: str, control_token: str) -> int:
    from .credentials import load_bot_token

    try:
        token = load_bot_token()
    except Exception as exc:  # noqa: BLE001 — 자격 증명 관리자를 못 열었다
        log.error("봇 토큰을 읽지 못했습니다(%s) — setup 을 먼저 돌려 주세요.", type(exc).__name__)
        return 2
    if not token:
        log.error("저장된 봇 토큰이 없습니다 — `python -m alture_jarvis.messaging setup` 을 먼저 돌려 주세요.")
        return 2
    if not control_token:
        log.error("손자리 연결 토큰(control.token)을 찾지 못했습니다 — PC 에서 손자리를 한 번 켠 뒤 다시 해 주세요.")
        return 2
    adapter, backend = compose_bridge(data_dir, base_url, control_token, token)
    if not await backend.health():
        log.warning("지금은 손자리 본체(%s)가 답하지 않습니다 — 다리는 켜 두고, 일이 들어오면 그때 다시 봅니다.", base_url)
    try:
        await adapter.run_forever()
    finally:
        await backend.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m alture_jarvis.messaging", description="디스코드로 손자리에게 일 시키기")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "setup", "check"))
    # 마법사는 기본값(앱 주인 허용 · 다른 사람 없음 · 홈 채널은 나중에)을 묻지 않고 정한다. 직접 고르려면 --advanced.
    parser.add_argument("--advanced", action="store_true", help="허용할 사람 · 홈 채널을 직접 묻는다")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001, S110 — pythonw 에는 stdout 이 없다
        pass

    from .bridge import resolve_backend

    base_url, control_token, data_dir = resolve_backend()
    if args.command == "setup":
        from .onboarding import run_setup

        return run_setup(data_dir=data_dir, advanced=args.advanced)
    if args.command == "check":
        from .credentials import load_bot_token

        settings = DiscordSettings.load(data_dir / SETTINGS_FILE)
        try:
            has_token = bool(load_bot_token())
        except Exception:  # noqa: BLE001
            has_token = False
        print(f"봇 토큰 저장됨: {'예' if has_token else '아니요'}")
        print(f"허용 사용자: {len(settings.allowed_user_ids)}명 · 승인: {settings.discord_approvals}")
        print(f"손자리 주소: {base_url} · 연결 토큰: {'있음' if control_token else '없음'}")
        print(f"설정 파일: {data_dir / SETTINGS_FILE}")
        return 0
    _setup_logging(data_dir)
    lock = _SingleInstance(data_dir / LOCK_FILE)
    if not lock.acquire():
        log.error("디스코드 다리가 이미 돌고 있습니다 — 하나만 켭니다.")
        return 3
    try:
        return asyncio.run(_run(data_dir, base_url, control_token))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 — 작업 스케줄러가 실패로 보고 다시 켜게 0 이 아닌 값으로 끝낸다
        log.error("다리가 멈췄습니다: %s", REDACTOR.redact(type(exc).__name__))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
