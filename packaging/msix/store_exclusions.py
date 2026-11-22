"""스토어(MSIX) 포장에서 아직 내보내지 않는 팩을 뺀다.

★ 2026-11-16 대표 결정: 「3D 팩은 이번 판에서 숨긴다」. 개발 PC · 운영(C:) 동기화 · 맥 설치는 그대로 두고
  **스토어 포장 길만** 뺀다(대표 PC 는 3D 를 쓴다).

규칙
- `packs/<id>/pack.json` 에 `"store": false` 가 있으면 포장본의 `Lib/packs/<id>` 를 지운다.
- 그 팩의 도구**만** 적힌 기능 카드(`Lib/capabilities/**/*.md` 머리의 `도구: [...]`)도 지운다.
  카드가 남으면 클로드에게 「설정 › 팩에서 켜라」고 안내하는데 스토어판엔 켤 팩이 없다 — 헛안내가 된다.
- 다른 팩 도구가 하나라도 섞인 카드는 남긴다(그 카드는 다른 팩 몫이기도 하다).

사용: <venv python> store_exclusions.py <포장본 python\\Lib>
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

_TOOLS_LINE = re.compile(r"^도구:\s*\[(?P<body>[^\]]*)\]\s*$", re.MULTILINE)


def card_tools(text: str) -> list[str]:
    """카드 머리(첫 `---` 두 줄 사이)의 `도구: [a, b]` 를 읽는다. 머리가 없으면 빈 목록."""
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    head = text[3:end] if end != -1 else ""
    found = _TOOLS_LINE.search(head)
    if not found:
        return []
    return [name.strip() for name in found.group("body").split(",") if name.strip()]


def hidden_packs(packs_dir: Path) -> dict[str, set[str]]:
    """`"store": false` 인 팩 id → 그 팩의 도구 이름."""
    hidden: dict[str, set[str]] = {}
    for manifest in sorted(packs_dir.glob("*/pack.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("store") is False:
            hidden[str(data.get("id") or manifest.parent.name)] = {str(t) for t in data.get("tools") or ()}
    return hidden


def prune(lib: Path) -> dict[str, list[str]]:
    lib = Path(lib)
    packs_dir = lib / "packs"
    hidden = hidden_packs(packs_dir)
    removed_packs: list[str] = []
    removed_cards: list[str] = []
    hidden_tools = set().union(*hidden.values()) if hidden else set()
    for manifest in sorted(packs_dir.glob("*/pack.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("store") is False:
            shutil.rmtree(manifest.parent)
            removed_packs.append(manifest.parent.name)
    cards_dir = lib / "capabilities"
    if hidden_tools and cards_dir.is_dir():
        for card in sorted(cards_dir.rglob("*.md")):
            tools = card_tools(card.read_text(encoding="utf-8"))
            if tools and set(tools) <= hidden_tools:
                card.unlink()
                removed_cards.append(card.relative_to(cards_dir).as_posix())
        # 카드가 다 빠진 분류 폴더는 같이 지운다(빈 분류가 목록에 남지 않게).
        for folder in sorted((p for p in cards_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
    return {"packs": removed_packs, "cards": removed_cards}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: store_exclusions.py <package python\\Lib>")
        return 2
    lib = Path(argv[1])
    if not (lib / "packs").is_dir():
        print(f"no packs folder under {lib}")
        return 1
    result = prune(lib)
    print(f"store exclusions: packs removed {result['packs']} · cards removed {result['cards']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
