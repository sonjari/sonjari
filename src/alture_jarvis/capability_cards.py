"""기능 카드(`capabilities/`) — 부모 에이전트가 손자리 기능을 찾는 문서 (설계 docs/설계_기능카드_2026-11-12.ko.md).

- `search(query)` : 파일을 못 뒤지는 부모(클로드 앱 채팅 등)를 위해 `sonjari_guide(query=…)` 가 부른다.
  낱말 맞추기만 한다(찾는말 > 제목 > 본문) — 모델 · 임베딩 없음, 결정론 · 오프라인. 없으면 「카드 없음」.
- `install_cards(dest)` : 손님 PC 의 스킬 폴더 옆(`~/.claude/skills/sonjari-guide/cards/` · `~/.codex/sonjari-cards/`)에
  카드를 복사한다. grep 되는 부모는 거기서 필요할 때만 읽는다(부모 기본 입력을 늘리지 않는다 — 09-23 결정).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

__all__ = ["Card", "cards_dir", "load_cards", "search", "render_search", "install_cards", "remove_cards", "MARK_FILE"]

#: 우리가 깐 카드 폴더라는 표시 — 이 파일이 있는 폴더만 지우고 다시 쓴다(남의 폴더는 건드리지 않는다).
MARK_FILE = ".sonjari-cards"
_JOSA = ("으로", "에서", "에게", "까지", "부터", "에", "을", "를", "이", "가", "은", "는", "로", "도", "의", "와", "과", "만")


def cards_dir() -> Path:
    """저장소 · 패키지 모두 `src/alture_jarvis` 의 두 단계 위에 `capabilities/` 가 있다(packs 와 같은 자리)."""
    from .config import setting

    env = setting("JARVIS_CAPABILITIES_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "capabilities"


@dataclass
class Card:
    id: str
    group: str
    title: str
    words: list[str]
    tools: list[str]
    needs: list[str]
    text: str
    path: Path
    head: dict[str, object] = field(default_factory=dict)


def _parse_head(text: str) -> dict[str, object]:
    match = re.match(r"^﻿?---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        return {}
    out: dict[str, object] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            out[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            out[key.strip()] = value
    return out


def load_cards(directory: Path | None = None) -> list[Card]:
    root = Path(directory) if directory else cards_dir()
    cards: list[Card] = []
    if not root.is_dir():
        return cards
    for path in sorted(root.rglob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        head = _parse_head(text)
        if not head.get("id"):
            continue
        cards.append(Card(
            id=str(head["id"]), group=str(head.get("분류") or ""), title=str(head.get("제목") or ""),
            words=list(head.get("찾는말") or []), tools=list(head.get("도구") or []),
            needs=list(head.get("필요") or []), text=text, path=path, head=head,
        ))
    return cards


def _tokens(query: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[\s,·/?!.]+", query.lower()):
        token = raw.strip("「」\"'()[]")
        if not token:
            continue
        for josa in _JOSA:  # 「참조칸에」 → 「참조칸」 — 한국어 조사를 한 번만 뗀다
            if len(token) > len(josa) + 1 and token.endswith(josa) and re.search(r"[가-힣]$", token):
                token = token[: -len(josa)]
                break
        if len(token) >= 2 or re.search(r"[가-힣]", token):
            out.append(token)
    return out


def _pieces(text: str) -> list[str]:
    return [p for p in re.split(r"[\s,·/()「」\[\]—\-_.]+", text.lower()) if p]


def _piece_hit(token: str, pieces: list[str]) -> bool:
    """낱말 조각의 **앞부분**만 맞춘다. 가운데 글자로 걸면 「레이어」가 「플레이어」에 걸린다(11-12 시험에서 잡힘)."""
    return any(p.startswith(token) or (len(p) >= 2 and token.startswith(p)) for p in pieces)


def _score(card: Card, query: str, tokens: list[str]) -> tuple[int, int]:
    """(머리 점수, 본문 점수). 머리(찾는말 · 제목 · 도구 이름)에 하나도 안 걸리면 고르지 않는다 — 본문 한 낱말로 엉뚱한 카드를 내지 않게."""
    words = [w.lower() for w in card.words]
    word_pieces = [p for w in words for p in _pieces(w)]
    title_pieces = _pieces(card.title)
    tool_pieces = [p for t in card.tools for p in _pieces(t)]
    body_pieces = _pieces(card.text)
    head = 0
    q = query.lower().strip()
    if q and any(q == w for w in words):
        head += 20
    hit = 0
    for token in tokens:
        if any(token == w for w in words) or token in word_pieces:
            head += 6
        elif _piece_hit(token, word_pieces):
            head += 4
        if _piece_hit(token, title_pieces):
            head += 3
        if _piece_hit(token, tool_pieces):
            head += 3
        if _piece_hit(token, body_pieces):
            hit += 1
    return head, hit


def search(query: str, cards: Iterable[Card] | None = None, limit: int = 3) -> tuple[list[Card], list[str]]:
    """맞는 카드 위 `limit` 장과 그 밖에 걸린 id 들."""
    pool = list(cards) if cards is not None else load_cards()
    tokens = _tokens(query)
    scored = []
    for card in pool:
        head, body = _score(card, query, tokens)
        if head > 0:
            scored.append((head * 10 + body, card))
    scored.sort(key=lambda row: (-row[0], row[1].id))
    picked = [card for _, card in scored[:limit]]
    more = [card.id for _, card in scored[limit:limit + 10]]
    return picked, more


def render_search(query: str, *, enabled_packs: set[str] | None = None, lang: str = "ko",
                  cards: Iterable[Card] | None = None, limit: int = 3) -> str:
    pool = list(cards) if cards is not None else load_cards()
    picked, more = search(query, pool, limit)
    if not pool:
        return ("Capability cards are not installed with this build." if lang == "en"
                else "이 판에는 기능 카드가 없습니다.")
    if not picked:
        if lang == "en":
            return (f"No capability card for \"{query}\". Do not assume Sonjari can do it — hand it off with sonjari_task "
                    "and read model_hint in the result, or ask the user.")
        return (f"「{query}」 에 맞는 기능 카드가 없습니다. 된다고 가정하지 말고, sonjari_task 로 맡겨 결과의 model_hint 를 보거나 "
                "사용자에게 물으세요.")
    parts: list[str] = []
    for card in picked:
        note = ""
        if enabled_packs is not None and card.group in _pack_groups(pool) and card.group not in enabled_packs:
            note = (f"> This PC has the `{card.group}` pack turned off. The user turns it on in Sonjari Settings › Packs — do not turn it on yourself.\n\n"
                    if lang == "en" else
                    f"> 지금 이 PC 에선 `{card.group}` 팩이 꺼져 있습니다. 사용자가 손자리 설정 › 팩에서 켜야 합니다 — 대신 켜지 마세요.\n\n")
        parts.append(note + card.text.strip())
    tail = ""
    if more:
        tail = ("\n\n---\nAlso matched: " if lang == "en" else "\n\n---\n더 걸린 카드: ") + ", ".join(more)
    return "\n\n---\n\n".join(parts) + tail


def _pack_groups(pool: list[Card]) -> set[str]:
    """팩으로 켜고 끄는 분류(카드 머리 `필요` 에 「팩 켜기」가 있는 분류)."""
    return {card.group for card in pool if any("팩 켜기" in need for need in card.needs)}


def install_cards(dest: Path, source: Path | None = None) -> dict[str, object]:
    """카드 폴더를 `dest` 로 통째로 맞춘다. `dest` 가 있는데 우리 표시가 없으면 남의 폴더라 덮지 않는다."""
    src = Path(source) if source else cards_dir()
    dest = Path(dest)
    if not src.is_dir():
        return {"ok": False, "error": "no_cards_in_build"}
    if dest.exists() and not (dest / MARK_FILE).exists():
        return {"ok": False, "error": "foreign_folder_exists", "path": str(dest)}
    tmp = dest.with_name(dest.name + ".tmp-sonjari")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # BOM 을 붙인다 — 코덱스는 PowerShell 5.1 로 읽어 BOM 없는 한글을 깨뜨린다(guide_skill._write_note 주석 · 사고 J).
    for md in tmp.rglob("*.md"):
        md.write_text(md.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    (tmp / MARK_FILE).write_text("손자리가 깐 기능 카드 — 앱이 켜질 때 이 판으로 다시 맞춥니다. 고친 것은 사라집니다.\n",
                                 encoding="utf-8")
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return {"ok": True, "path": str(dest), "count": len(load_cards(dest))}


def remove_cards(dest: Path) -> bool:
    dest = Path(dest)
    if dest.is_dir() and (dest / MARK_FILE).exists():
        shutil.rmtree(dest, ignore_errors=True)
        return True
    return False
