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

from .pack_models import ModelError, parse_models, public_model

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
    #: 켤 때 그 자리에서 받을 모델 · 실행기(`pack_models.parse_models` 가 검증한 칸). 없으면 받을 것이 없는 팩.
    models: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: 이 팩 다음에 이어 쓸 팩(2026-11-16 · 설계_팩켜기UX §4-3) — `[{"pack": id, "when": 한 줄}]`. 권하기만 한다(켜는 것은 사람).
    next: tuple[dict[str, str], ...] = field(default_factory=tuple)

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
            "permissions": localize_permissions(self.permissions), "bench": self.bench,
            "sources": [dict(item) for item in self.sources],
            "guide": bool(self.guide_path),
            "origin": self.origin,
            "triggers": {name: list(words) for name, words in self.triggers.items()},
            "asks": dict(self.asks),
            "work": dict(self.work),
            # 켜기 전에 「무엇을 얼마나 받나 · 어느 라이선스인가」를 보여 주려고 — 주소 · 해시는 싣지 않는다.
            "models": [public_model(model) for model in self.models],
            "next": [dict(item) for item in self.next],
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


#: 「다음 팩」 한 줄의 한도 — 권하는 까닭 한 줄이지 글이 아니다.
NEXT_WHEN_MAX_CHARS = 80
NEXT_MAX = 4


def _read_next(pack_id: str, raw: Any) -> tuple[dict[str, str], ...]:
    """`next` 칸을 읽는다(2026-11-16). 팩 id 꼴 · 한 줄 까닭만 받는다 — 없는 팩 이름은 쓸 때 거른다(팩은 따로 깔린다)."""
    if raw in (None, []):
        return ()
    if not isinstance(raw, list) or len(raw) > NEXT_MAX:
        raise PackError(f"{pack_id}: next 는 [{{pack, when}}, …] 꼴(최대 {NEXT_MAX}개)이어야 한다")
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"pack", "when"}:
            raise PackError(f"{pack_id}: next 의 한 칸은 pack · when 만 가진다")
        target = str(item.get("pack") or "")
        when = " ".join(str(item.get("when") or "").split())
        if not _PACK_ID.fullmatch(target) or target == pack_id:
            raise PackError(f"{pack_id}: next.pack 「{target}」 — 다른 팩의 id 여야 한다")
        if not when or len(when) > NEXT_WHEN_MAX_CHARS:
            raise PackError(f"{pack_id}: next.when 은 1~{NEXT_WHEN_MAX_CHARS}자 한 줄이어야 한다")
        if all(row["pack"] != target for row in out):
            out.append({"pack": target, "when": when})
    return tuple(out)


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
    try:
        models = parse_models(pack_id, data.get("models"))
    except ModelError as exc:
        raise PackError(str(exc)) from exc
    if models and kind != "code":
        raise PackError(f"{pack_id}: 내려받을 모델(models)은 코드 팩(code)만 가질 수 있다")
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
        models=models,
        next=_read_next(pack_id, data.get("next")),
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


#: pack.json 의 경로 자리 표시(2026-11-16 · ADR-PACK-1). 예전엔 `내 문서\Sonjari\animator` 를 그대로 적어
#: JSON 의 `\a` 가 벨 문자로 읽혀 깨졌고(「Sonjari□nimator」), 맥에도 윈도우 경로가 보였다. 이제 `{docs}/Sonjari/animator` 로 적고 기계마다 푼다.
_DOCS_PATH = re.compile(r"\{docs\}((?:/[^\s/()·,]+)*)")


def localize(text: str, platform: str | None = None) -> str:
    """`{docs}/Sonjari/x` → 윈도우 `내 문서` 아래(역슬래시) · 맥 `~/Documents/Sonjari/x`."""
    import sys

    mac = (platform or sys.platform) == "darwin"

    def put(match: "re.Match[str]") -> str:
        rest = match.group(1)
        return "~/Documents" + rest if mac else "내 문서" + rest.replace("/", "\\")

    return _DOCS_PATH.sub(put, str(text))


def localize_permissions(permissions: dict[str, Any], platform: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (permissions or {}).items():
        if isinstance(value, list):
            out[key] = [localize(item, platform) for item in value]
        elif isinstance(value, str):
            out[key] = localize(value, platform)
        else:
            out[key] = value
    return out


def tools_here(pack: "Pack", platform: str | None = None) -> list[str]:
    """이 기계에서 쓰는 도구 — 맥이면 「맥에서는 아직」 표의 도구를 뺀다(애니메이터 15 → 맥 13)."""
    from .tool_gateway import not_yet_on_mac

    return [name for name in pack.tools if not_yet_on_mac(name, platform) is None]


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
        #: 「이 PC 에 맞는 팩」 권하기를 사람이 무시한 팩(2026-11-16 · `pack_hints`). 다시 묻지 않는다.
        self._dismissed = self._read_dismissed()
        #: 「팩 켜기는 클로드에게 맡기기」(2026-11-16 · ADR-PACK-1). 사람이 손자리 쪽 문(화면 · 설정 API)에서만 켠다 — 도구로 켜는 길은 없다.
        self._claude_may_enable = self._read_raw_state().get("claude_may_enable") is True
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

    def _read_raw_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_state(self) -> set[str]:
        return {str(item) for item in self._read_raw_state().get("enabled") or () if str(item) in self.packs}

    def _read_dismissed(self) -> set[str]:
        # 지금 없는 팩 이름도 지우지 않고 둔다 — 팩이 다음 판에 돌아와도 「무시」가 살아 있게.
        return {str(item) for item in self._read_raw_state().get("hint_dismissed") or () if _PACK_ID.fullmatch(str(item))}

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        # ★ 켜고 끌 때 「무시」를 덮어 지우지 않는다 — 한 파일에 둘이 같이 산다.
        state = {"enabled": sorted(self._enabled), "hint_dismissed": sorted(getattr(self, "_dismissed", set())),
                 "claude_may_enable": bool(getattr(self, "_claude_may_enable", False))}
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
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

    def dismiss_hint(self, pack_id: str) -> dict[str, Any]:
        """사람이 「나중에 · 무시」를 눌렀다 — 그 팩은 다시 권하지 않는다. 켜고 끄는 것과는 상관없다."""
        if pack_id not in self.packs:
            raise PackError(f"unknown_pack: {pack_id}")
        with self._lock:
            self._dismissed.add(pack_id)
            self._write_state()
        return {"pack": pack_id, "dismissed": True}

    def hint_dismissed(self) -> set[str]:
        return set(self._dismissed)

    def claude_may_enable(self) -> bool:
        """사람이 「팩 켜기는 클로드에게 맡기기」를 켜 두었나(ADR-PACK-1). 바깥 클로드의 켜기 청만 카드 없이 지나간다."""
        return bool(self._claude_may_enable)

    def set_claude_may_enable(self, on: bool) -> dict[str, Any]:
        """사람 쪽 문(화면 · `POST /v1/packs/delegate`)에서만 부른다. 도구 목록 어디에도 이 일을 하는 도구를 두지 않는다."""
        with self._lock:
            self._claude_may_enable = bool(on)
            self._write_state()
        return {"claude_may_enable": self._claude_may_enable}

    def next_for(self, pack_id: str) -> list[dict[str, str]]:
        """`pack_id` 다음에 이어 쓸 팩 — 이미 켰거나 · 권하기를 무시했거나 · 이 판에 없는 팩은 뺀다."""
        pack = self.packs.get(pack_id)
        if pack is None:
            return []
        return [{"pack": item["pack"], "name": self.packs[item["pack"]].name, "when": item["when"]}
                for item in pack.next
                if item["pack"] in self.packs and not self.is_enabled(item["pack"]) and item["pack"] not in self._dismissed]

    def describe(self, pack_id: str) -> dict[str, Any]:
        pack = self.packs[pack_id]
        return {**pack.public(), "enabled": self.is_enabled(pack_id)}

    def listing(self) -> dict[str, Any]:
        return {
            "packs": [self.describe(pack_id) for pack_id in sorted(self.packs)],
            "problems": list(self.problems),
            "user_dir": str(self.user_dir) if self.user_dir is not None else "",
            "claude_may_enable": self.claude_may_enable(),
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
