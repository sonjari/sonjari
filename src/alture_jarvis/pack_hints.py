"""이 PC 에 맞는 팩 권하기 — 판정 한 자리 (2026-11-16 · 설계 `docs/설계_팩켜기UX_2026-11-16.ko.md` §4-1).

## 왜

팩 넷은 기본 꺼짐이고 설정 › 팩에서만 켠다. 3ds Max 가 깔린 PC 에서도 애니메이터 팩이 있는 줄 몰라 안 켰다(11-16 대표).
그래서 「이 PC 에 무엇이 깔려 있나」를 보고 맞는 팩을 **한 번** 권한다. 화면 · 클로드 · 시험이 같은 판정을 쓴다(여기 하나).

## 지킬 것

- **켜지 않는다.** 이 모듈은 `set_enabled` 를 부르지 않는다 — 권하기만. 켜는 것은 늘 사람(설정 › 팩 · 팩 켜기 카드).
- **이 PC 안에서만 본다.** 찾기는 이미 있는 함수만 부른다(새 경로를 짐작하지 않는다):
  3ds Max `heavy_apps.installed`(레지스트리) · 블렌더 `animator.blender_bridge.find_blender` · `gen3d.blender.find_blender` ·
  유니티 `UnityTools.installed_editors`(허브 판 폴더) · 뱀부 `gen3d.slicer.find_bambu` ·
  그래픽카드 메모리 `gen3d.memory.gpu_list`(nvidia-smi) · 맥은 `gen3d.memory.unified_total_mib`(sysctl).
  ★ 마법사의 `profile()` 은 쓰지 않는다 — 그 안에서 Ollama 주소(짝지은 본체 PC 일 수 있다)에 묻는다.
- **못 읽은 것은 맞다고 하지 않는다.** 메모리를 못 읽으면 막는 까닭에 「못 읽음」으로 적는다.
- 찾기는 느릴 수 있다(설치 목록 · 폴더 훑기) — 하루 한 번 재고 쥐고 있는다.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: 이 판정이 아는 팩. 사람이 넣은 내용 팩(content)은 권하지 않는다(설계 §7 — 다음 판).
KNOWN_PACKS = ("animator", "game", "gen3d", "video", "genvideo")
#: 설계 §4-1 문턱(GB).
GEN3D_MIN_GB = 8.0
GEN3D_MIN_UNIFIED_GB = 16.0
#: 영상 생성 팩(genvideo) 문턱 — 11-16 RTX 3060 12GB 실측(FastWan 시안 카드 최대 11,764MiB). 영상 읽기 팩(video)은 그래픽카드를 안 쓴다.
GENVIDEO_MIN_GB = 12.0
CACHE_SEC = 24 * 3600

# 신호에 쓰는 프로그램 이름(화면 · 까닭 글에 그대로 나간다).
APP_MAX = "3ds Max"
APP_BLENDER = "Blender"
APP_UNITY = "Unity"
APP_BAMBU = "Bambu Studio"


@dataclass
class Signals:
    """이 PC 에서 본 것. 시험은 이것을 손으로 만들어 판정에 넣는다."""

    os: str = "win"  # "win" · "mac" · "other"
    apps: dict[str, str] = field(default_factory=dict)  # 이름 → 한 줄(판 · 경로)
    #: 그래픽카드 메모리(GB). 윈도우는 가장 큰 엔비디아 카드, 맥은 통합 메모리 전체. 못 읽으면 None.
    gpu_gb: float | None = None
    errors: list[str] = field(default_factory=list)  # 찾다가 터진 것(조용히 빠지지 않게)

    def public(self) -> dict[str, Any]:
        return {"os": self.os, "apps": dict(self.apps), "gpu_gb": self.gpu_gb, "errors": list(self.errors)}


def _gb(value: float | None) -> str:
    return f"{value:g}GB" if value is not None else "?"


def _memory_name(os_name: str) -> str:
    return "통합 메모리" if os_name == "mac" else "그래픽카드 메모리"


def judge(signals: Signals, *, enabled: set[str] | frozenset[str] = frozenset(),
          dismissed: set[str] | frozenset[str] = frozenset(), present: set[str] | None = None) -> list[dict[str, Any]]:
    """팩마다 `{pack, fits, reasons, blockers, enabled, dismissed}`. 순수 함수 — 시험은 가짜 신호로 표를 돈다.

    `fits` 는 「맞는 신호가 하나라도 있고 막는 조건이 없다」. 켜짐 · 무시와 상관없이 판정 그대로 둔다 — 화면이 거른다.
    `present` 를 주면 그 팩만(이 판에 깔린 팩).
    """
    apps = signals.apps
    mem = _memory_name(signals.os)
    out: list[dict[str, Any]] = []
    for pack in KNOWN_PACKS:
        if present is not None and pack not in present:
            continue
        reasons: list[str] = []
        blockers: list[str] = []
        if pack == "animator":
            if APP_MAX in apps:
                reasons.append(f"3ds Max 가 깔려 있음({apps[APP_MAX]})")
            if APP_BLENDER in apps:
                reasons.append(f"블렌더가 깔려 있음({apps[APP_BLENDER]})")
        elif pack == "game":
            if APP_UNITY in apps:
                reasons.append(f"유니티 에디터가 깔려 있음({apps[APP_UNITY]})")
        elif pack == "gen3d":
            if APP_BAMBU in apps:
                reasons.append(f"뱀부 스튜디오가 깔려 있음({apps[APP_BAMBU]})")
            if APP_BLENDER in apps:
                reasons.append(f"블렌더가 깔려 있음({apps[APP_BLENDER]})")
            need = GEN3D_MIN_UNIFIED_GB if signals.os == "mac" else GEN3D_MIN_GB
            if signals.gpu_gb is None:
                blockers.append(f"{mem}를 못 읽음 — 3D 굽기는 {_gb(need)} 이상이 필요")
            elif signals.gpu_gb < need:
                blockers.append(f"{mem} {_gb(signals.gpu_gb)} — 3D 굽기는 {_gb(need)} 이상이 필요")
            else:
                reasons.append(f"{mem} {_gb(signals.gpu_gb)}(3D 굽기 {_gb(need)} 이상)")
        elif pack == "video":
            # 영상 읽기(video_read)는 크롬 탭 · ffmpeg 만 쓴다 — 그래픽카드 기준 없음. 이 PC 에서 볼 신호도 없어 권하지 않는다
            # (gen3d → video 같은 「다음 팩」 길로만 나온다). 11-16 까지 12GB 기준이 여기 잘못 붙어 있었다.
            pass
        elif pack == "genvideo":
            # 영상 생성(sd-cli)은 윈도우 엔비디아 CUDA 판만 있다(맥 Metal 판은 안 쟀다 · tool_gateway 도 gen_video 를 win32 만).
            if signals.os != "win":
                blockers.append("영상 생성은 아직 윈도우 + 엔비디아 그래픽카드에서만 된다(굽는 실행기가 CUDA 판만 있다 · 맥 · 라데온은 안 맞음)")
            elif signals.gpu_gb is None:
                # gpu_list 는 nvidia-smi 로 읽는다 — 라데온 · 인텔 카드만 있는 PC 도 여기로 온다.
                blockers.append(f"엔비디아 {mem}를 못 읽음 — 영상 생성은 엔비디아 {_gb(GENVIDEO_MIN_GB)} 이상이 필요(라데온 · 인텔은 안 맞음)")
            elif signals.gpu_gb < GENVIDEO_MIN_GB:
                blockers.append(f"{mem} {_gb(signals.gpu_gb)} — 영상 생성은 엔비디아 {_gb(GENVIDEO_MIN_GB)} 이상이 필요")
            else:
                reasons.append(f"{mem} {_gb(signals.gpu_gb)}(영상 생성 {_gb(GENVIDEO_MIN_GB)} 이상)")
        out.append({
            "pack": pack, "fits": bool(reasons) and not blockers, "reasons": reasons, "blockers": blockers,
            "enabled": pack in enabled, "dismissed": pack in dismissed,
        })
    return out


# ── 진짜 찾기(이미 있는 함수만) ─────────────────────────────────────────────────


def _os_name() -> str:
    return "win" if sys.platform == "win32" else "mac" if sys.platform == "darwin" else "other"


def _find_max() -> str:
    from . import heavy_apps

    return "설치 목록" if APP_MAX in heavy_apps.installed() else ""


def _find_blender() -> str:
    from .animator.blender_bridge import find_blender as anim_find
    from .gen3d.blender import find_blender as gen_find

    found = gen_find()
    if found.get("found"):
        return f"{found.get('version') or '판 모름'} · {found.get('exe')}"
    exe = anim_find()
    return str(exe or "")


def _find_bambu() -> str:
    from .gen3d.slicer import find_bambu

    exe = find_bambu()
    return str(exe) if exe else ""


def _gpu_gb(os_name: str) -> float | None:
    from .gen3d import memory

    if os_name == "mac":
        total = memory.unified_total_mib()
        return round(total / 1024, 1) if total else None
    cards = memory.gpu_list()
    if not cards:
        return None
    return round(max(int(card.get("total_mib") or 0) for card in cards) / 1024, 1)


def read_signals(*, unity_editors: Callable[[], dict[str, Any]] | None = None,
                 finders: dict[str, Callable[[], str]] | None = None,
                 gpu: Callable[[str], float | None] | None = None, os_name: str | None = None) -> Signals:
    """이 PC 를 읽는다. 하나가 터져도 나머지는 읽는다(터진 것은 `errors` 에)."""
    signals = Signals(os=os_name or _os_name())
    table: dict[str, Callable[[], str]] = {APP_BLENDER: _find_blender, APP_BAMBU: _find_bambu}
    if signals.os == "win":
        table[APP_MAX] = _find_max  # 3ds Max 는 윈도우에만 있다
    if unity_editors is not None:
        def _unity() -> str:
            editors = unity_editors() or {}
            return ", ".join(sorted(editors)[-3:]) if editors else ""
        table[APP_UNITY] = _unity
    table.update(finders or {})
    for name, find in table.items():
        try:
            detail = find()
        except Exception as exc:  # noqa: BLE001 — 하나가 터져도 판정은 나간다
            signals.errors.append(f"{name}: {exc}"[:200])
            continue
        if detail:
            signals.apps[name] = str(detail)[:160]
    try:
        signals.gpu_gb = (gpu or _gpu_gb)(signals.os)
    except Exception as exc:  # noqa: BLE001
        signals.errors.append(f"gpu: {exc}"[:200])
    return signals


class PackHints:
    """판정 + 하루 캐시. 켜고 끄는 일은 하지 않는다(`registry` 는 읽기만)."""

    def __init__(self, registry: Any, *, reader: Callable[[], Signals] | None = None,
                 clock: Callable[[], float] = time.monotonic, ttl_sec: float = CACHE_SEC) -> None:
        self.registry = registry
        self.reader = reader or read_signals
        self.clock = clock
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._signals: Signals | None = None
        self._at = 0.0
        self._measured_at = ""

    def signals(self, *, fresh: bool = False) -> Signals:
        with self._lock:
            if fresh or self._signals is None or self.clock() - self._at > self.ttl_sec:
                self._signals = self.reader()
                self._at = self.clock()
                self._measured_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            return self._signals

    def warm(self) -> None:
        """켤 때 한 번 — 뒤에서 재 둔다(첫 화면이 설치 목록 훑기를 기다리지 않게)."""
        threading.Thread(target=lambda: self._safe_signals(), name="pack-hints-warm", daemon=True).start()

    def _safe_signals(self) -> None:
        try:
            self.signals()
        except Exception:  # noqa: BLE001
            pass

    def hints_if_ready(self) -> dict[str, Any] | None:
        """재 둔 신호가 있을 때만 판정 — 없으면 None(훑기를 기다리지 않는다). 도구 목록 설명처럼 빨라야 하는 자리용."""
        if self._signals is None:
            return None
        return self.hints()

    def hints(self, *, fresh: bool = False) -> dict[str, Any]:
        signals = self.signals(fresh=fresh)
        packs = getattr(self.registry, "packs", {}) or {}
        enabled = {pack_id for pack_id in packs if self.registry.is_enabled(pack_id)}
        rows = judge(signals, enabled=enabled, dismissed=self.registry.hint_dismissed(), present=set(packs))
        for row in rows:
            pack = packs.get(row["pack"])
            row["name"] = getattr(pack, "name", row["pack"])
        return {
            "hints": rows,
            # 화면이 띄울 것: 맞고 · 꺼져 있고 · 무시하지 않은 팩.
            "suggest": [row["pack"] for row in rows if row["fits"] and not row["enabled"] and not row["dismissed"]],
            "signals": signals.public(),
            "measured_at": self._measured_at,
        }


__all__ = ["KNOWN_PACKS", "PackHints", "Signals", "judge", "read_signals"]
