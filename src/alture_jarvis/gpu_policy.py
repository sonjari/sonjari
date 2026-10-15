"""온텔릭 프로세스가 **어떤 GPU 를 보는가**를 기동 경로와 상관없이 하나로 정한다 (2026-09-28).

## 무엇이 있었나

집 PC 는 3090(모델 전용) + 3060(화면·음성·비전) 이다. 사용자 전역 환경변수에 `CUDA_VISIBLE_DEVICES=0` 이 걸려
있었다 — Ollama 를 3090 에 묶으려고 넣은 값이다. 정식 기동(`scripts/start.ps1`)은 백엔드에서만 그 값을 `0,1` 로
덮어써 두 장을 다 보게 했다. 그런데 배포 절차대로 `task_entry.py` 를 명령줄로 다시 띄우면 그 덮어쓰기를 **안 거쳤다.**

그러자 백엔드에는 3090 한 장만 보였고, 「1번 카드(3060)」로 정해 둔 음성 인식·비전이 「1번이 없다」며 0번(3090)으로
내려가 1.3GB 를 잡았다. 그다음 Ollama 가 모델을 올릴 때 1.18GB 가 모자라 전문가 층 1.5GB 를 CPU 로 뺐고, 코드 모드처럼
길게 생성하는 일마다 CPU 가 PC 전체의 80~95% 로 튀었다. 증상(느림·CPU)과 원인(환경변수 하나)이 세 단계 떨어져 있었다.

## 규칙

1. 번호는 **nvidia-smi 와 같은 순서**(PCI 버스)로 센다 — 설정 화면·사양 판정이 nvidia-smi 로 읽으니 번호가 같아야 한다.
2. 사용자 전역 `CUDA_VISIBLE_DEVICES` 는 다른 도구(Ollama 등)를 위한 값이다. 온텔릭은 물려받지 않고 **모든 카드를 본 뒤
   자기 설정(음성·비전 장치 번호)으로 고른다.** 온텔릭만 좁히고 싶으면 `JARVIS_CUDA_VISIBLE_DEVICES` 를 쓴다.
3. 물려받은 값은 버리지 않고 적어 둔다 — 온텔릭이 Ollama 를 직접 띄울 때 그대로 돌려준다(`child_env_for_ollama`).
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Any

#: 기동 때 물려받은 사용자 값. 빈 문자열은 「원래 없었다」.
INHERITED_KEY = "ONTELIC_INHERITED_CUDA_VISIBLE_DEVICES"
#: 번호 세는 순서도 돌려준다 — 사용자의 `0` 은 **그 사람 순서로** 센 0 이다.
INHERITED_ORDER_KEY = "ONTELIC_INHERITED_CUDA_DEVICE_ORDER"


def apply_process_gpu_policy(environ: MutableMapping[str, str] | None = None) -> dict[str, Any]:
    """**CUDA 라이브러리를 부르기 전에** 한 번 부른다. 여러 번 불러도 결과가 같다. 한 일을 돌려준다(/health 용)."""
    env = os.environ if environ is None else environ
    if INHERITED_KEY not in env:
        env[INHERITED_KEY] = env.get("CUDA_VISIBLE_DEVICES", "")
        env[INHERITED_ORDER_KEY] = env.get("CUDA_DEVICE_ORDER", "")
    inherited = env[INHERITED_KEY]
    env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    own = str(env.get("JARVIS_CUDA_VISIBLE_DEVICES") or "").strip()
    if own:
        env["CUDA_VISIBLE_DEVICES"] = own
    else:
        env.pop("CUDA_VISIBLE_DEVICES", None)
    return {
        "device_order": env.get("CUDA_DEVICE_ORDER", ""),
        "visible": own or "all",
        "inherited_ignored": inherited if inherited and inherited != own else "",
    }


def child_env_for_ollama(environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """온텔릭이 띄우는 Ollama 에 줄 환경. 사용자가 Ollama 를 위해 정해 둔 카드 제한을 **그대로** 돌려준다."""
    env = dict(os.environ if environ is None else environ)
    for key, name in ((INHERITED_KEY, "CUDA_VISIBLE_DEVICES"), (INHERITED_ORDER_KEY, "CUDA_DEVICE_ORDER")):
        if key not in env:
            continue
        inherited = env.pop(key)
        if inherited:
            env[name] = inherited
        else:
            env.pop(name, None)
    return env
