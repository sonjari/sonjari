from __future__ import annotations

import uvicorn

from .config import JarvisConfig, absorb_environment, load_env_file
from .os_trust import use_os_trust_store


def main() -> None:
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
