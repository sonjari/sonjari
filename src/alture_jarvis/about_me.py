"""「나에 대한 지침」 — 사용자 지침을 **파일 하나**에 모으고, 그 위에 쉬운 화면을 얹는다.

## ★ 2026-10-18 왜 만들었나

조사(`docs/사용자지침_스킬만들기_조사_1018.ko.md`)를 하다 손자리 안에서 두 조각이 서로 엇갈려 있는 것을 찾았다.

1. **프로필 파일(`JARVIS_PROFILE.md`)** — 매 턴 `<jarvis-profile>` 로 실리는 「사람이 쓴 신뢰 가능한 글」 자리가 이미 있었다.
   그런데 화면이 없어서 일반 사용자는 거기에 쓸 길이 없었다.
2. **지침 가져오기(`instruction_import.py`)** — 화면은 있는데 가져온 글을 **아무 프롬프트도 읽지 않았다.** 막다른 길이다.

남들(OpenClaw `USER.md` 4,000자 · Hermes `USER.md` 1,375자)도 「파일이 진짜, 화면은 그 위의 껍데기」다. ChatGPT 는 빈칸 옆에
「고르기」를 붙였다 — 빈칸은 잘 안 채워진다. 그래서:

- **진짜는 파일 하나.** 자리 · 이름은 그대로(`JARVIS_PROFILE.md`) — 이미 쓰는 PC 와 맞추려고. 화면에서는 「나에 대한 지침」.
  개발자는 이 파일을 메모장 · 편집기로 바로 고친다. 저장하면 **다음 턴부터** 실린다(`profile.OperatorProfile` 이 바뀐 것을 다시 읽음).
- **3분 카드.** 빈칸 대신 질문 몇 개(하는 일 · 답 길이 · 말투 · 자주 쓰는 사이트 · 하지 말 것). 답에서 줄을 만드는 것은
  **이 파일의 결정론 코드**다(모델 호출 없음) — 같은 답이면 언제나 같은 줄이 나온다.
- **가져온 지침은 골라 올리기만.** 통째로 싣지 않는다. 사람이 줄을 고르면 그 줄만 이 파일 끝에 더한다. 비밀이 걷힌 줄은 못 더한다.
- **길이 자.** 이 글은 매 턴 실려 일할 자리(창)를 먹는다. 작은 카드(48K 창)에서 고정 앞부분이 창의 57% 를 먹은 기록이 있다
  (2026-10-11). 그래서 「창의 N%」를 보여 주고 10% 를 넘으면 살짝 경고한다. 글자 → 토큰은 우리가 잰 값(`transcript.CHARS_PER_TOKEN`,
  한글 약 2자 = 1토큰, 2026-08-10 실측)을 그대로 쓴다. 새 상수를 만들지 않는다.

## 카드 답은 어디에 두나 — 곁 JSON(`JARVIS_PROFILE.answers.json`)

파일 머리(front-matter)에 넣으면 그 글도 매 턴 모델에게 가거나, 아니면 읽을 때 따로 걷어 내야 한다. 개발자가 파일을 열면
읽기 어려운 YAML 이 맨 위에 있게 된다. 곁 JSON 은 **프롬프트에 절대 안 실리고**, 카드를 다시 열 때 답을 채우는 데만 쓴다.
파일에는 사람이 읽는 줄만 남는다.

카드가 쓴 줄은 `<!-- sonjari:card … -->` ~ `<!-- /sonjari:card -->` 사이에 둔다. 카드를 다시 저장하면 **그 사이만** 바뀌고,
개발자가 손으로 쓴 줄 · 가져온 줄은 그대로다. HTML 주석은 모델에게 안 간다(`profile.strip_comments`) — 경계 표시는 공짜다.

## 부르는 이름

이미 설정(`settings.json` 의 `user_label`)에 살고, 시스템 글 · 에이전트 글 두 곳이 그 값을 읽는다. 파일에 한 번 더 적으면
값이 두 자리에 살아 갈린다(사고 Q). 그래서 카드의 「부르는 이름」은 **그 설정을 그대로 고친다** — 설정 › 일반과 같은 값이다.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any

from .profile import OperatorProfile, profile_block, strip_comments
from .secret_scrub import scrub
from .transcript import CHARS_PER_TOKEN

#: 창의 이 몫을 넘으면 화면이 살짝 경고한다. 「상한」이 아니라 안내다 — 저장은 글자 상한(`profile_max_chars`)만 막는다.
WARN_SHARE = 0.10

CARD_START = "<!-- sonjari:card · 「나에 대한 지침」 3분 카드가 쓰는 칸 — 카드를 다시 저장하면 이 사이만 바뀝니다 -->"
CARD_END = "<!-- /sonjari:card -->"
_CARD_BLOCK = re.compile(r"<!-- sonjari:card\b.*?-->.*?<!-- /sonjari:card -->[ \t]*\n?", re.S)

#: 새 파일을 「파일 열기」로 처음 만들 때의 머리말. 주석이라 모델에게는 0자다.
#: ★ 안에 주석 표시를 또 쓰면 안 된다 — 걷는 규칙이 **처음 닫는 표시**에서 끊어 뒤쪽 글이 모델에게 샌다.
FILE_HEADER = (
    "<!-- 손자리 「나에 대한 지침」 · About me — 이 파일의 글이 매 대화에 실립니다. "
    "이런 꺾쇠 주석 안의 메모는 모델에게 가지 않습니다. 저장하면 다음 대화부터 쓰입니다. -->\n"
)

LENGTHS = ("short", "normal", "long")
TONES = ("casual", "polite")

#: 답 → 줄. 「보통」은 줄을 안 만든다 — 기본값을 적으면 매 턴 토큰만 먹는다.
_FIXED_LINES = {
    "ko": {
        "length:short": "- 답은 짧게, 핵심부터.",
        "length:long": "- 답은 자세히, 까닭과 예를 들어.",
        "tone:casual": "- 말투는 편하게, 딱딱하지 않게.",
        "tone:polite": "- 말투는 정중하게, 존댓말로.",
        "work": "- 하는 일: {0}",
        "sites": "- 자주 쓰는 사이트: {0}",
        "avoid": "- 하지 말 것: {0}",
    },
    "en": {
        "length:short": "- Keep answers short; lead with the point.",
        "length:long": "- Give detailed answers with reasons and examples.",
        "tone:casual": "- Use a relaxed, friendly tone.",
        "tone:polite": "- Use a polite, formal tone.",
        "work": "- What I do: {0}",
        "sites": "- Sites I use often: {0}",
        "avoid": "- Don't: {0}",
    },
}

#: 칸마다 글자 상한. 「부르는 이름」은 설정 칸의 상한(`settings.py` user_label max_length 20)과 같다.
_LIMITS = {"user_label": 20, "work_text": 120, "avoid_text": 200}
_MAX_SITES = 8
_MAX_SITE_CHARS = 40
_SITE_SPLIT = re.compile(r"[,，、;\n]+")
_SECRET_MARK = "[비밀 걷어 냄:"


class AboutMeError(ValueError):
    """사람에게 돌려줄 까닭 코드. 화면이 코드를 사람 말로 바꾼다."""


def _one_line(value: Any, limit: int) -> str:
    """한 줄로 펴고, 주석 경계를 못 쓰게 한다(카드 칸을 깨뜨리지 않게)."""
    text = " ".join(str(value or "").replace("<!--", "").replace("-->", "").split())
    if len(text) > limit:
        raise AboutMeError("answer_too_long")
    return text


def normalize_answers(raw: Any) -> dict[str, Any]:
    """카드 답을 검사해 정리한다. 모르는 칸은 버리고, 선택지 밖 값은 거절한다."""
    data = raw if isinstance(raw, dict) else {}
    length = str(data.get("length") or "")
    tone = str(data.get("tone") or "")
    if length and length not in LENGTHS:
        raise AboutMeError("bad_choice")
    if tone and tone not in TONES:
        raise AboutMeError("bad_choice")
    sites_raw = data.get("sites")
    pieces = sites_raw if isinstance(sites_raw, list) else _SITE_SPLIT.split(str(sites_raw or ""))
    sites: list[str] = []
    for piece in pieces:
        site = _one_line(piece, 10_000)[:_MAX_SITE_CHARS].strip()
        if site and site not in sites:
            sites.append(site)
    return {
        "user_label": _one_line(data.get("user_label"), _LIMITS["user_label"]),
        "work_text": _one_line(data.get("work_text"), _LIMITS["work_text"]),
        "length": length,
        "tone": tone,
        "sites": sites[:_MAX_SITES],
        "avoid_text": _one_line(data.get("avoid_text"), _LIMITS["avoid_text"]),
    }


def card_lines(answers: dict[str, Any], lang: str = "ko") -> list[str]:
    """답 → 줄. **결정론**이다 — 모델을 부르지 않는다. 순서도 고정(하는 일 → 답 길이 → 말투 → 사이트 → 하지 말 것).

    「부르는 이름」은 줄을 만들지 않는다 — 설정(`user_label`)이 이미 매 턴 따로 싣는다.
    """
    words = _FIXED_LINES.get(lang, _FIXED_LINES["ko"])
    lines: list[str] = []
    if answers.get("work_text"):
        lines.append(words["work"].format(answers["work_text"]))
    if answers.get("length") in ("short", "long"):
        lines.append(words[f"length:{answers['length']}"])
    if answers.get("tone") in TONES:
        lines.append(words[f"tone:{answers['tone']}"])
    if answers.get("sites"):
        lines.append(words["sites"].format(", ".join(answers["sites"])))
    if answers.get("avoid_text"):
        lines.append(words["avoid"].format(answers["avoid_text"]))
    return lines


def render_card(lines: list[str]) -> str:
    return f"{CARD_START}\n" + "\n".join(lines) + f"\n{CARD_END}\n" if lines else ""


def merge_card(content: str, card: str) -> str:
    """카드 칸만 바꾼다. 칸이 없으면 맨 위에 둔다(가장 짧고 가장 덜 바뀌는 글 — 앞에 있어야 프리필 캐시가 덜 깨진다)."""
    body = str(content or "")
    if _CARD_BLOCK.search(body):
        merged = _CARD_BLOCK.sub(lambda _m: card, body, count=1)
    elif card:
        rest = body.strip()
        merged = card + ("\n" + rest + "\n" if rest else "")
    else:
        merged = body
    return _tidy(merged)


def _tidy(text: str) -> str:
    """줄 끝 빈칸을 떼고, 빈 줄이 셋 이상 이어지면 둘로. 비었으면 빈 글, 아니면 줄바꿈 하나로 끝난다."""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return body + "\n" if body else ""


def injected_text(content: str, max_chars: int) -> str:
    """모델에게 실제로 가는 글 — `OperatorProfile.reload` 와 같은 규칙(앞뒤 공백 걷고 상한까지, 주석이 있으면 걷기)."""
    raw = str(content or "").strip()[:max_chars]
    return strip_comments(raw) if "<!--" in raw else raw


def meter(config: Any, content: str, max_chars: int) -> dict[str, Any]:
    """「창의 N%」. 대화 판 시스템 글에 실리는 블록 그대로(`profile_block`)를 잰다."""
    sent = injected_text(content, max_chars)
    block = profile_block(sent)
    tokens = math.ceil(len(block) / CHARS_PER_TOKEN) if block else 0
    try:
        num_ctx = int(config.num_ctx_for("chat"))
    except Exception:  # noqa: BLE001 — 자가 없어도 저장은 된다
        num_ctx = int(getattr(config, "ollama_num_ctx", 0) or 0)
    share = tokens / num_ctx if num_ctx > 0 else 0.0
    return {
        "sent_chars": len(sent),
        "tokens": tokens,
        "num_ctx": num_ctx,
        "share": round(share, 4),
        "share_pct": round(share * 100, 1),
        "warn": share > WARN_SHARE,
        "warn_share": WARN_SHARE,
        "chars_per_token": CHARS_PER_TOKEN,
    }


class AboutMe:
    """설정 화면 · 첫 실행 카드 · 지침 가져오기가 함께 쓰는 한 문. 파일 자리는 `config.profile_path` 하나다."""

    def __init__(self, config: Any, profile: OperatorProfile, *, settings: Any = None, imports: Any = None,
                 clock: Any = time.time) -> None:
        self.config = config
        self.profile = profile
        self.settings = settings
        self.imports = imports
        self.clock = clock
        self._lock = threading.RLock()

    # ── 자리 ────────────────────────────────────────────────────────────────
    @property
    def path(self) -> Path:
        return Path(self.profile.path)

    @property
    def answers_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".answers.json")

    @property
    def max_chars(self) -> int:
        return int(self.profile.max_chars)

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8-sig") if self.path.is_file() else ""
        except OSError:
            return ""

    def _write_atomic(self, path: Path, data: bytes) -> None:
        """임시 파일 → 바꿔 끼우기. 윈도우에서 다른 프로그램이 잠깐 붙잡으면(EPERM) 몇 번 다시 한다."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(data)
        for attempt in range(5):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def _stored_answers(self) -> dict[str, Any]:
        try:
            data = json.loads(self.answers_path.read_text(encoding="utf-8"))
            return normalize_answers(data.get("answers"))
        except (OSError, ValueError, AboutMeError, AttributeError):
            return normalize_answers({})

    # ── 보기 ────────────────────────────────────────────────────────────────
    def view(self) -> dict[str, Any]:
        content = self._read()
        answers = self._stored_answers()
        # 부르는 이름은 설정이 진짜다 — 설정 › 일반에서 바꿨으면 그 값을 보인다.
        answers["user_label"] = str(getattr(self.config, "user_label", "") or "")
        return {
            "ok": True,
            "path": str(self.path),
            "exists": self.path.is_file(),
            # ★ `content_raw` · `card_lines` 이름은 응답 번역(`ui_i18n._KEEP_KEYS`)이 건드리지 않는 칸이다 — 영어 화면에서
            #   사용자가 쓴 글이 사전과 우연히 같아 바뀐 채 저장되돌아오는 일을 막는다.
            "content_raw": content,
            "chars": len(content.strip()),
            "max_chars": self.max_chars,
            "truncated": len(content.strip()) > self.max_chars,
            "has_card": bool(_CARD_BLOCK.search(content)),
            "answers": answers,
            **meter(self.config, content, self.max_chars),
        }

    # ── 원문 저장(개발자 편집기) ────────────────────────────────────────────────
    def save(self, content: str) -> dict[str, Any]:
        with self._lock:
            text = _tidy(content)
            if len(text.strip()) > self.max_chars:
                return self._too_long(len(text.strip()))
            self._write_atomic(self.path, text.encode("utf-8"))
            self.profile.reload()
            return {**self.view(), "saved": True}

    def _too_long(self, chars: int) -> dict[str, Any]:
        return {"ok": False, "error": "too_long", "chars": chars, "max_chars": self.max_chars,
                "message": f"「나에 대한 지침」은 {self.max_chars}자까지입니다(지금 {chars}자). 줄을 덜어 낸 뒤 다시 저장해 주세요."}

    # ── 3분 카드 ──────────────────────────────────────────────────────────────
    def _card_result(self, raw_answers: Any, lang: str) -> tuple[dict[str, Any], list[str], str]:
        answers = normalize_answers(raw_answers)
        lines = card_lines(answers, "en" if lang == "en" else "ko")
        for line in lines:
            if scrub(line)["secret_total"]:
                raise AboutMeError("secret_in_answer")
        return answers, lines, merge_card(self._read(), render_card(lines))

    def preview_card(self, raw_answers: Any, lang: str = "ko") -> dict[str, Any]:
        """저장하지 않는다. 화면이 「이렇게 들어갑니다」를 보여 주고, 사람이 확인하면 `save_card` 를 부른다."""
        try:
            answers, lines, content = self._card_result(raw_answers, lang)
        except AboutMeError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "answers": answers, "card_lines": lines, "content_raw": content,
                "chars": len(content.strip()), "max_chars": self.max_chars,
                "fits": len(content.strip()) <= self.max_chars, **meter(self.config, content, self.max_chars)}

    def save_card(self, raw_answers: Any, lang: str = "ko") -> dict[str, Any]:
        with self._lock:
            try:
                answers, lines, content = self._card_result(raw_answers, lang)
            except AboutMeError as exc:
                return {"ok": False, "error": str(exc)}
            if len(content.strip()) > self.max_chars:
                return self._too_long(len(content.strip()))
            # 이름부터 — 설정이 거절하면(너무 김 등) 파일도 안 바꾼다. 반쯤 저장된 카드가 제일 나쁘다.
            current_label = str(getattr(self.config, "user_label", "") or "")
            if answers["user_label"] != current_label and self.settings is not None:
                result = self.settings.patch({"user_label": answers["user_label"]})
                if not result.get("ok"):
                    return {"ok": False, "error": "user_label_rejected", "detail": result.get("error")}
            self._write_atomic(self.path, content.encode("utf-8"))
            stored = {k: v for k, v in answers.items() if k != "user_label"}
            self._write_atomic(self.answers_path, json.dumps(
                {"version": 1, "updated_at": self.clock(), "lang": "en" if lang == "en" else "ko", "answers": stored},
                ensure_ascii=False, indent=2).encode("utf-8"))
            self.profile.reload()
            return {**self.view(), "saved": True, "card_lines": lines}

    # ── 가져온 지침에서 골라 올리기 ──────────────────────────────────────────────
    def _import_row(self, import_id: int) -> dict[str, Any] | None:
        if self.imports is None:
            return None
        try:
            return self.imports.get(int(import_id))
        except (TypeError, ValueError):
            return None

    def _lines_of(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        present = {line.strip() for line in self._read().splitlines() if line.strip()}
        out = []
        for index, line in enumerate(str(row.get("text") or "").replace("\r\n", "\n").split("\n")):
            raw = line.rstrip()
            if not raw.strip():
                reason = "blank"
            # 걷은 표시가 남은 줄 · 다시 걸어 봐도 비밀처럼 생긴 줄은 **못 더한다**(백엔드 한 곳에서 정한다).
            elif _SECRET_MARK in raw or scrub(raw)["secret_total"]:
                reason = "secret"
            elif raw.strip() in present:
                reason = "already"
            else:
                reason = ""
            out.append({"index": index, "raw": raw, "allowed": not reason, "reason": reason})
        return out

    def import_lines(self, import_id: int) -> dict[str, Any]:
        row = self._import_row(import_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        lines = self._lines_of(row)
        return {"ok": True, "import_id": row["import_id"], "tool_name": row["tool_name"],
                "source_path": row["source_path"], "lines": lines,
                "allowed_count": sum(1 for line in lines if line["allowed"])}

    def append_import(self, import_id: int, indexes: Any) -> dict[str, Any]:
        with self._lock:
            row = self._import_row(import_id)
            if row is None:
                return {"ok": False, "error": "not_found"}
            wanted: list[int] = []
            for value in indexes if isinstance(indexes, list) else []:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number not in wanted:
                    wanted.append(number)
            lines = self._lines_of(row)
            by_index = {line["index"]: line for line in lines}
            picked: list[str] = []
            refused: list[dict[str, Any]] = []
            for number in sorted(wanted):
                line = by_index.get(number)
                if line is None:
                    refused.append({"index": number, "reason": "not_in_import"})
                elif not line["allowed"]:
                    refused.append({"index": number, "reason": line["reason"]})
                elif line["raw"].strip() not in {p.strip() for p in picked}:
                    picked.append(line["raw"].replace("<!--", "").replace("-->", ""))
            if not picked:
                return {"ok": False, "error": "nothing_to_add", "refused": refused}
            day = time.strftime("%Y-%m-%d", time.localtime(self.clock()))
            name = (Path(str(row.get("source_path") or "")).name or str(row.get("tool_name") or "")).replace("--", "-")
            note = f"<!-- 가져옴: {row.get('tool_name') or ''} · {name} · {day} -->"
            current = self._read()
            content = _tidy((current.rstrip() + "\n\n" if current.strip() else "") + note + "\n" + "\n".join(picked))
            if len(content.strip()) > self.max_chars:
                return {**self._too_long(len(content.strip())), "refused": refused}
            self._write_atomic(self.path, content.encode("utf-8"))
            self.profile.reload()
            return {**self.view(), "added": len(picked), "refused": refused}

    # ── 파일 열기 ─────────────────────────────────────────────────────────────
    def ensure_file(self) -> Path:
        with self._lock:
            if not self.path.is_file():
                self._write_atomic(self.path, FILE_HEADER.encode("utf-8"))
                self.profile.reload()
            return self.path


__all__ = ["AboutMe", "AboutMeError", "CARD_END", "CARD_START", "WARN_SHARE", "card_lines", "merge_card",
           "meter", "normalize_answers", "render_card"]
