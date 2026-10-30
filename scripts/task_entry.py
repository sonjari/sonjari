from __future__ import annotations

import sys
from pathlib import Path

# 기동할 때 로그가 이보다 크면 한 세대만 밀어 두고 새로 쓴다.
#
# 이건 폭주를 막는 장치가 아니라 **폭주해도 로그가 쓸모를 잃지 않게** 하는
# 장치다. 실측(2026-08-09): PyAV 가 프레임마다 트레이스백을 찍어 이 파일이
# 186MB · 465만 줄이 됐고, 그중 98%가 같은 한 줄이었다. 진짜 고장(브라우저가
# 죽은 것)을 찾는 데 이 잡음을 먼저 걷어내야 했다. 원인은 원인대로 고쳤지만
# (screen_capture._ForwardOnlyStream), 다음 폭주가 어디서 올지는 알 수 없다.
_LOG_ROTATE_BYTES = 64 * 1024 * 1024


def _rotate_if_huge(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < _LOG_ROTATE_BYTES:
            return
        previous = path.with_suffix(path.suffix + ".1")
        previous.unlink(missing_ok=True)
        path.rename(previous)
    except Exception:
        # 로그를 못 민다고 자비스가 안 뜨면 그게 더 나쁘다.
        pass


def _mark_life(stream) -> None:
    """이 백엔드가 **언제 떴고 · 어떻게 끝났는지** 로그에 남긴다 (2026-10-30 · 10-29 07:16 판 도중 꺼짐).

    그날 백엔드가 판 도중 말없이 사라졌는데 원인을 못 가렸다 — 이 로그(uvicorn 줄)에는 시각이 없고, 끝나는 줄도 없고,
    재시작 직전에 오류 줄이 하나도 없었다. 그래서 세 가지를 남긴다:
    시작 시각 · PID / 정상으로 끝나면 「정상 종료」 한 줄(이 줄이 없으면 밖에서 죽인 것) / C 수준에서 터지면 모든 스레드의 스택(`faulthandler`).
    """
    import atexit
    import faulthandler
    import os
    import time

    def stamp(what: str) -> None:
        try:
            stream.write(f"[life] {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {what}\n")
            stream.flush()
        except Exception:
            pass

    stamp("시작")
    atexit.register(stamp, "정상 종료")
    try:
        faulthandler.enable(file=stream, all_threads=True)
    except Exception:
        pass


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ★ `.env` 를 **여기 있는 기본값들보다 먼저** 싣는다 (2026-08-24).
    #
    # 아래 기본값은 전부 「이미 있으면 안 덮는다」인데, `.env` 로더도 같은 규칙이다(`load_env_file`). 그래서 순서가 곧
    # 우선순위였고, 예전에는 여기가 먼저 돌아서 **`.env` 가 영원히 졌다.**
    #
    # 실측: 본체 `.env` 에 `JARVIS_HOST=0.0.0.0` 을 적고 재시작했는데 계속 `127.0.0.1` 만 들었다. 그래서 위성이 제어 API 에
    # 아예 못 닿았고, 「방화벽인가 테일스케일인가」로 한참 봤다. 값이 사는 자리가 셋이고(dataclass 기본값 · 환경변수 로더 ·
    # **함수 안 하드 상수**) 제일 안 보이는 세 번째였다 — 사고 Q 와 같은 모양이다.
    #
    # 뜻하는 우선순위:  사용자 환경변수  >  .env  >  여기 기본값
    #
    # ★ 2026-10-09: 이 값들을 **프로세스 환경에 쓰지 않는다.** 환경에 두면 손자리가 켜는 모든 프로그램이 열쇠와 데이터 위치를
    #   물려받는다(`config._PRIVATE` 의 설명). 물려받은 것은 안으로 옮기고, 여기 기본값도 안쪽 보관소에 둔다. 우선순위는 그대로다.
    #
    # config 를 **try 밖에** 불러온다 — 못 불러오면 어차피 못 뜬다.
    sys.path.insert(0, str(project_root / "src"))
    from alture_jarvis import config

    # 물려받은 JARVIS_* 를 보관소로 옮기고 환경에서 지운다.
    config.absorb_environment()

    # 런타임 루트는 여기가 정한다(환경·보관소에 없으면 덮는다).
    config.keep_private("JARVIS_RUNTIME_ROOT", str(project_root), override=True)

    # `.env` 를 보관소에 싣는다(환경·보관소에 이미 있는 이름은 덮지 않는다).
    try:
        config.load_env_file(project_root / ".env")
    except Exception:
        # `.env` 를 못 읽는다고 자비스가 안 뜨면 그게 더 나쁘다. 아래 기본값으로 뜬다.
        pass

    # 나머지 기본값들(override 없이 — 환경·보관소에 있으면 안 된다).
    config.keep_private("JARVIS_HOST", "127.0.0.1")
    config.keep_private("JARVIS_PORT", "8091")
    # Public defaults stay read-only and hardware-neutral. An installation may
    # opt into Google/browser writes, cameras, or a specific GPU in its `.env`.
    config.keep_private("JARVIS_GOOGLE_WRITE_ENABLED", "false")
    config.keep_private("JARVIS_BROWSER_READ_ONLY", "true")
    config.keep_private("JARVIS_CAMERA_CONTROL_ENABLED", "false")
    config.keep_private("JARVIS_CAMERA_SCREEN_CAPTURE", "false")

    for name in ("jarvis.stdout.log", "jarvis.stderr.log"):
        _rotate_if_huge(output_dir / name)
    stdout = (output_dir / "jarvis.stdout.log").open("a", encoding="utf-8", buffering=1)
    stderr = (output_dir / "jarvis.stderr.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = stdout
    sys.stderr = stderr
    _mark_life(stderr)

    from alture_jarvis.__main__ import main as run_jarvis

    run_jarvis()


if __name__ == "__main__":
    main()
