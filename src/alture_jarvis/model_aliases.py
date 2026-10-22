"""모델 별명 표 — 「똑똑한」 · 「빠른」 같은 짧은 이름 → Ollama 태그 (2026-10-18).

## 왜

디스코드에서 「@빠른 오늘 날씨」처럼 판 하나만 다른 모델로 돌리고(`messaging.bridge`), `/모델` 로 그 대화의 모델을 고른다.
사람은 태그(`qwen3.5:9b-q4_K_M`)를 외우지 않는다. 그래서 짧은 별명 표를 데이터 폴더에 둔다(비밀 없음).

- 처음 볼 때 표가 없으면 이 PC 에 깔린 모델(`/api/tags`, **읽기만** — 모델을 올리거나 내리지 않는다)에서 둘쯤 채운다:
  운영 대화 모델 = 「똑똑한」, 깔린 것 중 그보다 작은 가장 작은 대화 모델 = 「빠른」(없으면 만들지 않는다).
  채운 뒤에는 `seeded` 를 적어 둔다 — 사람이 다 지운 표를 다시 채우지 않는다.
- 별명 규칙: 공백 없는 1~12자, 한글 · 영문 · 숫자.
- 판 하나에 거는 자리는 `/v1/chat` 의 `model_alias` → 본체가 이 표로 태그를 풀어 `runtime._chat_job` 이
  `OllamaClient.pin_model` 로 그 판 동안만 묶는다. 바깥이 태그를 직접 넘길 길은 열지 않는다(표에 있는 것만).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

ALIASES_FILE = "model_aliases.json"
ALIAS_RE = re.compile(r"^[0-9A-Za-z가-힣]{1,12}$")
MAX_ALIASES = 20
#: 대화 모델이 아닌 것 — 글을 숫자로 바꾸는 모델은 「빠른」 후보가 아니다.
_NOT_CHAT = ("embed", "bge-", "minilm", "rerank", "nomic-bert")

SMART = {"ko": ("똑똑한", "PC 에서 쓰는 대화 모델"), "en": ("smart", "The chat model this PC uses")}
FAST = {"ko": ("빠른", "깔린 것 중 가장 작은 모델 — 빠르지만 덜 꼼꼼합니다"),
        "en": ("fast", "The smallest installed model — quicker but less thorough")}


def _identity(tag: Any) -> str:
    value = str(tag or "").strip().casefold()
    return value[:-7] if value.endswith(":latest") else value


def same_model(left: Any, right: Any) -> bool:
    return bool(_identity(left)) and _identity(left) == _identity(right)


def valid_alias(alias: str) -> bool:
    return bool(ALIAS_RE.match(str(alias or "")))


def clean_items(items: Any) -> list[dict[str, str]]:
    """사람이 보낸 표를 검사한다. 틀리면 ValueError(까닭 코드)."""
    if not isinstance(items, list):
        raise ValueError("aliases_must_be_a_list")
    if len(items) > MAX_ALIASES:
        raise ValueError("too_many_aliases")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("alias_must_be_an_object")
        alias = str(item.get("alias") or "").strip()
        tag = str(item.get("tag") or "").strip()
        note = " ".join(str(item.get("note") or "").split())[:120]
        if not valid_alias(alias):
            raise ValueError("invalid_alias")
        if not tag or len(tag) > 200 or any(ch.isspace() for ch in tag):
            raise ValueError("invalid_tag")
        if alias.casefold() in seen:
            raise ValueError("duplicate_alias")
        seen.add(alias.casefold())
        out.append({"alias": alias, "tag": tag, "note": note})
    return out


def find(items: list[dict[str, str]], alias: str) -> dict[str, str] | None:
    wanted = str(alias or "").strip().casefold()
    return next((item for item in items if item["alias"].casefold() == wanted), None) if wanted else None


def split_prefix(text: str, aliases: list[str]) -> tuple[str, str]:
    """「@별명 할 일」 → (별명, 할 일). 표에 없는 `@무엇` 이면 ("", 원래 글) — 건드리지 않는다."""
    body = str(text or "")
    match = _PREFIX.match(body)
    if not match:
        return "", body
    wanted = match.group(1).casefold()
    for alias in aliases:
        if alias.casefold() == wanted:
            return alias, match.group(2).strip()
    return "", body


_PREFIX = re.compile(r"\s*@([^\s@<>]+)(?:\s+|$)(.*)", re.S)


#: 그림 읽는 부속(mmproj) — 모델처럼 목록에 오르지만 혼자서는 말을 못 한다.
_NOT_A_MODEL = ("mmproj", "projector")
#: 「빠른」으로 고를 바닥 — 이보다 작은 모델은 일 판에서 너무 자주 틀린다(10-13 꾸러미: 4B 1/9 · 9B 3/9 · 27B 9/9).
_FAST_FLOOR_BILLIONS = 7.0


def _billions(model: dict[str, Any]) -> float:
    """`details.parameter_size`(예: "9.0B", "566.70M")를 십억 단위로. 모르면 0."""
    raw = str((model.get("details") or {}).get("parameter_size") or "").strip().upper()
    try:
        if raw.endswith("B"):
            return float(raw[:-1])
        if raw.endswith("M"):
            return float(raw[:-1]) / 1000
    except ValueError:
        pass
    return 0.0


def _smallest_chat_model(installed: list[dict[str, Any]], chat_model: str) -> str:
    """「빠른」 후보 — PC 대화 모델보다 작은 대화 모델 중, 7B 이상에서 가장 작은 것(없으면 그 아래에서 가장 큰 것).

    ★ 2026-10-18 첫 운영: 파일 크기만 보고 골랐더니 그림 부속(mmproj 1.7GB)이 「빠른」이 됐다 — 부속은 모델이 아니다.
      부속을 빼면 4B 가 남는데, 4B 는 조사 판에서 너무 자주 틀린다. 그래서 바닥을 둔다.
    """
    chat_size = next((int(m.get("size") or 0) for m in installed if same_model(m.get("name") or m.get("model"), chat_model)), 0)
    candidates = []
    for model in installed:
        name = str(model.get("name") or model.get("model") or "").strip()
        family = str((model.get("details") or {}).get("family") or "").casefold()
        size = int(model.get("size") or 0)
        if not name or size <= 0 or same_model(name, chat_model):
            continue
        lowered = name.casefold()
        if any(word in lowered for word in _NOT_CHAT + _NOT_A_MODEL) or "bert" in family or "clip" in family:
            continue
        if chat_size and size >= chat_size:
            continue
        candidates.append((size, _billions(model), name))
    if not candidates:
        return ""
    floor = [row for row in candidates if row[1] >= _FAST_FLOOR_BILLIONS]
    if floor:
        return min(floor)[2]
    known = [row for row in candidates if row[1] > 0]
    if known:
        return max(known, key=lambda row: (row[1], row[0]))[2]
    return min(candidates)[2]  # 크기(매개변수 수)를 모르면 예전처럼 파일이 가장 작은 것


def default_items(chat_model: str, installed: list[dict[str, Any]], lang: str = "ko") -> list[dict[str, str]]:
    lang = "en" if lang == "en" else "ko"
    items: list[dict[str, str]] = []
    if chat_model:
        items.append({"alias": SMART[lang][0], "tag": chat_model, "note": SMART[lang][1]})
    small = _smallest_chat_model(installed, chat_model)
    if small:
        items.append({"alias": FAST[lang][0], "tag": small, "note": FAST[lang][1]})
    return items


def _installed_from_ollama(base_url: str) -> list[dict[str, Any]] | None:
    """`/api/tags` — 깔린 목록을 **읽기만** 한다. 못 물으면 None."""
    import httpx

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=3.0)
        response.raise_for_status()
        models = response.json().get("models")
    except Exception:  # noqa: BLE001
        return None
    return [m for m in models if isinstance(m, dict)] if isinstance(models, list) else None


class ModelAliasBook:
    """데이터 폴더의 별명 표 하나. 스레드 안전."""

    def __init__(self, config: Any, *, installed: Callable[[], list[dict[str, Any]] | None] | None = None,
                 resident: Callable[[], list[str]] | None = None, lang: Callable[[], str] | None = None) -> None:
        self.config = config
        self._installed = installed or (lambda: _installed_from_ollama(str(config.ollama_base_url)))
        self._resident = resident
        self._lang = lang
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return Path(self.config.data_dir) / ALIASES_FILE

    def _ui_lang(self) -> str:
        if self._lang is not None:
            return self._lang()
        try:
            from . import ui_i18n

            return ui_i18n.lang()
        except Exception:  # noqa: BLE001
            return "ko"

    def _read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, items: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"seeded": True, "aliases": items}, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def items(self) -> list[dict[str, str]]:
        with self._lock:
            data = self._read()
            if data is not None and data.get("seeded"):
                try:
                    return clean_items(data.get("aliases") or [])
                except ValueError:
                    return []
            chat_model = str(self.config.model_for("chat") or "").strip()
            installed = self._installed()
            items = default_items(chat_model, installed or [], self._ui_lang())
            if installed is not None:
                # 깔린 목록을 봤을 때만 「채웠다」고 적는다 — Ollama 가 아직 안 떴으면 다음에 다시 채워 본다.
                self._write(items)
            return items

    def resolve(self, alias: str) -> str:
        found = find(self.items(), alias)
        return found["tag"] if found else ""

    def replace(self, items: Any) -> list[dict[str, str]]:
        cleaned = clean_items(items)
        with self._lock:
            self._write(cleaned)
        return cleaned

    def view(self) -> dict[str, Any]:
        items = self.items()
        resident: list[str] = []
        if self._resident is not None:
            try:
                resident = list(self._resident() or [])
            except Exception:  # noqa: BLE001
                resident = []
        return {
            "pc_model": str(self.config.model_for("chat") or ""),
            "aliases": [{**item, "loaded": any(same_model(item["tag"], name) for name in resident)} for item in items],
        }
