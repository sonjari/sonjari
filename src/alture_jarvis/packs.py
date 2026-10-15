"""분야 팩 — 온텔릭 본체 위에 얹는 능력 묶음 (0판, 2026-09-27 · 전략안 §50).

## 왜

본체는 브라우저·파일·문서만 쥔다. 게임(유니티)·교육 같은 분야 능력은 **필요한 사람만** 켠다.
유니티 도구를 본체에 넣었더니 게임을 안 하는 사람의 도구 목록(147개)에도 끼었다 — 작은 모델에겐 고를 것만 는다.

## 팩 한 개 = 폴더 한 개

    packs/<id>/pack.json     이름·버전·설명·구성·**권한**·벤치·출처
    packs/<id>/recipes/      레시피(팩이 켜졌을 때만 보인다)
    packs/<id>/skills/vendor/<묶음>/<스킬>/SKILL.md   스킬(+LICENSE)

- 기본은 **꺼짐**. 켜고 끈 상태는 사용자 데이터 폴더의 `packs.json` 에 둔다(앱을 새로 깔아도 남게 하는 것은 다음 판).
- 켤 때 화면은 `permissions` 를 **먼저 보여 준다** — 무엇을 읽고, 무엇을 쓰고, 무엇을 실행하고, 인터넷을 쓰는가.
  누른 것이 동의다(Ollama 설치 단추와 같은 규칙).
- 형식은 처음부터 「남이 올린다」를 전제로 한다: `kind` 가 `content`(레시피·스킬만)면 누구나, `code`(새 도구)면 우리와
  검증된 파트너만. 0판에서는 저장소에 들어 있는 우리 팩만 읽는다 — 내려받기는 다음 판.

## 직접 넣는 스킬팩 (2026-10-11)

대표: 「스킬팩 폴더를 하나 만들어 주고 그걸 손자리에 넣는 방식 — 사용자는 우리가 준 폴더를 거기에 넣기만 하면 된다」.

    문서\Sonjari\skillpacks\<id>\pack.json
    문서\Sonjari\skillpacks\<id>\skills\<스킬>\SKILL.md      (클로드 스킬과 같은 짜임 — 묶음 폴더 · LICENSE 없이)

- 자리는 **문서 폴더**다. 프로그램 폴더는 스토어 판에서 잠겨 있고 판마다 새것으로 바뀐다. 앱 자료 폴더는 스토어 판에서
  「앱 전용 칸」으로 가서, 탐색기로 넣은 것을 우리가 못 본다(2026-09-18).
- 여기서는 **`content` 팩만** 읽는다. 누가 준 폴더를 넣었다고 새 실행 능력이 생기면 안 된다.
- 우리가 싣는 팩의 이름을 가로채지 못한다. 못 읽은 것은 이유와 함께 `problems` 에 남는다.
- 팩은 **제 낱말**(`triggers`)을 들고 온다 — 어떤 말에 그 스킬이 붙는가. 코드 안 낱말표를 고치지 않고도 새 스킬이 걸린다.
- 팩은 **시키는 말**(`asks`)도 들고 온다 — 사람이 매번 길게 쳤을 그 한 문장. 첫 실제 판에서 「가격 조사」만 치자 스킬은
  붙었는데 엑셀을 안 만들고 멈췄다: 「시킨 것」은 사람의 말에서만 뽑는데 그 말에 파일 요구가 없었다. 스킬 글에 「꼭
  만들어라」를 더 세게 적지 않는다(안내문은 안 먹는다) — 이 문장을 사람의 말 뒤에 붙여 원래 있던 요구 뽑기가 일하게 한다.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PACK_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_KINDS = frozenset({"content", "code"})
STATE_FILE = "packs.json"
#: 팩이 들고 오는 낱말의 한도. 한 글자 낱말은 아무 말에나 걸리고, 수백 개면 낱말표가 아니라 그물이다.
TRIGGER_MIN_CHARS = 2
TRIGGER_MAX_CHARS = 40
TRIGGERS_PER_SKILL = 40
#: 「시키는 말」은 요청 한 문장이다. 너무 짧으면 시키는 말이 아니고, 길면 요청이 아니라 글이다(글은 스킬에 쓴다).
ASK_MIN_CHARS = 10
ASK_MAX_CHARS = 300


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Pack:
    id: str
    root: Path
    name: str
    version: str
    kind: str
    summary: str
    description: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    domains: tuple[str, ...]
    permissions: dict[str, Any]
    bench: str = ""
    sources: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: 바깥 AI(클로드·코덱스)가 읽을 사용서 — 팩 폴더 안 상대 경로. 켜면 「잇기」가 스킬·지침에 넣는다.
    guide: str = ""
    #: `builtin`(프로그램과 같이 온 것) 또는 `user`(사람이 스킬팩 폴더에 넣은 것).
    origin: str = "builtin"
    #: 스킬 이름 → 그 스킬이 붙는 낱말들. 켜져 있을 때만 쓰인다.
    triggers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: 스킬 이름 → 그 스킬이 붙을 때 사람의 말 뒤에 붙는 한 문장(「시키는 말」).
    asks: dict[str, str] = field(default_factory=dict)
    #: 스킬 이름 → 그 일의 갈래(`WORK_KINDS`). 적혀 있으면 그 스킬이 붙은 판을 그 갈래의 일로 다룬다.
    work: dict[str, str] = field(default_factory=dict)

    @property
    def guide_path(self) -> Path | None:
        if not self.guide:
            return None
        path = (self.root / self.guide).resolve()
        return path if path.is_file() and self.root.resolve() in path.parents else None

    @property
    def recipes_dir(self) -> Path:
        return self.root / "recipes"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "version": self.version, "kind": self.kind,
            "summary": self.summary, "description": self.description,
            "tools": list(self.tools), "skills": list(self.skills), "domains": list(self.domains),
            "permissions": self.permissions, "bench": self.bench,
            "sources": [dict(item) for item in self.sources],
            "guide": bool(self.guide_path),
            "origin": self.origin,
            "triggers": {name: list(words) for name, words in self.triggers.items()},
            "asks": dict(self.asks),
            "work": dict(self.work),
        }


def _read_triggers(pack_id: str, raw: Any, skills: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """`triggers` 칸을 읽는다. 틀리면 팩을 받지 않는다 — 낱말은 「언제 끼어드는가」라서 대충 받으면 안 된다."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"{pack_id}: triggers 는 「스킬 이름: [낱말, …]」 꼴이어야 한다")
    out: dict[str, tuple[str, ...]] = {}
    for name, words in raw.items():
        if str(name) not in skills:
            raise PackError(f"{pack_id}: triggers 의 {name} 은 이 팩의 스킬이 아니다 — 제 스킬에만 낱말을 달 수 있다")
        if not isinstance(words, list) or not words or len(words) > TRIGGERS_PER_SKILL:
            raise PackError(f"{pack_id}: triggers.{name} 은 낱말 목록(1~{TRIGGERS_PER_SKILL}개)이어야 한다")
        cleaned: list[str] = []
        for word in words:
            text = " ".join(str(word).split()).lower()
            if not TRIGGER_MIN_CHARS <= len(text) <= TRIGGER_MAX_CHARS:
                raise PackError(
                    f"{pack_id}: triggers.{name} 의 「{text}」 — 낱말은 {TRIGGER_MIN_CHARS}~{TRIGGER_MAX_CHARS}자여야 한다"
                )
            if text not in cleaned:
                cleaned.append(text)
        out[str(name)] = tuple(cleaned)
    return out


def _read_asks(pack_id: str, raw: Any, skills: tuple[str, ...]) -> dict[str, str]:
    """`asks` 칸을 읽는다. 이 글은 **사람이 시킨 말로 취급된다** — 그래서 한 문장만, 제 스킬에만 받는다."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"{pack_id}: asks 는 「스킬 이름: 시키는 말 한 문장」 꼴이어야 한다")
    out: dict[str, str] = {}
    for name, sentence in raw.items():
        if str(name) not in skills:
            raise PackError(f"{pack_id}: asks 의 {name} 은 이 팩의 스킬이 아니다 — 제 스킬에만 말을 달 수 있다")
        if not isinstance(sentence, str):
            raise PackError(f"{pack_id}: asks.{name} 은 글 한 문장이어야 한다")
        # ★ 여러 줄은 받지 않는다. 사람의 말 뒤에 붙는 글이라, 줄을 바꿔 다른 지시를 끼워 넣을 자리를 주지 않는다.
        if "\n" in sentence.strip() or "\r" in sentence.strip():
            raise PackError(f"{pack_id}: asks.{name} 은 한 줄이어야 한다 — 긴 설명은 스킬 글에 쓴다")
        text = " ".join(sentence.split())
        if not ASK_MIN_CHARS <= len(text) <= ASK_MAX_CHARS:
            raise PackError(f"{pack_id}: asks.{name} 은 {ASK_MIN_CHARS}~{ASK_MAX_CHARS}자여야 한다")
        out[str(name)] = text
    return out


#: 팩이 적을 수 있는 일의 갈래 (2026-10-11). 지금은 하나다.
#:   web — 「웹을 보고 와서 정리하는 일」. 그 판은 조사 일의 손(브라우저 · 문서 쓰기 · 파일 읽기)만 받고,
#:         파일을 쓰기 전에 숫자를 읽은 자료와 대조한다(`tool_roster._is_web_research_job` 을 쓰는 자리 전부).
#: ★ 손을 **좁히는** 갈래만 받는다. 넓히는 갈래(코드 실행 등)를 팩이 스스로 적게 하면 팩이 권한을 올리는 길이 된다.
WORK_KINDS = frozenset({"web"})


def _read_work(pack_id: str, raw: Any, skills: tuple[str, ...]) -> dict[str, str]:
    """`work` 칸을 읽는다. 틀리면 팩을 받지 않는다 — 일의 갈래는 손과 검사를 바꾼다."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"{pack_id}: work 는 「스킬 이름: 갈래」 꼴이어야 한다")
    out: dict[str, str] = {}
    for name, kind in raw.items():
        if str(name) not in skills:
            raise PackError(f"{pack_id}: work 의 {name} 은 이 팩의 스킬이 아니다 — 제 스킬의 일만 정할 수 있다")
        if not isinstance(kind, str) or kind not in WORK_KINDS:
            raise PackError(f"{pack_id}: work.{name} 은 {sorted(WORK_KINDS)} 가운데 하나여야 한다")
        out[str(name)] = kind
    return out


def _load_manifest(folder: Path, origin: str = "builtin") -> Pack:
    path = folder / "pack.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"{folder.name}: pack.json 을 못 읽었다 — {exc}") from exc
    pack_id = str(data.get("id") or "")
    if not _PACK_ID.fullmatch(pack_id) or pack_id != folder.name:
        raise PackError(f"{folder.name}: id 는 폴더 이름과 같고 소문자·숫자·붙임표여야 한다")
    kind = str(data.get("kind") or "")
    if kind not in _KINDS:
        raise PackError(f"{pack_id}: kind 는 content 또는 code")
    # ★ 사람이 넣는 폴더에서는 스킬 글만 받는다. 새 도구(code)는 프로그램과 같이 온 팩만 가질 수 있다.
    if origin == "user" and kind != "content":
        raise PackError(f"{pack_id}: 직접 넣는 스킬팩은 스킬 글만 담을 수 있다(kind 는 content) — 새 도구는 받지 않는다")
    permissions = dict(data.get("permissions") or {})
    # ★ 권한을 안 적은 팩은 받지 않는다 — 켜는 사람이 무엇을 허락하는지 모르면 동의가 아니다.
    for key in ("reads", "writes", "runs", "network"):
        if key not in permissions:
            raise PackError(f"{pack_id}: permissions.{key} 가 없다 — 무엇을 하는지 적지 않은 팩은 켤 수 없다")
    tools = tuple(str(name) for name in data.get("tools") or ())
    if kind == "content" and tools:
        raise PackError(f"{pack_id}: 내용 팩(content)은 도구를 가질 수 없다 — 코드 팩(code)이어야 한다")
    for name in ("name", "version", "summary"):
        if not str(data.get(name) or "").strip():
            raise PackError(f"{pack_id}: {name} 가 비었다")
    skills = tuple(str(name) for name in data.get("skills") or ())
    return Pack(
        id=pack_id, root=folder, name=str(data["name"]), version=str(data["version"]), kind=kind,
        summary=str(data["summary"]), description=str(data.get("description") or ""),
        tools=tools, skills=skills,
        domains=tuple(str(name) for name in data.get("domains") or ()),
        permissions=permissions, bench=str(data.get("bench") or ""),
        sources=tuple(dict(item) for item in data.get("sources") or ()),
        guide=str(data.get("guide") or ""),
        origin=origin,
        triggers=_read_triggers(pack_id, data.get("triggers"), skills),
        asks=_read_asks(pack_id, data.get("asks"), skills),
        work=_read_work(pack_id, data.get("work"), skills),
    )


def load_packs(directory: Path, origin: str = "builtin") -> tuple[dict[str, Pack], list[str]]:
    """팩 폴더를 읽는다. 망가진 팩은 **건너뛰되 이유를 돌려준다**(조용히 빠지지 않는다)."""
    packs: dict[str, Pack] = {}
    problems: list[str] = []
    if not directory.is_dir():
        return packs, problems
    for folder in sorted(p for p in directory.iterdir() if p.is_dir() and (p / "pack.json").is_file()):
        try:
            pack = _load_manifest(folder, origin)
        except PackError as exc:
            problems.append(str(exc))
            continue
        packs[pack.id] = pack
    return packs, problems


class PackRegistry:
    """어떤 팩이 있고, 무엇이 켜져 있나. 켜고 끄는 것은 사람이 화면에서 한다."""

    def __init__(self, packs_dir: Path, data_dir: Path, user_dir: Path | None = None) -> None:
        self.packs_dir = Path(packs_dir)
        #: 사람이 스킬팩을 넣는 폴더(문서 폴더 안). 없으면 직접 넣는 팩은 없는 것이다.
        self.user_dir = Path(user_dir) if user_dir else None
        self.state_path = Path(data_dir) / STATE_FILE
        self._lock = threading.Lock()
        self.packs, self.problems = self._load()
        self._enabled = self._read_state()
        self._listeners: list[Any] = []

    def _load(self) -> tuple[dict[str, Pack], list[str]]:
        packs, problems = load_packs(self.packs_dir)
        if self.user_dir is not None:
            dropped, more = load_packs(self.user_dir, origin="user")
            problems.extend(more)
            for pack_id, pack in dropped.items():
                # ★ 프로그램과 같이 온 팩이 이긴다. 같은 이름의 폴더를 넣어 우리 팩(과 그 도구)을 갈아 끼우지 못한다.
                if pack_id in packs:
                    problems.append(f"{pack_id}: 이미 있는 팩 이름이다 — 폴더와 id 를 다른 이름으로 바꿔 넣어야 한다")
                    continue
                packs[pack_id] = pack
        return packs, problems

    def rescan(self) -> dict[str, Any]:
        """폴더를 다시 읽는다 — 사람이 스킬팩 폴더에 넣거나 뺀 뒤 「다시 읽기」. 켜 둔 것은 켜진 채다."""
        with self._lock:
            self.packs, self.problems = self._load()
            self._enabled = self._read_state()
        self._notify()
        return self.listing()

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 — 뒤따르는 정리가 실패해도 켜고 끈 사실은 남는다
                pass

    def _read_state(self) -> set[str]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {str(item) for item in data.get("enabled") or () if str(item) in self.packs}

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"enabled": sorted(self._enabled)}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)

    def on_change(self, callback: Any) -> None:
        """켜고 끌 때 불린다 — 스킬 다시 읽기 같은 것."""
        self._listeners.append(callback)

    def is_enabled(self, pack_id: str) -> bool:
        return pack_id in self._enabled

    def enabled(self) -> list[Pack]:
        return [self.packs[pack_id] for pack_id in sorted(self._enabled) if pack_id in self.packs]

    def set_enabled(self, pack_id: str, on: bool) -> dict[str, Any]:
        if pack_id not in self.packs:
            raise PackError(f"unknown_pack: {pack_id}")
        with self._lock:
            (self._enabled.add if on else self._enabled.discard)(pack_id)
            self._write_state()
        self._notify()
        return self.describe(pack_id)

    def describe(self, pack_id: str) -> dict[str, Any]:
        pack = self.packs[pack_id]
        return {**pack.public(), "enabled": self.is_enabled(pack_id)}

    def listing(self) -> dict[str, Any]:
        return {
            "packs": [self.describe(pack_id) for pack_id in sorted(self.packs)],
            "problems": list(self.problems),
            "user_dir": str(self.user_dir) if self.user_dir is not None else "",
        }

    # ── 본체의 다른 층이 묻는 것 ─────────────────────────────────────────
    def tool_owner(self, tool: str) -> str:
        return next((pack.id for pack in self.packs.values() if tool in pack.tools), "")

    def tool_enabled(self, tool: str) -> bool:
        """팩에 속한 도구면 그 팩이 켜져 있을 때만 True. 팩과 무관한 도구는 True."""
        owner = self.tool_owner(tool)
        return not owner or self.is_enabled(owner)

    def pack_tools(self) -> set[str]:
        return {tool for pack in self.packs.values() for tool in pack.tools}

    def skill_dirs(self) -> list[Path]:
        """켜진 **우리 팩**의 스킬 폴더(`vendor/<묶음>/<스킬>` 짜임 · LICENSE 를 본다)."""
        return [pack.skills_dir for pack in self.enabled() if pack.origin != "user" and pack.skills_dir.is_dir()]

    def user_skill_dirs(self) -> list[tuple[str, Path]]:
        """켜진 **직접 넣은 팩**의 `(팩 id, 스킬 폴더)`. 짜임이 다르다 — `skills/<스킬>/SKILL.md`."""
        return [(pack.id, pack.skills_dir) for pack in self.enabled() if pack.origin == "user" and pack.skills_dir.is_dir()]

    def triggers(self) -> dict[str, tuple[str, ...]]:
        """켜진 팩들이 들고 온 낱말. 꺼진 팩의 낱말은 없는 것이다."""
        merged: dict[str, tuple[str, ...]] = {}
        for pack in self.enabled():
            for name, words in pack.triggers.items():
                merged[name] = tuple(dict.fromkeys((*merged.get(name, ()), *words)))
        return merged

    def asks(self) -> dict[str, str]:
        """켜진 팩들이 들고 온 「시키는 말」. 스킬 이름 → 한 문장."""
        merged: dict[str, str] = {}
        for pack in self.enabled():
            for name, sentence in pack.asks.items():
                merged.setdefault(name, sentence)
        return merged

    def works(self) -> dict[str, str]:
        """켜진 팩들이 적어 온 일의 갈래. 스킬 이름 → 갈래."""
        merged: dict[str, str] = {}
        for pack in self.enabled():
            for name, kind in pack.work.items():
                merged.setdefault(name, kind)
        return merged

    def pack_skills(self) -> set[str]:
        return {skill for pack in self.packs.values() for skill in pack.skills}


__all__ = ["Pack", "PackError", "PackRegistry", "load_packs"]
