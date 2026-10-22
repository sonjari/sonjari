"""업데이트 뒤 「바뀐 것 · 이미 되는 것」 (2026-10-20 대표).

## 왜

대표(10-20): 「기능 추가나 개선은 사용자가 알아야 되는데 지금은 아예 모른다 · 디스코드처럼 되는 게 많은데 한번 알려 주는 게
필요하다」. 판마다 스토어 「새로운 기능」 글을 한 · 영으로 쓰고 있었지만, 그 글은 스토어 페이지에만 있었다 — 앱을 켠 사람은 못 봤다.

## 무엇을

- 글은 **패키지 안 한 곳**(`whats_new/<판 번호>.json` · `ko`/`en` · `changes`/`tour`)에 둔다. 화면 한 줄 · 대화 답이 같은 글을 쓴다.
- 판 번호는 스토어에 올린 **패키지 번호**(`msix.package_version`)다. 패키지 밖(개발)에서는 빈 값이라 아무것도 안 띄운다.
- 「이 판을 봤다」는 데이터 폴더의 `whats_new_seen.json` 에 적는다.
- ★ 기록이 없는 사람을 무조건 「새로 깐 사람」으로 치면 **이 기능이 처음 들어간 판에서** 0.4.25.0 에서 넘어오는 사람이 한 줄을 못 본다.
  그래서 첫 설정(`setup_state.completed`)을 마친 사람이면 지금 판을 보여 주고, 아직 안 마친 사람(막 깐 사람)이면 조용히 「봤다」로 적는다.

## 슬라이드 (2026-10-21 대표 「그림에 글을 넣어 피피티마냥 한눈에 알아보고 이쁘게」)

0.4.29.0 의 「바뀐 것」 목록은 22줄이었다 — 아무도 안 읽는다. 판마다 `slides`(3~4장)를 더 둔다. 한 장은
`title` · `body` · `try`(없어도 됨) · `visual`(없어도 됨)이고, `visual` 은 둘 중 하나다.

- `{"kind": "stat", "label", "before", "after", "unit", "basis"}` — 화면이 막대로 그린다. **숫자에는 잰 조건(`basis`)이 꼭 붙는다.**
- `{"kind": "image", "src", "alt"}` — `ui/public/<src>` 의 실제 손자리 화면. 그린 가짜 화면은 넣지 않는다.

`slides` 가 없는 옛 판(0.4.27~29)은 화면이 지금처럼 목록으로 펼친다. 긴 목록(`changes` · `tour`)은 그대로 두고 마지막 장 뒤에 접어서 보인다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NOTES_DIR = Path(__file__).with_name("whats_new")
SEEN_NAME = "whats_new_seen.json"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _visual(raw: Any) -> dict[str, Any] | None:
    """장 위쪽의 그림 · 막대. 칸이 모자라면 버린다 — 잰 조건 없는 숫자 · 주소가 이상한 그림은 화면에 안 나간다."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind == "stat":
        before, after = _number(raw.get("before")), _number(raw.get("after"))
        label, basis = str(raw.get("label") or "").strip(), str(raw.get("basis") or "").strip()
        if before is None or after is None or before <= 0 or after < 0 or not label or not basis:
            return None
        return {"kind": "stat", "label": label, "before": before, "after": after,
                "unit": str(raw.get("unit") or "").strip(), "basis": basis}
    if kind == "image":
        src = str(raw.get("src") or "").strip()
        if not src.startswith("whats_new/") or ".." in src or "\\" in src or ":" in src:
            return None
        return {"kind": "image", "src": src, "alt": str(raw.get("alt") or "").strip()}
    return None


def _slides(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    slides: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title, body = str(item.get("title") or "").strip(), str(item.get("body") or "").strip()
        if not title or not body:
            continue
        slide: dict[str, Any] = {"title": title, "body": body}
        tip = str(item.get("try") or "").strip()
        if tip:
            slide["try"] = tip
        visual = _visual(item.get("visual"))
        if visual:
            slide["visual"] = visual
        slides.append(slide)
    return slides


def notes_for(version: str, lang: str = "ko") -> dict[str, Any] | None:
    """그 판의 글 — `{"changes", "tour", "slides"}`. 없으면 None. 영어가 비었으면 한국어로(슬라이드도 같다)."""
    version = str(version or "").strip()
    if not version or "/" in version or "\\" in version or ".." in version:
        return None
    try:
        data = json.loads((NOTES_DIR / f"{version}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    chosen = data.get("en" if lang == "en" else "ko") or data.get("ko") or {}
    if not isinstance(chosen, dict) or not str(chosen.get("changes") or "").strip():
        return None
    slides = _slides(chosen.get("slides"))
    if not slides and lang == "en":
        korean = data.get("ko")
        slides = _slides(korean.get("slides")) if isinstance(korean, dict) else []
    return {"changes": str(chosen.get("changes") or ""), "tour": str(chosen.get("tour") or ""), "slides": slides}


def newest_version() -> str:
    """글이 있는 가장 높은 판 — 패키지 밖(개발)에서 대화로 「뭐가 바뀌었어?」에 답할 때 쓴다."""
    def key(name: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in name.split("."))
        except ValueError:
            return (-1,)
    names = [path.stem for path in NOTES_DIR.glob("*.json")]
    names = [name for name in names if key(name) != (-1,)]
    return max(names, key=key) if names else ""


def _seen_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / SEEN_NAME


def read_seen(data_dir: str | Path) -> str | None:
    try:
        value = json.loads(_seen_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(value.get("version") or "") if isinstance(value, dict) else None


def mark_seen(data_dir: str | Path, version: str) -> dict[str, Any]:
    version = str(version or "").strip()
    if not version:
        return {"ok": False, "error": "no_version"}
    path = _seen_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"version": version}), encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}"}
    return {"ok": True, "version": version}


def status(data_dir: str | Path, version: str, *, setup_done: bool, lang: str = "ko") -> dict[str, Any]:
    """화면이 한 줄을 띄울지. `{"show", "version", "changes", "tour", "slides"}` — 슬라이드가 없는 판은 `slides: []`."""
    version = str(version or "").strip()
    if not version:
        return {"show": False, "version": ""}
    seen = read_seen(data_dir)
    if seen is None and not setup_done:
        # 막 깐 사람 — 마법사가 먼저다. 이 판은 본 것으로 적고, 다음 업데이트부터 알린다.
        mark_seen(data_dir, version)
        return {"show": False, "version": version}
    if seen == version:
        return {"show": False, "version": version}
    notes = notes_for(version, lang)
    if notes is None:
        return {"show": False, "version": version}
    return {"show": True, "version": version, **notes}


def chat_answer(version: str, lang: str = "ko") -> str:
    """「뭐가 바뀌었어?」에 하는 답 — 모델이 쓰지 않는다. 글이 없으면 빈 문자열."""
    used = str(version or "").strip() or newest_version()
    notes = notes_for(used, lang)
    if notes is None:
        return ""
    if lang == "en":
        head = f"Here is what changed in Sonjari {used}."
    else:
        head = f"손자리 {used} 에서 바뀐 것입니다."
    parts = [head, notes["changes"].strip()]
    if notes["tour"].strip():
        parts.append(notes["tour"].strip())
    return "\n\n".join(parts)
