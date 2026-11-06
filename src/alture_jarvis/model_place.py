"""모델 자리 — 이번엔 어느 그래픽카드로 돌릴까: 이 맥(이 PC) / 집 PC (설계_짝짓기_모델자리_2026-11-03 §3-1 · §4-4 · 순서 1).

대표(11-03 맥미니): 「맥판에서는 설정도 못 하고 모델도 못 바꾼다」. 위성(`JARVIS_ROLE=satellite`)을 **이 기기의 정체**로 만들어
모델 화면을 통째로 숨겼다. 사람에게 이것은 「이번엔 어디서 돌릴까」라는 **선택**이다. 그래서 둘을 나눈다:

- **역할**(예약 메일 · 카메라 · 상자 끄기)은 그대로 `.env` 의 `JARVIS_ROLE` — 기동 때 정해진다(두 대가 같은 메일을 두 번 보내지 않게).
- **모델 자리**는 여기 — `data/model_place.json`. 바꾸면 **다시 켜지 않고** 살아 있는 설정에 얹어 다음 모델 호출부터 바뀐다
  (`ollama.py` 는 부를 때마다 `config.ollama_base_url` · `config.model_roles` 를 읽는다).
- 「집 PC」에서 모델을 고르면 **이 기기가 쓸 모델만** 적는다. 집 PC 의 사용자 선택은 건드리지 않는다(§3-1 표 마지막 줄).
- 「이 맥」은 이 기기의 선택(`model_selection.json` · 마법사 · 설정의 모델 고르기)을 그대로 쓴다.

집 PC 를 아는 길은 지금은 `.env` 의 위성 주소 하나다. 짝짓기(순서 2)가 들어오면 그 자리를 짝지은 기기가 대신한다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

FILE_NAME = "model_place.json"
LOCAL_OLLAMA = "http://127.0.0.1:11434"
PLACES = ("this_pc", "home_pc")
_LOCK = threading.Lock()


def _path(data_dir: Path | str) -> Path:
    return Path(data_dir) / FILE_NAME


def read(data_dir: Path | str) -> dict[str, Any]:
    try:
        raw = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(data_dir: Path | str, data: dict[str, Any]) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def remember_home(config: Any) -> None:
    """집 PC 주소 · 모델을 따로 쥐어 둔다 — 자리를 이 맥으로 바꾸면 `ollama_base_url` · `model_roles` 를 덮기 때문이다.

    집 PC 를 아는 길은 둘이다(앞 것이 이긴다):
      1. **짝지은 집 PC**(`pairing.read_home`) — 모델 호출은 이 기기 손자리의 `/v1/home-llm` 으로 보내고, 거기서 기기 토큰을 붙여
         집 PC 손자리로 넘긴다(집 PC Ollama 를 네트워크에 열지 않는다 · 설계 §4-2).
      2. **옛 위성 설치본**(`.env` 의 `JARVIS_ROLE=satellite` + 집 PC Ollama 주소) — 짝지을 때까지 그대로 둔다.
    옛 위성 값은 **처음 한 번** 덮이기 전의 설정에서 쥔다(`legacy_home`) — 짝을 끊으면 그리로 돌아간다.
    """
    if getattr(config, "legacy_home", None) is None:
        satellite = str(getattr(config, "jarvis_role", "")).lower() == "satellite"
        url = str(getattr(config, "ollama_base_url", "") or "").rstrip("/") if satellite else ""
        if url and url.split("//")[-1].split(":")[0] in {"127.0.0.1", "localhost", "::1"}:
            url = ""
        config.legacy_home = (url, dict(getattr(config, "model_roles", None) or {}), int(getattr(config, "ollama_num_ctx", 0) or 0))
    if getattr(config, "home_ollama_url", None) is not None:
        return
    from . import pairing

    paired = pairing.read_home(config.data_dir)
    if paired.get("address"):
        config.home_ollama_url = f"http://127.0.0.1:{int(getattr(config, 'port', 8091) or 8091)}/v1/home-llm"
        model = str(paired.get("home_model") or "")
        config.home_model_roles = {"chat": model, "code": model} if model else {}
        config.home_num_ctx = int(paired.get("home_ctx") or 0) or config.legacy_home[2]
        return
    config.home_ollama_url, roles, config.home_num_ctx = config.legacy_home
    config.home_model_roles = dict(roles)


def forget_cache(config: Any) -> None:
    """짝짓기 · 끊기 뒤 — 쥐어 둔 집 PC 값을 버리고 다음에 다시 쥔다(옛 위성 값은 `legacy_home` 에 남아 있다)."""
    config.home_ollama_url = None


def home_url(config: Any) -> str:
    remember_home(config)
    return str(getattr(config, "home_ollama_url", "") or "")


def current(config: Any) -> str:
    """지금 자리. 집 PC 를 모르면 늘 이 기기다. 파일이 없으면 위성 설치본은 예전처럼 집 PC."""
    if not home_url(config):
        return "this_pc"
    place = str(read(config.data_dir).get("place") or "")
    return place if place in PLACES else "home_pc"


def apply(config: Any) -> str:
    """지금 자리를 설정에 얹는다(기동 때와 바꿀 때 같은 함수). 얹은 자리를 돌려준다."""
    remember_home(config)
    place = current(config)
    saved = read(config.data_dir)
    if place == "home_pc":
        config.ollama_base_url = home_url(config)
        roles = dict(config.home_model_roles)
        model = str(saved.get("home_model") or "").strip()
        if model:
            # 이 기기가 집 PC 에서 고른 모델 — 대화와, 대화를 따라가던 역할만 바꾼다.
            old_chat = str(roles.get("chat") or "")
            for role, tag in list(roles.items()):
                if tag == old_chat:
                    roles[role] = model
            roles["chat"] = model
        config.model_roles = roles
        ctx = int(saved.get("home_ctx") or 0) or config.home_num_ctx
        if ctx:
            config.ollama_num_ctx = ctx
        return place
    config.ollama_base_url = LOCAL_OLLAMA
    # 이 기기의 선택. 아직 안 골랐으면 집 PC 모델 이름이 남지 않게 비운다 — 화면이 「이 맥에 고른 모델이 없습니다」를 말한다.
    config.model_roles = {}
    from .model_setup import apply_selection_to_config, follow_chat_with_code

    apply_selection_to_config(config)
    follow_chat_with_code(config)
    return place


def set_place(config: Any, place: str, *, extra_live: list[Any] | None = None) -> dict[str, Any]:
    """자리를 바꾼다 — 파일에 적고 살아 있는 설정에 얹는다. 백엔드를 다시 켜지 않는다."""
    if place not in PLACES:
        return {"ok": False, "error": "unknown_place"}
    if place == "home_pc" and not home_url(config):
        return {"ok": False, "error": "no_home_pc"}
    with _LOCK:
        data = read(config.data_dir)
        data["place"] = place
        _write(config.data_dir, data)
        apply(config)
        for holder in extra_live or []:
            if hasattr(holder, "base_url"):
                holder.base_url = config.ollama_base_url
    return {"ok": True, **view(config)}


def set_home_model(config: Any, tag: str, num_ctx: int = 0) -> dict[str, Any]:
    """집 PC 에 깔린 모델 가운데 **이 기기가 쓸 것**을 고른다. 집 PC 사용자의 선택은 바꾸지 않는다."""
    tag = str(tag or "").strip()
    if len(tag) > 300:
        return {"ok": False, "error": "bad_tag"}
    if not home_url(config):
        return {"ok": False, "error": "no_home_pc"}
    with _LOCK:
        data = read(config.data_dir)
        if tag:
            data["home_model"] = tag
            if num_ctx:
                data["home_ctx"] = int(num_ctx)
        else:
            # 빈 값 = 집 PC 가 쓰는 모델을 그대로 따라간다(이 기기에서 고른 것을 지운다).
            data.pop("home_model", None)
            data.pop("home_ctx", None)
        _write(config.data_dir, data)
        if current(config) == "home_pc":
            apply(config)
    return {"ok": True, **view(config)}


def view(config: Any) -> dict[str, Any]:
    from . import pairing

    saved = read(config.data_dir)
    home = home_url(config)
    paired = pairing.read_home(config.data_dir)
    host = str(paired.get("name") or "") if paired else (home.split("//")[-1].split(":")[0] if home else "")
    return {
        "paired": bool(paired),
        "home_gpu": str(paired.get("gpu") or "") if paired else "",
        "place": current(config),
        "home_known": bool(home),
        "home_host": host,
        "home_model": str(saved.get("home_model") or "") or str((getattr(config, "home_model_roles", {}) or {}).get("chat") or ""),
        "home_model_chosen_here": bool(saved.get("home_model")),
        "chat_model": str((config.model_roles or {}).get("chat") or ""),
        "num_ctx": int(getattr(config, "ollama_num_ctx", 0) or 0),
    }


# ── 집 PC 모델 목록 거르기 (2026-11-04 대표 맥미니 스크린샷) ─────────────────────────────────────────────
# 집 PC 목록에 대화 모델이 아닌 것이 섞여 「고르면 안 되는 것」을 고를 수 있었다:
#   bge-m3(임베딩 · 1.2GB) · …:mmproj-…(그림 읽는 부품 · 1.9GB) · sonjari-probe-…:test(시험용 별칭).
# 그리고 집 PC 가 지금 쓰는 모델이 어느 줄인지 안 보였다 → home_default 로 표시한다.
_NOT_CHAT_FAMILIES = {"bert", "nomic-bert", "xlm-roberta", "clip"}


def is_chat_model(tag: str, family: str = "") -> bool:
    """대화에 쓸 수 있는 모델인가 — 임베딩 · 그림 읽는 부품(mmproj) · 시험용 별칭은 아니다."""
    name = str(tag or "").lower()
    if not name:
        return False
    if "mmproj" in name or "embed" in name or name.startswith(("bge-", "sonjari-probe-")):
        return False
    return str(family or "").lower() not in _NOT_CHAT_FAMILIES


def home_rows(tags: list[dict[str, Any]], home_default: str = "") -> list[dict[str, Any]]:
    """집 PC Ollama 의 /api/tags → 이 기기가 고를 수 있는 줄. 집 PC 기본 모델이 맨 위, 나머지는 이름순."""
    rows = []
    for m in tags:
        details = m.get("details") or {}
        tag = str(m.get("name") or "")
        if not is_chat_model(tag, str(details.get("family") or "")):
            continue
        rows.append({"tag": tag, "gb": round(float(m.get("size") or 0) / 1e9, 1),
                     "family": str(details.get("family") or ""),
                     "params": str(details.get("parameter_size") or ""),
                     "quant": str(details.get("quantization_level") or ""),
                     "home_default": bool(home_default) and tag == home_default})
    return sorted(rows, key=lambda r: (not r["home_default"], r["tag"].lower()))


def home_default_model(config: Any) -> str:
    """집 PC 가 쓰는 대화 모델 — 짝지을 때 받은 값(없으면 옛 위성 설정의 대화 모델)."""
    from . import pairing

    paired = pairing.read_home(getattr(config, "data_dir", "")) or {}
    return str(paired.get("home_model") or (getattr(config, "home_model_roles", {}) or {}).get("chat") or "")

