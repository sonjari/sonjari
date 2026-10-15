"""페이지 **첫머리**에서 주 항목 값(판매가·정가·적립)을 뽑는다 — 모델이 아니라 도구가 값을 읽는다.

★ 2026-09-28 헤르메스 대결 T1. 모델은 교보 상세를 열고도 표에 딴 값을 썼다 — 첫머리에 붙은 다른 판 가격
(「국내도서 16,200원 외국도서 23,410원 eBook 12,960원」)이나 추천 띠(1,350자째)에서 집었다. 「쓰는 순간 되돌리기」로
돌려보내도 울린 3판 모두 정답이 0이었다(「확인 불가」로 쓰거나 가격×5% 로 계산). 안내문은 안 먹는다 — 결정론으로 박는다(사고 R).

사이트 지식은 파이썬이 아니라 `recipes/page_values/*.json` 에 적는다(site_recipes 와 같은 생각). 한 필드는 위에서부터
**처음 맞은 규칙만** 쓴다. 못 맞으면 비워 둔다 — **모르면 안 고친다.**
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RECIPE_DIR = Path(__file__).resolve().parents[2] / "recipes" / "page_values"


@dataclass(frozen=True)
class Field:
    field: str
    kind: str  # "money" | "point"
    label: str
    pattern: re.Pattern[str]
    group: int


@dataclass(frozen=True)
class PageValueRecipe:
    name: str
    hosts: tuple[str, ...]
    head_chars: int
    fields: tuple[Field, ...]

    def covers(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return any(host == item or host.endswith("." + item) for item in self.hosts)


def _load(path: Path) -> PageValueRecipe:
    raw = json.loads(path.read_text(encoding="utf-8"))
    fields = tuple(
        Field(
            field=str(item["field"]),
            kind=str(item.get("kind") or "money"),
            label=str(item.get("label") or item["field"]),
            pattern=re.compile(str(item["pattern"])),
            group=int(item.get("group") or 1),
        )
        for item in raw.get("fields") or []
    )
    return PageValueRecipe(
        name=str(raw.get("name") or path.stem),
        hosts=tuple(str(host).lower() for host in raw.get("hosts") or []),
        head_chars=int(raw.get("head_chars") or 900),
        fields=fields,
    )


@lru_cache(maxsize=4)
def load_recipes(directory: str = "") -> tuple[PageValueRecipe, ...]:
    """레시피를 읽는다. 깨진 파일은 **건너뛴다** — 값 레시피 하나 때문에 판을 죽이지 않는다."""
    folder = Path(directory) if directory else RECIPE_DIR
    found: list[PageValueRecipe] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            found.append(_load(path))
        except Exception:  # noqa: BLE001
            continue
    return tuple(found)


def extract(url: str, text: str, *, recipes: tuple[PageValueRecipe, ...] | None = None) -> dict[str, dict[str, Any]]:
    """이 주소·본문에서 뽑은 값. `{"sale_price": {"kind": "money", "label": "판매가", "digits": "16200"}, ...}` — 없으면 빈 dict."""
    for recipe in recipes if recipes is not None else load_recipes():
        if not recipe.covers(url):
            continue
        head = str(text or "")[: recipe.head_chars]
        values: dict[str, dict[str, Any]] = {}
        for item in recipe.fields:
            if item.field in values:
                continue
            match = item.pattern.search(head)
            if not match:
                continue
            digits = match.group(item.group).replace(",", "")
            if digits.isdigit():
                values[item.field] = {"kind": item.kind, "label": item.label, "digits": digits}
        return values
    return {}


def describe(values: dict[str, dict[str, Any]]) -> str:
    """사람·모델이 읽는 한 줄: 「판매가 16,200원 · 정가 18,000원 · 적립 900P」."""
    parts = []
    for value in values.values():
        if value["kind"] == "rate":
            parts.append(f"{value['label']} {int(value['digits'])}%")
            continue
        unit = "P" if value["kind"] == "point" else "원"
        parts.append(f"{value['label']} {int(value['digits']):,}{unit}")
    return " · ".join(parts)
