"""램 부스트 — 그래픽카드가 작거나 다른 프로그램이 쥐어도, 남는 램으로 MoE 모델을 돌린다 (2026-11-11 대표 결정).

## 왜
16GB 카드 · 램 64GB · 3ds Max 를 쓰는 사용자 PC 에서 Qwen 3.6 2비트가 「CPU 로 돌고 있습니다」로 떴고, 손자리를 껐다 켜자 됐다.
3.6 은 MoE 라 한 번에 일하는 부분이 3B 뿐이다 — 큰 몫(전문가)을 일반 메모리에 두어도 많이 안 느려진다.
6GB 노트북(3050 · 램 24GB)에서 이렇게 돌려 초당 25.5토큰 · 가격 찾기 5/9(4B 는 0.7~1.4) · 첫 읽기 72~95초(n=1 · 11-09).

## 어떻게
Ollama 0.35 는 엔진(llama-server)에 「몇 층을 카드에」(`-ngl`)를 안 넘기고 엔진의 자동 맞춤(`--fit`)에 맡긴다
(노트북 serve.log 11-11). 엔진은 Ollama 의 환경을 그대로 받는다(`ollama_install.PROMPT_CACHE_ENV` 의 설명).
그런데 윈도우에서 엔진은 **다른 프로그램이 쥔 그래픽 메모리를 못 본다**(10-23 실측 · `gpu_pressure` 머리말).
그래서 그 몫을 `nvidia-smi` 로 재서 「이만큼 비워 둬」(`LLAMA_ARG_FIT_TARGET`, MiB)로 알린다 — 그러면 자동 맞춤이 남은 자리에
맞춰 나머지를 램으로 옮긴다.

## 기준 (대표 11-11)
전체 램이 아니라 **바꾸는 순간 남은 램 ≥ 전문가 몫 + 여유 4GB**. 안내는 32GB 권장 · 24GB 가능.
설계: `generated_reports/ram_boost_1111/설계_램부스트_1111.md`.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

#: 엔진이 비워 둘 몫을 읽는 환경 이름(llama.cpp `--fit-target`, 장치마다 MiB).
FIT_TARGET_ENV = "LLAMA_ARG_FIT_TARGET"
#: 엔진 기본 여유(10-23 실측 · `gpu_pressure.FREE_FLOOR_GB` 의 설명)와 우리가 더 얹는 몫(MiB).
ENGINE_DEFAULT_MARGIN_MIB = 1024
EXTRA_MARGIN_MIB = 512
#: 남은 램에서 전문가 몫을 빼고도 남겨야 할 여유(GB) — 대표 11-11 「전문가 몫 + 4GB」.
RAM_MARGIN_GB = 4.0
#: MoE 모델 파일 가운데 전문가 몫의 비율. ★ 짐작이다(35B 중 3B 만 일하는 구조에서 셈) — 실측으로 바꿀 것.
EXPERT_SHARE_GUESS = 0.9

#: 램 부스트를 쓸 수 있는 모델(마법사 키 → 파일 크기 GB · MoE 여부). 파일 크기는 허깅페이스에서 확인(11-11).
MOE_MODELS: dict[str, dict[str, Any]] = {
    "qwen3.6-35b-iq2m": {"file_gb": 11.52, "moe": True},
    # ★ 11-11 대표: 램이 넉넉하면 4비트로(2비트는 같은 날 출시 전 시험에서 가격 조사 값 0/3). Ollama 공식 `qwen3.6:35b-a3b` 본체
    #   21.72GB(이 PC 의 모델 폴더에서 잼 · 그림 부속 0.9GB 따로). 같은 집안이라 넘김 · 부스트 길은 그대로 탄다.
    "qwen3.6-35b-a3b": {"file_gb": 21.72, "moe": True},
}

#: 램이 되면 먼저 고를 순서 — 좋은 것(4비트)부터. `model_fallback` · 마법사가 같이 쓴다.
BOOST_LADDER: tuple[str, ...] = ("qwen3.6-35b-a3b", "qwen3.6-35b-iq2m")
#: 사다리 윗칸(4비트)은 모델의 이만큼 이상이 그래픽카드에 올라갈 때만 고른다 (2026-11-12 출시 문 시험).
#:   12GB 카드 + 짐에서 4비트는 20% 만 올라가 긴 판에서 첫 글자가 5분씩 안 나왔고(두 번) 가격 과제가 시간 제한에 걸렸다.
#:   같은 시험을 0.4.44 의 2비트(52% 올라감)는 통과했다. 0.5 는 그 둘 사이의 첫 값이다 — 재서 고친다.
CARD_SHARE_MIN = 0.5


def card_share(model_key: str, card: dict[str, Any] | None, ours_gb: float = 0.0, min_fit_mib: int = 0) -> float | None:
    """램 부스트로 올렸을 때 그 모델 파일 중 그래픽카드에 올라갈 비율(0~1). 카드를 모르면 None."""
    info = MOE_MODELS.get(model_key)
    if not info or not card or not card.get("total_gb"):
        return None
    target = max(fit_target_mib(card, ours_gb), int(min_fit_mib or 0))
    room_gb = max(0.0, float(card["total_gb"]) * 1024 - target) / 1024
    return round(min(1.0, room_gb / float(info["file_gb"])), 3)


def ram_free_gb() -> float | None:
    """지금 남은 일반 메모리(GB). 윈도우만 — 맥은 통합 메모리라 이 장치가 해당 없다(None)."""
    if os.name != "nt" or sys.platform == "darwin":
        return None

    class _Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _Status()
    status.dwLength = ctypes.sizeof(_Status)
    try:
        from . import winapi

        if not winapi.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except Exception:  # noqa: BLE001 — 못 재면 모른다
        return None
    return round(status.ullAvailPhys / 2**30, 1)


def need_ram_gb(model_key: str) -> float | None:
    """그 모델을 램 부스트로 돌릴 때 남아 있어야 할 램(GB). MoE 가 아니거나 모르는 모델이면 None."""
    info = MOE_MODELS.get(model_key)
    if not info or not info.get("moe"):
        return None
    return round(float(info["file_gb"]) * EXPERT_SHARE_GUESS + RAM_MARGIN_GB, 1)


def fit_target_mib(card: dict[str, Any] | None, ours_gb: float = 0.0) -> int:
    """엔진에게 「이만큼 비워 둬」라고 할 몫(MiB) = 다른 프로그램이 쥔 몫 + 엔진 기본 여유 + 우리 여유.

    다른 프로그램 몫 = 카드 사용 − 우리 모델 몫. Ollama 작업 버퍼가 섞여 **부풀려질 수 있다** — 부풀리면 전문가가 램으로
    조금 더 가서 느려질 뿐 죽지는 않는 쪽이라 받아들인다(반대로 작게 세면 카드가 넘쳐 윈도우가 조용히 시스템 메모리로 민다).
    """
    if not card:
        return ENGINE_DEFAULT_MARGIN_MIB + EXTRA_MARGIN_MIB
    others = max(0.0, float(card.get("used_gb") or 0) - max(0.0, float(ours_gb or 0)))
    return int(others * 1024) + ENGINE_DEFAULT_MARGIN_MIB + EXTRA_MARGIN_MIB


def plan(model_key: str, *, card: dict[str, Any] | None, ram_free: float | None, ours_gb: float = 0.0,
         min_fit_mib: int = 0) -> dict[str, Any]:
    """램 부스트를 할 수 있나 · 한다면 엔진에 줄 환경. 하지 않는 까닭은 `why` 로.

    양쪽 다 지킨다: 램이 모자라면 하지 않는다(일반 메모리까지 차면 PC 전체가 멈춘다) · MoE 가 아니면 하지 않는다
    (밀집 모델은 램으로 가면 초당 6토큰 안팎 — 10-30 Swift 27B 흉내 실측).
    """
    need = need_ram_gb(model_key)
    if need is None:
        return {"ok": False, "why": "not_moe", "model": model_key}
    if ram_free is None:
        return {"ok": False, "why": "ram_unknown", "model": model_key, "need_ram_gb": need}
    if float(ram_free) < need:
        return {"ok": False, "why": "ram_short", "model": model_key, "need_ram_gb": need, "ram_free_gb": ram_free}
    # 「그래픽카드 비워 두기」(gpu_mode keep_free)는 남이 아직 안 쥐었어도 정해 둔 몫을 비워 둔다.
    target = max(fit_target_mib(card, ours_gb), int(min_fit_mib or 0))
    return {
        "ok": True, "model": model_key, "need_ram_gb": need, "ram_free_gb": ram_free,
        "fit_target_mib": target, "env": {FIT_TARGET_ENV: str(target)},
        "card": dict(card) if card else None,
    }


def lower_cache_ram(mib: int) -> int:
    """부스트 중에는 엔진의 대화 보관함(`LLAMA_ARG_CACHE_RAM`)을 반으로 — 전문가가 램을 먹는다. 2GB 아래로는 안 내린다."""
    if mib <= 0:
        return mib
    return max(2048, int(mib) // 2)


STATE_FILE = "ram_boost.json"


def read_state(data_dir: Path | str) -> dict[str, Any]:
    try:
        value = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 — 없거나 깨졌으면 부스트 안 한 것으로
        return {}


def write_state(data_dir: Path | str, state: dict[str, Any] | None) -> None:
    path = Path(data_dir) / STATE_FILE
    if not state:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


class Booster:
    """램 부스트를 켜고 끄는 손. `installer` 는 `OllamaInstaller`(환경 바꿔 다시 켜기) · `service` 는 `model_setup.SetupService`.

    켠 사실은 `data/ram_boost.json` 에 남는다 — 손자리를 다시 켜도 같은 환경으로 Ollama 를 켠다(`resume`).
    끄기는 「원래 모델로」(`model_fallback.restore`)를 따른다 — 자동으로 끄지 않는다(10-30 결정과 같은 까닭: 판마다 왔다 갔다 하지 않게).
    """

    def __init__(self, *, installer: Any, service: Any, data_dir: Path | str,
                 ram: Callable[[], float | None] = ram_free_gb,
                 audit: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.installer = installer
        self.service = service
        self.data_dir = Path(data_dir)
        self._ram = ram
        self._audit = audit or (lambda event, payload: None)

    @property
    def active(self) -> bool:
        return bool(getattr(self.installer, "boost_env", None))

    def resume(self) -> bool:
        """켤 때: 지난번에 켠 부스트가 있으면 Ollama 를 켜기 **전에** 그 환경을 쥐어 둔다(다시 켜지는 않는다)."""
        state = read_state(self.data_dir)
        env = state.get("env") if isinstance(state.get("env"), dict) else None
        if not env:
            return False
        self.installer.boost_env = {str(k): str(v) for k, v in env.items()}
        return True

    def fits(self, model_key: str) -> bool:
        """지금 남은 램으로 그 모델을 램 부스트로 돌릴 수 있나(비트 고르기 · 11-11)."""
        need = need_ram_gb(model_key)
        free = self._ram()
        return need is not None and free is not None and float(free) >= need

    def engage(self, model_key: str, num_ctx: int, facts: dict[str, Any] | None = None, *,
               job_id: str = "", reason: str = "", min_fit_mib: int = 0) -> dict[str, Any]:
        """할 수 있으면 부스트 환경으로 Ollama 를 다시 켜고 그 모델을 올려 속도를 잰다. {"action": "boosted"|"none"|"failed", …}."""
        facts = dict(facts or {})
        card = None
        if facts.get("card_total_gb"):
            card = {"used_gb": facts.get("card_used_gb") or 0, "total_gb": facts.get("card_total_gb")}
        decided = plan(model_key, card=card, ram_free=self._ram(), ours_gb=float(facts.get("model_gb") or 0),
                       min_fit_mib=min_fit_mib)
        self._audit("ram_boost_plan", {"job_id": job_id, "reason": reason, **{k: v for k, v in decided.items() if k != "env"}})
        if not decided.get("ok"):
            return {"action": "none", "why": decided.get("why"), "plan": decided}
        restarted = self.installer.set_boost(decided["env"])
        if not restarted.get("ok"):
            self.installer.boost_env = {}
            self._audit("ram_boost_failed", {"job_id": job_id, "stage": "restart", "error": restarted.get("error")})
            return {"action": "failed", "error": str(restarted.get("error") or "restart_failed")}
        applied = self.service.apply(model_key, int(num_ctx), eyes=False, accept_spill=True)
        if not applied.get("ok"):
            self._audit("ram_boost_failed", {"job_id": job_id, "stage": "apply", "error": applied.get("error")})
            return {"action": "failed", "error": str(applied.get("error") or "apply_failed")}
        speed = (applied.get("verified") or {}).get("tokens_per_sec")
        write_state(self.data_dir, {"env": decided["env"], "model": model_key, "num_ctx": int(num_ctx), "at": time.time(),
                                    "job_id": job_id, "reason": reason, "plan": {k: v for k, v in decided.items() if k != "env"},
                                    "tokens_per_sec": speed})
        self._audit("ram_boost_on", {"job_id": job_id, "reason": reason, "model": model_key,
                                     "fit_target_mib": decided["fit_target_mib"], "ram_free_gb": decided["ram_free_gb"],
                                     "tokens_per_sec": speed})
        return {"action": "boosted", "to": applied.get("chat_model"), "tokens_per_sec": speed,
                "fit_target_mib": decided["fit_target_mib"], "ram_free_gb": decided["ram_free_gb"], "applied": applied}

    def release(self) -> dict[str, Any]:
        """부스트를 끈다(「원래 모델로」). 켜져 있지 않았으면 아무것도 안 한다."""
        if not self.active and not read_state(self.data_dir):
            return {"ok": True, "released": False}
        write_state(self.data_dir, None)
        result = self.installer.set_boost(None)
        self._audit("ram_boost_off", {"restart": result.get("restarted"), "ok": result.get("ok")})
        return {**result, "released": True}


def boosted_line(english: bool) -> str:
    if english:
        return ("The graphics card is busy, so I moved part of the model into spare RAM (RAM Boost) - "
                "say 'go back to the usual model' to undo")
    return "그래픽카드가 모자라 모델 일부를 남는 램으로 옮겼습니다(램 부스트) — 「원래 모델로」라고 하시면 돌아갑니다"
