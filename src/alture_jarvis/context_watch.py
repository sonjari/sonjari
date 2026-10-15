"""컨텍스트 감시 — 모델이 올라간 카드에 붙은 **프로그램 목록이 바뀌었나**를 30분마다 본다 (2026-09-23 제품 요청).

## 왜

상한은 잰 순간의 카드 사정에 묶인다. 잰 뒤에 그 카드를 쓰는 프로그램이 들어오거나 나가면, 다시 재야 맞는지
알 수 있다 — 그런데 아무도 다시 재지 않는다. 그래서 바뀌었다는 **사실**을 모델 칩의 작은 점으로 알린다.

## 재지 않고 **보기만** 한다

재기(`SetupService.measure_context_ceiling`)는 모델을 내렸다 올려 도는 일을 끊는다. 30분마다 그럴 수는 없다.
여기서는 `nvidia-smi` 한 번(1초 안)만 쓴다:

    잴 때 모델 카드에 붙어 있던 프로그램 목록  ─┐
    지금 목록                                  ─┴→ 달라졌으면 「카드 사정이 바뀌었습니다 — 다시 재 볼까요?」

## 말하지 않는 것 — 역검증에서 틀렸다

「얼마나(GB) 여유가 생겼나」와 「몇 K 까지 올라갈 것 같다」는 말하지 않는다. 처음엔 「카드 사용량 − 모델 몫」을
남의 몫으로 셌는데, 윈도우는 프로세스별 메모리가 `[N/A]` 이고, 그 차이의 대부분은 **Ollama 자신의 작업 버퍼**였다.
실측(2026-09-23 이 PC): 뱀부 스튜디오가 3090 에 있을 때와 없을 때 qwen3.6 64K 의 그래픽카드 비율이 둘 다 96.63%.
화면 출력(모니터)은 판단에서 뺀다(제품 요청) — 모델 카드가 아닌 카드는 보지 않는다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import PureWindowsPath
from typing import Any, Callable

#: 우리 것 — 남의 몫 목록에서 뺀다.
_OURS = ("llama-server", "ollama")

Runner = Callable[..., Any]


def _run(run: Runner | None, args: list[str]) -> str:
    try:
        done = (run or subprocess.run)(args, capture_output=True, text=True, timeout=10,
                                       creationflags=0x08000000 if os.name == "nt" else 0)
        return str(done.stdout or "") if getattr(done, "returncode", 1) == 0 else ""
    except Exception:  # noqa: BLE001 — nvidia-smi 가 없거나 멈추면 「모름」이다
        return ""


def own_pids() -> set[int]:
    """손자리 자신 — 이 프로세스·조상·자손. 이름이 `python` 이라 남의 프로그램으로 셌다(2026-09-30 「새로: python」).

    ★ 백엔드가 화면을 찍으면 그 카드에 붙는다(실측: task_entry 의 python.exe 가 3060 목록에 있었다). 이름으로는
      사용자의 다른 파이썬과 못 가른다 — PID 로 가른다.
    """
    pids = {os.getpid(), os.getppid()}
    try:
        import psutil  # noqa: PLC0415

        me = psutil.Process()
        pids.update(p.pid for p in me.parents())
        pids.update(p.pid for p in me.children(recursive=True))
    except Exception:  # noqa: BLE001 — psutil 이 없으면 나와 부모만
        pass
    return pids


def gpu_snapshot(run: Runner | None = None, ours: set[int] | None = None) -> dict[str, Any]:
    """카드별 사용량과 붙어 있는 프로그램 이름. 못 읽으면 `{"gpus": []}`. 손자리 자신(`ours`)은 뺀다."""
    ours = own_pids() if ours is None else ours
    gpus: dict[str, dict[str, Any]] = {}
    text = _run(run, ["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total,display_active",
                      "--format=csv,noheader,nounits"])
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus[parts[1]] = {"index": int(parts[0]), "uuid": parts[1], "used_gb": round(float(parts[2]) / 1024, 2),
                              "total_gb": round(float(parts[3]) / 1024, 2),
                              "display": parts[4].lower() == "enabled", "apps": []}
        except ValueError:
            continue
    apps = _run(run, ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name", "--format=csv,noheader"])
    for line in apps.splitlines():
        parts = [p.strip() for p in line.split(",", 2)]
        if len(parts) == 3 and parts[0] in gpus:
            if parts[1].isdigit() and int(parts[1]) in ours:
                continue
            gpus[parts[0]]["apps"].append(PureWindowsPath(parts[2]).stem if "\\" in parts[2] else parts[2])
    return {"gpus": sorted(gpus.values(), key=lambda g: g["index"])}


def model_gpu(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """모델이 올라간 카드 = Ollama 러너가 붙은 카드. 없으면 가장 큰 카드."""
    gpus = snapshot.get("gpus") or []
    for gpu in gpus:
        if any(name.lower().startswith(_OURS) for name in gpu.get("apps") or []):
            return gpu
    return max(gpus, key=lambda g: g.get("total_gb") or 0) if gpus else None


def others(gpu: dict[str, Any]) -> list[str]:
    """그 카드에 붙은 **남의** 프로그램 이름(중복 없이). 권한 없어 이름을 못 읽은 것은 뺀다."""
    seen: list[str] = []
    for name in gpu.get("apps") or []:
        low = name.lower()
        if low.startswith(_OURS) or "insufficient" in low or name in seen:
            continue
        seen.append(name)
    return seen


def slope_gb_per_k(steps: list[dict[str, Any]]) -> float:
    """그래픽카드에 온전히 올라간 칸들로 잰 **컨텍스트 1K 당 GB**. 두 칸이 안 되면 0(모름)."""
    fits = sorted((s for s in steps if s.get("passed") and s.get("size_gb")), key=lambda s: s["num_ctx"])
    if len(fits) < 2 or fits[-1]["num_ctx"] == fits[0]["num_ctx"]:
        return 0.0
    return max(0.0, (fits[-1]["size_gb"] - fits[0]["size_gb"]) / ((fits[-1]["num_ctx"] - fits[0]["num_ctx"]) / 1024))


def assess(record: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """잰 때와 지금, 모델 카드에 붙은 **프로그램 목록**이 달라졌나. `state`: changed · steady · unknown.

    ★ 2026-09-23 역검증으로 GB 추정을 뺐다. 처음엔 「카드 사용량 − 모델 몫(size_vram) = 남의 몫」으로 늘어난 여유를
      셌는데, 그 차이의 대부분이 **Ollama 자신의 작업 버퍼**였다(size_vram 에 안 잡힌다). 뱀부 스튜디오가 있을 때와
      없을 때 64K 비율이 둘 다 96.63% — 남의 프로그램이 상한을 바꾼다는 증거가 0건인데 추정은 「여유가 3GB 늘었다」고
      헛깜빡임을 냈을 것이다. 그래서 **사실만**(누가 빠지고 들어왔나) 말하고, 다시 재 보기를 권한다. 판단은 실측이 한다.
    """
    gpu = next((g for g in snapshot.get("gpus") or [] if g.get("uuid") == record.get("gpu_uuid")), None)
    if not record.get("ceiling") or "others_apps" not in record or gpu is None:
        return {"state": "unknown"}
    then = set(record.get("others_apps") or [])
    now = set(others(gpu))
    left, joined = sorted(then - now), sorted(now - then)
    return {"state": "changed" if (left or joined) else "steady", "left": left, "joined": joined,
            "gpu_index": gpu.get("index"), "measured_at": record.get("measured_at", "")}
