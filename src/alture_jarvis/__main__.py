from __future__ import annotations

import uvicorn

from .config import JarvisConfig, absorb_environment, load_env_file
from .os_trust import use_os_trust_store


def raise_open_file_limit(target: int = 8192) -> tuple[int, int] | None:
    """열 수 있는 파일 · 연결 수의 한도를 올린다(맥 · 리눅스). 윈도우는 해당 없음 → None.

    ★ 2026-11-10 맥 27시간 사고: launchd 로 뜬 백엔드의 한도가 256 이었다. 크롬 화면 중계 · 웹소켓 · DB 가
    그 한도를 다 쓰자 일꾼이 DB 를 못 열고 죽었다. 새는 곳은 따로 쫓되, 256 은 손자리에게 너무 낮다.
    돌려주는 값 = (전, 후) 한도.
    """
    try:
        import resource
    except ImportError:
        return None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if soft != resource.RLIM_INFINITY and soft < want:
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
            except (ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_NOFILE, (min(want, 10240), hard))  # 맥 OPEN_MAX
        return soft, resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except (ValueError, OSError):
        return None


def main() -> None:
    raise_open_file_limit()
    # HTTPS 검사를 윈도우에 맡긴다 — 초기화한 PC 에서 Ollama 받기가 인증서로 죽었다(os_trust 참고).
    use_os_trust_store()
    # 물려받은 JARVIS_* 를 보관소로 옮기고 환경에서 지운다.
    absorb_environment()
    # `.env` 를 읽는다. 이미 환경에 있는 값은 덮지 않으므로 task_entry.py 가 켜 둔
    # 스위치들이 그대로 이긴다 — .env 는 환경에 **없는** 것만 채운다.
    load_env_file()
    # ★ GPU 배치는 기동 경로와 상관없이 하나다(2026-09-28, gpu_policy 참고). API 를 올리기 **전** —
    #   거기서 torch·음성 라이브러리가 CUDA 를 잡으면 이미 늦다.
    from .gpu_policy import apply_process_gpu_policy

    apply_process_gpu_policy()
    config = JarvisConfig.from_env()
    uvicorn.run(
        "alture_jarvis.api:app",
        host=config.host,
        port=config.port,
        log_level="info",
        # The HUD WebSocket authenticates through its local query string. Do not log secrets.
        access_log=False,
    )


if __name__ == "__main__":
    main()
