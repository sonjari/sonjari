"""기능 카드(capabilities/) — 카드가 코드와 어긋나지 않게 묶는다(설계 docs/설계_기능카드_2026-11-12.ko.md §4).

- 카드 머리 칸 · 크기 · id 가 경로와 같은지 · 찾는말이 한 · 영 둘 다인지
- 카드가 말하는 도구가 실제로 있는지(없는 도구 금지)
- 카드 폴더가 있는 팩은 그 팩 도구가 전부 어느 카드엔가 있는지(빠짐 금지)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "capabilities"
PACKS = ROOT / "packs"
MAX_BYTES = 4096  # 한글은 글자당 3바이트 — 3KB 는 1,000자 남짓이라 4KB(설계 §3 고침)
REQUIRED = ("id", "분류", "제목", "찾는말", "도구", "맡기기", "필요", "확인일")
SECTIONS = ("## 되는 것", "## 이렇게 맡기세요", "## 끝났는지 보는 법", "## 잰 것")


def _cards() -> list[Path]:
    return sorted(p for p in CARDS.rglob("*.md") if p.name != "README.md")


def _head(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path}: 머리(---) 가 없다"
    out: dict[str, object] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            out[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = value
    return out


def _pack_tools() -> dict[str, set[str]]:
    return {
        p.parent.name: set(json.loads(p.read_text(encoding="utf-8")).get("tools") or [])
        for p in PACKS.glob("*/pack.json")
    }


def test_cards_exist() -> None:
    assert _cards(), "capabilities/ 에 카드가 하나도 없다"


def test_card_shape() -> None:
    for path in _cards():
        head = _head(path)
        for key in REQUIRED:
            assert head.get(key), f"{path.name}: 머리 칸 「{key}」 가 비었다"
        rel = path.relative_to(CARDS).with_suffix("").as_posix()
        assert head["id"] == rel, f"{path.name}: id {head['id']} ≠ 경로 {rel}"
        assert head["분류"] == rel.split("/")[0], f"{path.name}: 분류가 폴더와 다르다"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(head["확인일"])), f"{path.name}: 확인일 꼴"
        assert head["맡기기"] in {"직접", "맡기기", "둘 다"}, f"{path.name}: 맡기기 값"
        words = head["찾는말"]
        assert any(re.search(r"[가-힣]", w) for w in words), f"{path.name}: 찾는말에 한국어가 없다"
        assert any(re.search(r"[A-Za-z]", w) and not re.search(r"[가-힣]", w) for w in words), f"{path.name}: 찾는말에 영어가 없다"
        size = path.stat().st_size
        assert size <= MAX_BYTES, f"{path.name}: {size}B > {MAX_BYTES}B — 카드를 나눠라"
        body = path.read_text(encoding="utf-8")
        for section in SECTIONS:
            assert section in body, f"{path.name}: 「{section}」 절이 없다"


def test_card_tools_are_real() -> None:
    known = set().union(*_pack_tools().values())
    for path in _cards():
        for tool in _head(path)["도구"]:
            # 팩 밖(런타임 · 맡기기 문) 도구는 그 분류 카드가 생길 때 여기에 더한다.
            assert tool in known, f"{path.name}: 없는 도구 {tool}"


def test_every_pack_tool_has_a_card() -> None:
    carded: dict[str, set[str]] = {}
    for path in _cards():
        head = _head(path)
        carded.setdefault(str(head["분류"]), set()).update(head["도구"])
    for pack, tools in _pack_tools().items():
        if not (CARDS / pack).is_dir():
            continue  # 아직 카드를 안 만든 분류 — 만들기 시작하면 전부 채워야 한다
        missing = tools - carded.get(pack, set())
        assert not missing, f"{pack} 팩 도구가 카드에 없다: {sorted(missing)}"
