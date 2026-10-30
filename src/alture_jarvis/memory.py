from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .check_notes import SUMMARY_LINE_HEAD
from . import fact_extract


_SEARCH_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_SEARCH_STOP_WORDS = {
    "그거", "그것", "그리고", "근데", "그러면", "나는", "내가", "대한", "대해서",
    "말해줘", "알려줘", "어떻게", "어떤", "무엇", "뭐가", "지금", "이제", "정도",
    "관련", "내용", "답변", "질문", "해줘", "해주세요", "있어", "있는", "했던",
}


# 한국어 조사. **토막 하나가 회상을 통째로 막고 있었다** (2026-08-24 실측).
#
#     「외주를 어디서 받으려고 했지?」 → 검색어 '외주를'
#     코퍼스에는                        '외주'
#     → `term in searchable` 이라 영원히 안 겹친다. 0건.
#
# 같은 이유로 「우리 제품은」이 '제품'을 못 찾고, 「내 이름이」가 '이름은'을
# 못 찾았다. 기억 눈금 20문항 중 절반이 여기서 죽었다.
#
# 긴 것부터 본다 — '에서'를 '에'로 먼저 떼면 '서'가 남는다.
_JOSA = (
    "에서는", "에서도", "에게서", "으로는", "이라고", "라고는",
    "에서", "에게", "한테", "으로", "라고", "부터", "까지", "보다", "처럼",
    "이나", "든지", "밖에", "께서", "이란", "라는", "이라",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로", "랑",
)

#: 조사를 뗀 뒤 이보다 짧아지면 안 뗀다. 두 글자짜리는 떼면 아무 데나 걸린다
#: ('이사' 에서 '사' 를 떼는 식). 실측으로 정한 값이 아니라 보수적인 선이고,
#: 넓히려면 오탐을 재 보고 넓혀라.
_STEM_MIN = 2


def _stem(token: str) -> str:
    """조사를 뗀 몸통. 뗄 것이 없으면 빈 글자."""
    if not any("가" <= ch <= "힣" for ch in token):
        return ""
    for josa in _JOSA:
        if token.endswith(josa) and len(token) - len(josa) >= _STEM_MIN:
            return token[: -len(josa)]
    return ""


def _term_groups(value: str) -> list[tuple[str, ...]]:
    """낱말 하나를 **꼴들의 묶음**으로. `[('외주를','외주'), ('어디서',)]`

    ★ 왜 묶음이 필요한가 (2026-08-24).

    조사를 뗀 몸통을 그냥 낱말 목록에 더했더니 회상이 **오히려 나빠진 곳**이
    생겼다. 점수 계산이 `coverage = 맞은 수 / 전체 수` 인데, 몸통을 더하면
    **분모만 커진다** — '외주를'과 '외주'는 같은 낱말의 두 꼴이지 두 낱말이
    아니다. 그래서 통과하던 것이 걸러졌다(20번 문항이 그렇게 죽었다).

    묶음 하나가 낱말 하나다. 묶음 안의 **아무 꼴이나** 맞으면 그 낱말은 맞은
    것이고, 분모는 묶음 수다.
    """
    seen: set[str] = set()
    groups: list[tuple[str, ...]] = []
    for token in _SEARCH_TOKEN.findall(str(value or "").lower()):
        if token in _SEARCH_STOP_WORDS or token in seen:
            continue
        seen.add(token)
        forms = [token]
        stem = _stem(token)
        if stem and stem not in _SEARCH_STOP_WORDS and stem not in seen:
            seen.add(stem)
            forms.append(stem)
        groups.append(tuple(forms))
    return groups[:24]


def _search_terms(value: str) -> list[str]:
    """Return stable Korean/English terms for the dependency-free local index.

    ★ 조사를 뗀 몸통을 **더한다**(바꾸지 않는다). 원래 꼴도 남겨 두는 이유는
      정확히 일치할 때 점수가 더 높아야 하기 때문이다 — '외주를'이 그대로
      있는 문장이 '외주'만 있는 문장보다 가깝다.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for token in _SEARCH_TOKEN.findall(str(value or "").lower()):
        for candidate in (token, _stem(token)):
            if not candidate or candidate in _SEARCH_STOP_WORDS or candidate in seen:
                continue
            seen.add(candidate)
            terms.append(candidate)
    return terms[:32]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


#: 바깥 AI(MCP)가 맡긴 과제의 방 이름 머리 — `mcp_server` 가 과제마다 `mcp-…` 방을 준다.
DELEGATED_ROOM_PREFIX = "mcp-"

#: 「관련 기록 찾아 붙이기」로 **다른 대화**에서 가져온 글 묶음의 첫머리. 모델에게는 참고로 주되, 근거 없는 숫자를 가리는
#: 검사들은 이 묶음을 「알려진 값」으로 치지 않는다(`runtime._grounding_texts` · 2026-10-30 판 58761894).
#: 글자를 바꾸면 지시문 앞부분 캐시가 깨진다 — 이 상수로만 쓴다.
RECALLED_MEMORY_HEADER = "현재 질문과 관련되어 로컬 대화 기록에서 검색한 과거 기억이다. "


def normalize_session_id(value: str) -> str:
    cleaned = "".join(character for character in str(value or "office-main") if character.isalnum() or character in "._:-")
    return cleaned[:80] or "office-main"


#: 답 끝에 **우리가 덧붙인** 글의 머리 — 경고(⚠ **…**)와 대조표(**시킨 것 대조** · **Checklist**).
#: ★ 2026-10-24: 사람이 시킨 판은 대조표 대신 한 줄(`check_notes.SUMMARY_LINE_HEAD`)이 붙는다 — 그것도 우리 꼬리다.
_OUR_TAIL_BLOCK = re.compile(r"(?:⚠\s*\*\*|\*\*(?:시킨 것 대조|Checklist)\*\*|" + SUMMARY_LINE_HEAD.pattern + ")")
#: 답 맨 끝에 붙는 **사실 덩어리** — 만든 파일 목록 · 목록 줄의 주소. 모델에게도 남긴다(우리 꼬리를 뗄 때 건너뛴다).
_FACT_TRAILER = re.compile(r"(?:만든 파일:|\[이 목록의 주소\])")


def without_our_tail(content: str) -> str:
    """답 끝에 우리가 덧붙인 경고·대조표를 뗀 **모델이 실제로 한 말**.

    ★ 2026-10-05 대표 실사용(전략 대화 방). 덧붙인 글이 대화 기록에 남아 다음 턴의 모델에게 그대로 들어갔다.
      「❌ 깃허브에서 하기 — 거기서 아무것도 안 함」을 본 모델은 그것을 **아직 남은 숙제**로 읽고, 「너 생각은 어떠냐」·
      「국내는 왜 그럴까」에 앞 답을 경고문까지 그대로 되풀이했다(05cd5f7b · cecf6a10). 스스로 흉내 낸 경고문을
      쓰기까지 했다(19294dfa · f7caaae1 — 구두점이 우리 것과 다르다). 사람에게 한 말이지 모델에게 한 말이 아니다.

    끝에서부터, 우리 머리로 시작하는 덩어리만 뗀다 — 답 **가운데**의 ⚠ 는 모델이 쓴 것이라 그대로 둔다.
    화면과 저장된 기록은 안 바꾼다(「이어서 해줘」 판정은 저장된 글을 본다).
    """
    blocks = str(content or "").rstrip().split("\n\n")
    # ★ 우리 꼬리 **뒤에** 붙는 덩어리가 있었다 (2026-10-08 전수조사 3-3). 「만든 파일:」(runtime 이 맨 끝에 붙인다)과
    #   「[이 목록의 주소]」가 끝에 오면 끝에서부터 떼던 이 함수는 첫 덩어리에서 멈췄고, 그 앞의 경고·대조표가 전부 모델에게 갔다.
    #   저장된 손자리 답 3,325개: 우리 꼬리가 붙은 622개 중 146개(23%)가 떼고도 남았다 — 142개가 「만든 파일:」 뒤였다.
    #   그 둘은 **모델도 알아야 하는 사실**(파일이 있다 · 그 줄의 주소)이라 남기고, 사이의 우리 꼬리만 뗀다.
    kept: list[str] = []
    while len(blocks) > 1:
        last = blocks[-1].lstrip()
        if _OUR_TAIL_BLOCK.match(last):
            blocks.pop()
        elif _FACT_TRAILER.match(last):
            kept.append(blocks.pop())
        else:
            break
    return "\n\n".join(blocks + kept[::-1])


def _model_content(record: dict[str, Any]) -> str:
    """모델에게 보낼 내용. 화면에 보인 문장과 모델이 받은 지시가 달랐으면 지시 원문이다.

    이어오기는 짧은 문장을 기록에 남기고 긴 인계문을 모델에 보낸다. 다음 턴이
    기록의 짧은 문장만 읽으면 마지막 요청·남은 할 일을 잊는다.
    """
    metadata = record.get("metadata")
    if str(record.get("role") or "") == "user" and isinstance(metadata, dict):
        hidden = str(metadata.get("model_prompt") or "").strip()
        if hidden:
            return hidden
    if str(record.get("role") or "") == "assistant":
        return without_our_tail(str(record["content"]))
    return str(record["content"])


#: 「그 ○○」 — 사람이 무언가를 **가리킨** 자리. ○○ 가 바로 앞 판에 나온 낱말이면 그것을 가리킨 것이다.
_POINTED_NOUN = re.compile(r"(?:^|[\s\"'「(])그\s+([가-힣A-Za-z0-9]{2,})")
_NOUN_ENDING = re.compile(
    r"(?:이라는|이라고|에서는|에서|으로는|으로|에게|한테|까지|부터|처럼|이랑|이나|이가|은|는|이|가|을|를|의|에|로|도|만|과|와|랑|나)$"
)
#: 「그」 뒤에 와도 가리키는 말이 아닌 것 — 이어 주는 말 · 머뭇거리는 말.
_NOT_A_POINTED_NOUN = frozenset({
    "다음", "다음에", "머라고", "머라고하지", "뭐라고", "뭐라고하지", "뭐지", "머지", "외", "외에", "중", "중에", "때", "때는",
    "뒤", "뒤에", "전에", "후", "후에", "이후", "밖에", "대신", "대로", "만큼", "정도", "이상", "사이", "동안",
    "너가", "니가", "우리", "나는", "내가",
})
#: 가리키되 **옛일을 찾는** 말 — 이때는 오랜 기억이 필요하다.
_ASKS_OLD_MEMORY = re.compile(r"기억|예전|옛날|지난\s*번|지난번|저번|전에\s*(?:말|얘기|이야기|했)|오래\s*전|며칠\s*전|어제|지난\s*주")


def points_at_previous_turn(request: str, previous: str) -> list[str]:
    """요청이 「그 ○○」로 가리킨 것 가운데 **바로 앞 판(질문 · 답)에 실제로 나온 낱말**. 없으면 빈 목록.

    ★ 2026-10-13 네 번 이어 묻기(4B · 창 32K): 「○○의 홍보 전략을 조사해 줘」 다음에 「**그 전략**이 동네 작은 카페와는 어디가
      다른지」라고 묻자, 도구 없이 답하는 길이 **이 PC 의 오랜 기억에 있던 다른 「전략」**으로 답했다(근거 칸 「기억」 · 같은 조건
      다섯 줄기 중 둘). 찾는 말이 요청 문장 하나뿐이라 「전략」이 든 옛 기억이 걸려 왔고, 그것이 「현재 질문과 관련된 기억」이라는
      이름으로 바로 앞 답과 나란히 실렸다. 작은 모델은 이름표가 붙은 쪽을 골랐다. 작은 카드로 쓰는 사람이 말한 「맥락을 못
      읽는다」의 한 갈래다.

      가리킨 것이 눈앞에 있으면 창고를 뒤지지 않는다 — 「그 ○○」의 ○○ 가 바로 앞 판에 있으면 이번 판에는 오랜 기억(배운 사실 ·
      과거 대화 검색)을 싣지 않는다. 늘 붙는 층과 이 대화의 기록은 그대로다.

    좁게 둔다(넣기 전에 운영 대화에 댔다 — 앞 답이 있는 말 1,392개 중 73개):
    - 「그 머라고하지」·「그 다음에」 같은 머뭇거림 · 이음말은 가리키는 말이 아니다. 처음 후보(「그」가 든 말 전부)는 넷 중 하나가
      걸렸다 — 말버릇이 기억을 끄는 스위치가 되면 안 된다.
    - 낱말이 앞 판에 **없으면** 예전 그대로다(「그 회사 주가는」— 앞에서 회사 얘기를 안 했다).
    - 「지난번에 말한 그 전략 기억나?」처럼 옛일을 찾는 말이면 예전 그대로 기억을 싣는다.
    """
    text = " ".join(str(request or "").split())
    if not text or not previous or _ASKS_OLD_MEMORY.search(text):
        return []
    low = str(previous).casefold()
    found: list[str] = []
    for match in _POINTED_NOUN.finditer(text):
        word = match.group(1)
        stem = word
        for _ in range(2):          # 조사가 겹친 말(「행사에는」)까지 — 두 글자는 남긴다
            shorter = _NOUN_ENDING.sub("", stem) if len(stem) > 2 else stem
            if len(shorter) < 2 or shorter == stem:
                break
            stem = shorter
        if len(stem) < 2 or word in _NOT_A_POINTED_NOUN or stem in _NOT_A_POINTED_NOUN:
            continue
        if stem.casefold() in low and stem not in found:
            found.append(stem)
    return found


class ConversationMemory:
    """Bounded SQLite conversation memory. Full images are never stored here — only the small
    preview a user message shows (attachment metadata `thumbnail`, 2026-09-17), never sent to the model."""

    def __init__(
        self,
        path: Path,
        *,
        recent_messages: int = 12,
        max_chars: int = 12000,
        compact_batch: int = 6,
        visual_max_age_sec: float = 3600.0,
    ) -> None:
        self.path = Path(path)
        self.recent_messages = max(2, recent_messages)
        self.max_chars = max(1000, max_chars)
        self.compact_batch = max(2, compact_batch)
        self.visual_max_age_sec = max(30.0, visual_max_age_sec)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'chat',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_session_id
                    ON conversation_messages(session_id, id);

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    session_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    through_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visual_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    focus TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    frame_id INTEGER NOT NULL DEFAULT 0,
                    captured_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_visual_observation_session
                    ON visual_observations(session_id, captured_at DESC);

                CREATE TABLE IF NOT EXISTS memory_documents (
                    message_id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    searchable_text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES conversation_messages(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_documents_session
                    ON memory_documents(session_id, message_id DESC);

                -- ── 사실 서랍 (2026-08-24, P1) ────────────────────────────
                --
                -- 회상은 **대화 조각**을 돌려준다. 조각 넷을 붙여도 "내 이름은
                -- 홍길동"라는 문장이 어디에도 없으면 모델은 답을 못 한다.
                -- 실측: '홍길동' 는 대화에 18건 있는데, 「내 이름이 뭐야」의
                -- 검색어는 ['이름이','뭐야'] 라 하나도 안 겹친다.
                --
                -- 그래서 **사실을 따로 적는다.** 한 줄에 하나.
                --
                -- ★ `source_message_id` 는 NOT NULL 이고 0 이 아니어야 한다.
                --   출처 없는 사실은 저장 자체가 안 된다 — 이 저장소는 「AI가
                --   생성했다」 라벨이 실은 정적 템플릿이었던 것을 두 번 겪었다
                --   (사고 I). provenance 는 주장이 아니라 검증 대상이다.
                --
                -- ★ 틀린 사실은 **지우지 않고 덮는다**(`superseded_by`).
                --   지우면 왜 바뀌었는지가 사라지고, 같은 오해가 다시 들어온다.
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    origin TEXT NOT NULL DEFAULT 'extracted',
                    created_at REAL NOT NULL,
                    superseded_by INTEGER,
                    searchable_text TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_facts_live
                    ON facts(superseded_by, kind, id DESC);
                -- 같은 사실을 두 번 적지 않는다. 대화가 같은 말을 여러 번 해도
                -- 서랍은 한 줄이어야 한다.
                CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique
                    ON facts(kind, subject, fact);
                """
            )
            # ★ 대화 제목 (2026-10-26 대표: 「첫 말 앞부분이라 한눈에 뭔지 모른다」). 대화마다 한 줄인 요약 표에 얹는다 —
            #   대화를 지우면 같이 지워지고(`delete_session`), 요약을 고쳐 써도(`save_summary`) 제목은 그대로다.
            #   `title_source` 는 누가 지었나: model(내 PC 모델) · person(사람이 바꿈). 사람이 바꾼 제목은 모델이 덮지 않는다.
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversation_summaries)")}
            for name, ddl in (
                ("title", "TEXT NOT NULL DEFAULT ''"),
                ("title_source", "TEXT NOT NULL DEFAULT ''"),
                ("title_at", "REAL NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE conversation_summaries ADD COLUMN {name} {ddl}")  # noqa: S608 - 고정 목록
            # Existing conversations predate the retrieval index. Backfill once and
            # keep the table in lock-step from add_message afterwards.
            conn.execute(
                """INSERT OR IGNORE INTO memory_documents
                   (message_id, session_id, role, content, searchable_text, created_at)
                   SELECT id, session_id, role, content, lower(content), created_at
                   FROM conversation_messages"""
            )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        kind: str = "chat",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        session_id = normalize_session_id(session_id)
        role = role if role in {"user", "assistant"} else "assistant"
        created_at = time.time()
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO conversation_messages
                   (session_id, role, content, kind, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, role, content.strip(), kind[:40], _json(metadata or {}), created_at),
            )
            message_id = int(cursor.lastrowid)
            conn.execute(
                """INSERT INTO memory_documents
                   (message_id, session_id, role, content, searchable_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, session_id, role, content.strip(), content.strip().lower(), created_at),
            )
        return message_id

    def add_exchange(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        *,
        kind: str = "chat",
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        user_id = self.add_message(
            session_id, "user", user_text, kind=kind, metadata=user_metadata
        )
        assistant_id = self.add_message(
            session_id,
            "assistant",
            assistant_text,
            kind=kind,
            metadata=assistant_metadata,
        )
        return user_id, assistant_id

    def summary(self, session_id: str) -> dict[str, Any]:
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversation_summaries WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else {"session_id": session_id, "content": "", "through_message_id": 0}

    def recent(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        session_id = normalize_session_id(session_id)
        limit = max(1, min(int(limit or self.recent_messages), 100))
        through_id = int(self.summary(session_id).get("through_message_id") or 0)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM conversation_messages
                   WHERE session_id = ? AND id > ? ORDER BY id DESC LIMIT ?""",
                (session_id, through_id, limit),
            ).fetchall()
        records = [dict(row) for row in reversed(rows)]
        for record in records:
            record["metadata"] = _decode(record.pop("metadata_json", ""), {})
        return records

    def history(self, session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return display history without the context-compaction cutoff.

        Context sent to Gemma remains bounded by ``context_messages``; this method is
        only for the full desktop workspace so an older conversation does not appear
        to have vanished after it was summarized.
        """
        session_id = normalize_session_id(session_id)
        limit = max(1, min(int(limit), 500))
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM conversation_messages
                   WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        records = [dict(row) for row in reversed(rows)]
        for record in records:
            record["metadata"] = _decode(record.pop("metadata_json", ""), {})
        return records

    def delete_session(self, session_id: str) -> dict[str, int]:
        """대화 하나를 지운다 — 목록·대화 기록·요약·회상 문서·관찰 (2026-09-24 사용자 요청: 「채팅창 삭제가 없다」).

        사실 서랍(`facts`)은 지우지 않는다: 여러 대화에서 모인 사실이고, 이 저장소의 원칙이 「틀린 사실은 지우지 않고
        덮는다」이다. 사실을 잊게 하는 길은 따로 있다(`/v1/memory/facts/forget`).
        """
        session_id = normalize_session_id(session_id)
        removed: dict[str, int] = {}
        with self._connection() as conn:
            for table in ("memory_documents", "visual_observations", "conversation_summaries", "conversation_messages"):
                removed[table] = conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,)).rowcount  # noqa: S608 - 표 이름은 위 고정 목록
        return removed

    def list_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """대화 목록. 제목은 지은 것(`set_title`)이 있으면 그것, 없으면 첫 사용자 말.

        ★ 2026-10-26: 앱 안 Claude Agent 가 손자리에게 맡긴 판(via=app)은 제 방(`mcp-…`)을 받지만 **목록에 따로 세우지 않는다** —
          그 판은 맡긴 Claude 대화 안(맡김 카드 · 눈금자)에 이미 보인다. 바깥 클로드 · 코덱스가 맡긴 방은 지금처럼 선다.
          `job_id` 는 첫 질문을 처리한 판 번호 — 화면이 「Claude 대화에 묶인 판」(via 칸이 생기기 전 기록)을 알아본다.
        """
        limit = max(1, min(int(limit), 200))
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM (SELECT
                       m.session_id,
                       COUNT(*) AS message_count,
                       MAX(m.created_at) AS updated_at,
                       COALESCE((
                         SELECT content FROM conversation_messages first_user
                         WHERE first_user.session_id = m.session_id
                           AND first_user.role = 'user'
                         ORDER BY first_user.id ASC LIMIT 1
                       ), '새 대화') AS title,
                       COALESCE((
                         SELECT CASE WHEN json_valid(first_user.metadata_json) THEN json_extract(first_user.metadata_json, '$.caller') END FROM conversation_messages first_user
                         WHERE first_user.session_id = m.session_id
                           AND first_user.role = 'user'
                         ORDER BY first_user.id ASC LIMIT 1
                       ), '') AS caller,
                       COALESCE((
                         SELECT CASE WHEN json_valid(first_user.metadata_json) THEN json_extract(first_user.metadata_json, '$.via') END FROM conversation_messages first_user
                         WHERE first_user.session_id = m.session_id
                           AND first_user.role = 'user'
                         ORDER BY first_user.id ASC LIMIT 1
                       ), '') AS via,
                       COALESCE((
                         SELECT CASE WHEN json_valid(first_user.metadata_json) THEN json_extract(first_user.metadata_json, '$.job_id') END FROM conversation_messages first_user
                         WHERE first_user.session_id = m.session_id
                           AND first_user.role = 'user'
                         ORDER BY first_user.id ASC LIMIT 1
                       ), '') AS job_id,
                       COALESCE((
                         SELECT s.title FROM conversation_summaries s WHERE s.session_id = m.session_id
                       ), '') AS named_title,
                       COALESCE((
                         SELECT s.title_source FROM conversation_summaries s WHERE s.session_id = m.session_id
                       ), '') AS title_source,
                       COALESCE((
                         SELECT content FROM conversation_messages last_message
                         WHERE last_message.session_id = m.session_id
                         ORDER BY last_message.id DESC LIMIT 1
                       ), '') AS preview,
                       EXISTS(
                         SELECT 1 FROM conversation_summaries s
                         WHERE s.session_id = m.session_id AND length(s.content) > 0
                       ) AS has_summary
                   FROM conversation_messages m
                   GROUP BY m.session_id)
                   WHERE via != 'app'
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                **{key: value for key, value in dict(row).items() if key != "named_title"},
                "message_count": int(row["message_count"]),
                "title": str(row["named_title"] or row["title"])[:80],
                "title_source": str(row["title_source"] or ""),
                "via": str(row["via"] or ""),
                "job_id": str(row["job_id"] or ""),
                # 바깥 AI 가 맡긴 대화면 그 호스트 이름(첫 사용자 메시지의 metadata). 없으면 빈 문자열.
                "caller": str(row["caller"] or "")[:80],
                "preview": str(row["preview"])[:160],
                "has_summary": bool(row["has_summary"]),
            }
            for row in rows
        ]

    #: 누가 지은 제목인가. person 이 있으면 model 이 덮지 않는다.
    TITLE_SOURCES = ("model", "person")
    #: 제목 글자 상한 — 한국어 15자 안팎을 바라지만, 영어 제목 · 사람이 바꾼 제목을 자르지 않을 만큼.
    TITLE_MAX_CHARS = 60

    def title_of(self, session_id: str) -> dict[str, str]:
        """지은 제목. 없으면 빈 글 둘."""
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT title, title_source FROM conversation_summaries WHERE session_id = ?", (session_id,)
            ).fetchone()
        return {"title": str(row["title"] or "") if row else "", "source": str(row["title_source"] or "") if row else ""}

    def set_title(self, session_id: str, title: str, *, source: str = "model") -> bool:
        """제목을 단다. 사람이 바꾼 제목(person)은 모델(model)이 덮지 않는다 — 덮지 않았으면 False."""
        session_id = normalize_session_id(session_id)
        clean = " ".join(str(title or "").split()).strip()[: self.TITLE_MAX_CHARS]
        if not clean or source not in self.TITLE_SOURCES:
            return False
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT title_source FROM conversation_summaries WHERE session_id = ?", (session_id,)
            ).fetchone()
            if source == "model" and row and str(row["title_source"] or "") == "person":
                return False
            conn.execute(
                """INSERT INTO conversation_summaries
                   (session_id, content, through_message_id, updated_at, title, title_source, title_at)
                   VALUES (?, '', 0, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     title = excluded.title, title_source = excluded.title_source, title_at = excluded.title_at""",
                (session_id, now, clean, source, now),
            )
        return True

    def titles(self, *, limit: int = 300) -> dict[str, dict[str, str]]:
        """지은 제목 전부(새 것부터) — 화면 저장소에만 있는 Claude 대화도 같은 제목을 받게."""
        limit = max(1, min(int(limit), 1000))
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT session_id, title, title_source FROM conversation_summaries
                   WHERE length(title) > 0 ORDER BY title_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return {str(row["session_id"]): {"title": str(row["title"]), "source": str(row["title_source"] or "")} for row in rows}

    def user_turns(self, session_id: str) -> int:
        """그 대화에서 사람이 한 말의 수 — 「첫 답이 끝났나」를 가른다."""
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ? AND role = 'user'", (session_id,)
            ).fetchone()
        return int(row[0] if row else 0)

    def latest_visual(self, session_id: str, *, max_age_sec: float | None = None) -> dict[str, Any] | None:
        session_id = normalize_session_id(session_id)
        age = self.visual_max_age_sec if max_age_sec is None else max(0.0, max_age_sec)
        with self._connection() as conn:
            row = conn.execute(
                """SELECT * FROM visual_observations
                   WHERE session_id = ? AND captured_at >= ?
                   ORDER BY captured_at DESC LIMIT 1""",
                (session_id, time.time() - age),
            ).fetchone()
        return dict(row) if row else None

    def retrieve(
        self,
        query: str,
        session_id: str,
        *,
        limit: int = 4,
        max_chars: int = 4200,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant older turns without loading another embedding model.

        The score combines exact phrase and Korean/English term overlap. This keeps
        Gemma resident on the 3090; a future embedding backend can replace the
        scorer without changing the context contract.
        """
        session_id = normalize_session_id(session_id)
        terms = _search_terms(query)
        if not terms:
            return []
        recent_ids = {int(row["id"]) for row in self.recent(session_id)}
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT message_id, session_id, role, content, searchable_text, created_at
                   FROM memory_documents ORDER BY message_id DESC LIMIT 1200"""
            ).fetchall()

        normalized_query = " ".join(str(query or "").lower().split())
        candidates: list[dict[str, Any]] = []
        newest_id = int(rows[0]["message_id"]) if rows else 1
        # ★ 분모는 **낱말 수**지 꼴의 수가 아니다. 위 `_term_groups` 주석 참고.
        groups = _term_groups(query)
        for row in rows:
            message_id = int(row["message_id"])
            if row["session_id"] == session_id and message_id in recent_ids:
                continue
            searchable = str(row["searchable_text"])
            matched = [
                next(form for form in group if form in searchable)
                for group in groups
                if any(form in searchable for form in group)
            ]
            if not matched:
                continue
            exact = len(normalized_query) >= 6 and normalized_query in searchable
            coverage = len(matched) / max(1, len(groups))
            strongest = max(len(term) for term in matched)
            if not exact and coverage < 0.34 and strongest < 4:
                continue
            score = coverage * 10 + sum(min(len(term), 8) for term in matched) * 0.45
            if exact:
                score += 12
            if row["role"] == "user":
                score += 0.8
            if row["session_id"] == session_id:
                score += 0.6
            score += max(0.0, 1.0 - ((newest_id - message_id) / max(1, newest_id)))
            candidates.append({**dict(row), "score": round(score, 3), "matched_terms": matched})

        candidates.sort(key=lambda item: (-float(item["score"]), -int(item["message_id"])))
        selected: list[dict[str, Any]] = []
        used = 0
        for item in candidates:
            content = str(item["content"]).strip()
            remaining = max_chars - used
            if remaining < 240:
                break
            if len(content) > min(1200, remaining):
                content = content[: min(1200, remaining)].rstrip() + "…"
            selected.append({**item, "content": content})
            used += len(content)
            if len(selected) >= max(1, min(limit, 10)):
                break
        return selected

    def context_messages(
        self,
        session_id: str,
        *,
        query: str = "",
        retrieval_limit: int = 4,
        retrieval_max_chars: int = 4200,
    ) -> list[dict[str, str]]:
        summary = self.summary(session_id)
        recent = self.recent(session_id)
        messages: list[dict[str, str]] = []
        summary_text = str(summary.get("content") or "").strip()
        if summary_text:
            messages.append({"role": "system", "content": f"이전 대화의 누적 요약:\n{summary_text}"})
        # ── 질문에 걸린 **사실**을 먼저 (2026-08-24, P4) ─────────────────────
        #
        # 조각 넷보다 사실 한 줄이 낫다. "사용자 이름은 홍길동" 한 줄이면 답이
        # 되지만, 그 이름이 안 든 대화 조각은 몇 개를 붙여도 답이 안 된다.
        #
        # ★ 항상 붙는 층(`learned_block`)에 이미 실린 것은 **뺀다.** 같은 줄이
        #   시스템 프롬프트와 여기에 두 번 나오면 토큰이 아니라 주의를 두 번 먹는다.
        # ★ 사람이 **바로 앞 판의 그것**을 가리켰으면 오랜 기억을 싣지 않는다 (2026-10-13 · `points_at_previous_turn` 의 설명).
        #   이번 요청이 기록에 먼저 들어와 있을 수 있다 — 그것은 「앞 판」이 아니다(자기 말에서 낱말을 찾으면 늘 걸린다).
        asked = " ".join(str(query or "").split())
        earlier = [record for record in recent if asked and asked not in " ".join(_model_content(record).split())]
        in_view = points_at_previous_turn(query, "\n".join(_model_content(record) for record in earlier[-2:])) if query else []
        already = {int(row["id"]) for row in self.live_facts(kinds=self.LEARNED_KINDS, limit=300)}
        matched_facts = [
            row for row in self.search_facts(query, limit=6)
            if int(row["id"]) not in already
            and not fact_extract.ephemeral_session(str(row.get("session_id") or ""))  # 임시 방에서 배운 것은 싣지 않는다
        ] if query and not in_view else []
        if matched_facts:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "현재 질문과 관련해 **이전에 배운 사실**이다. 틀릴 수 있으니 "
                        "사용자의 지금 말과 어긋나면 지금 말을 따라라.\n"
                        + "\n".join(f"- {row['subject']}: {row['fact']}" for row in matched_facts)
                    ),
                }
            )
        recalled = self.retrieve(
            query,
            session_id,
            limit=retrieval_limit,
            max_chars=retrieval_max_chars,
        ) if query and not in_view else []
        if recalled:
            lines = []
            for item in recalled:
                observed = time.strftime("%Y-%m-%d", time.localtime(float(item["created_at"])))
                lines.append(
                    f"[{observed} · {item['role']} · 세션 {item['session_id']}] {item['content']}"
                )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        RECALLED_MEMORY_HEADER
                        + "현재 질문과 충돌하면 사용자의 최신 말을 우선하고, 기억에 없는 사실은 만들지 마라.\n"
                        + "\n".join(lines)
                    ),
                }
            )
        visual = self.latest_visual(session_id)
        if visual:
            observed_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(visual["captured_at"])))
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"최근 카메라 관찰({observed_at}, 대상: {visual['focus']}): "
                        f"{str(visual['summary'])[:1000]}\n"
                        "과거 관찰에 관한 질문에는 활용하되, 현재 상태를 묻는다면 카메라를 다시 확인한다."
                    ),
                }
            )

        budget = self.max_chars - sum(len(item["content"]) for item in messages)
        selected: list[dict[str, str]] = []
        for record in reversed(recent):
            content = _model_content(record)
            if selected and len(content) > budget:
                break
            if not selected and len(content) > budget:
                content = content[-max(500, budget):]
            selected.append({"role": str(record["role"]), "content": content})
            budget -= len(content)
            if budget <= 0:
                break
        messages.extend(reversed(selected))
        return messages

    # ═══════════════════════════════════════════════════════════════════════
    # 사실 서랍 (2026-08-24, P1)
    # ═══════════════════════════════════════════════════════════════════════

    #: 사실의 갈래. **닫힌 목록**이다 — 아무 이름이나 받으면 서랍이 곧 잡동사니가
    #: 되고, 「항상 붙이는 층」이 무엇을 골라야 할지 판단할 수 없게 된다.
    # "code" 는 **저장소의 그 자리**에 대한 사실이다. 사람에 관한 것과 갈래를
    # 나눠 둬야, 코드 판에서 배운 것이 사용자의 영구 취향으로 박히지 않는다.
    FACT_KINDS: tuple[str, ...] = (
        "person", "product", "preference", "ongoing", "reference", "code",
    )

    #: 사실 한 줄의 상한. 길면 그건 사실이 아니라 요약이고, 요약은 이미 다른
    #: 자리(`conversation_summaries`)가 맡고 있다.
    FACT_MAX_CHARS = 200

    def add_fact(
        self,
        *,
        kind: str,
        subject: str,
        fact: str,
        source_message_id: int,
        session_id: str = "",
        origin: str = "extracted",
    ) -> int:
        """사실 한 줄을 넣는다. 이미 같은 것이 있으면 그 id 를 돌려준다.

        ## 거절하는 것들

        ★ **출처 없는 사실은 안 받는다.** `source_message_id` 가 0 이하면
          `ValueError` 다. 이 저장소는 「AI가 생성했다」 라벨이 실은 정적
          템플릿이었던 것을 두 번 겪었다(사고 I, 그리고 재발). 그때 배운 것은
          **provenance 는 주장이 아니라 검증 대상**이라는 것이고, 검증하려면
          되짚을 자리가 있어야 한다.

          손으로 넣는 사실(`origin="manual"`)만 예외다. 그건 사람이 출처다.

        갈래가 목록에 없어도 거절한다. 길이가 넘어도 거절한다. 조용히 자르지
        않는 이유는, 잘린 사실이 **틀린 사실**이 되기 때문이다 —
        "사용자는 여수로 사무실을 옮겼고 그 전에는" 에서 끊기면 뜻이 바뀐다.
        """
        kind = str(kind or "").strip().lower()
        subject = " ".join(str(subject or "").split())
        fact = " ".join(str(fact or "").split())
        if kind not in self.FACT_KINDS:
            raise ValueError(f"모르는 갈래입니다: {kind!r} (쓸 수 있는 것: {self.FACT_KINDS})")
        if not subject or not fact:
            raise ValueError("subject 와 fact 는 비어 있을 수 없습니다")
        if len(fact) > self.FACT_MAX_CHARS:
            raise ValueError(
                f"사실 한 줄이 너무 깁니다({len(fact)}자 > {self.FACT_MAX_CHARS}). "
                "긴 것은 사실이 아니라 요약입니다 — 잘라서 넣으면 뜻이 바뀝니다."
            )
        if origin != "manual" and int(source_message_id) <= 0:
            raise ValueError(
                "출처 없는 사실은 저장하지 않습니다. 어느 메시지에서 나왔는지 "
                "적을 수 없다면, 그건 대화에서 나온 것이 아닙니다."
            )
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id FROM facts WHERE kind = ? AND subject = ? AND fact = ?",
                (kind, subject, fact),
            ).fetchone()
            if row:
                return int(row["id"])
            cursor = conn.execute(
                """INSERT INTO facts
                   (kind, subject, fact, source_message_id, session_id, origin,
                    created_at, superseded_by, searchable_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (kind, subject, fact, int(source_message_id), normalize_session_id(session_id),
                 origin, now, f"{subject} {fact}".lower()),
            )
            return int(cursor.lastrowid)

    #: **항상 붙는 층**의 상한. 여기 한 자리에만 둔다.
    #:
    #: ★ 오늘(2026-08-24) 상한이 세 군데 흩어져 낮은 쪽만 일한 것을 네 번 겪었다
    #:   (dataclass 기본값 · 환경변수 로더 · 함수 안 하드 상수). 그래서 이 값은
    #:   **한 자리**에 있고, 검사가 그 자리를 지킨다.
    #:
    #: 왜 1,200 인가 — 실측으로 정했다. 지금 한 턴에 이미 10,454자가 들어간다
    #: (요약 1,321 · 회상 3,080 · 최근 대화 6,053). 1,200자는 그 위 11% 이고
    #: 128K 창의 0.5% 다. **토큰은 문제가 아니다.** 문제는 주의다 — 「지금 몇
    #: 시야」에 사실 150개가 딸려가면 그건 토큰이 아니라 주의를 먹는다. 스킬
    #: 61종을 상시 색인 **안 한** 이유가 정확히 이것이다.
    LEARNED_MAX_CHARS = 1_200

    #: 항상 붙일 갈래와 그 순서. `ongoing` 은 자리가 남을 때만 — 자주 바뀌고,
    #: 바뀌는 것이 앞에 있으면 프리필 캐시가 더 자주 깨진다.
    LEARNED_KINDS: tuple[str, ...] = ("person", "product", "preference", "ongoing")

    _KIND_LABEL = {
        "person": "사람",
        "product": "우리 것",
        "preference": "일하는 방식",
        "ongoing": "진행 중",
        "reference": "참고",
    }

    def learned_block(self, *, max_chars: int | None = None) -> str:
        """시스템 프롬프트에 **항상** 붙는 「배운 것」. 없으면 빈 글자.

        ## 프로필과 왜 갈라 놓는가

        `<jarvis-profile>` 은 **사람이 직접 관리**하는 것이라 권위가 있다.
        여기 있는 것은 **자비스가 대화에서 배운 것**이라 틀릴 수 있다. 둘을 같은
        무게로 믿으면, 잘못 배운 한 줄이 사람이 적어 둔 사실을 이긴다.

        그래서 블록을 나누고, 안에도 그렇게 적는다.

        ## 잘릴 때는 **잘렸다고 말한다**

        상한에 걸리면 조용히 자르지 않는다. 침묵으로 오는 잘림이 제일 나쁘다는
        것을 이 저장소는 사고 Q 에서 배웠다 — 본문의 23%가 그렇게 사라졌고
        아무도 몰랐다.
        """
        cap = self.LEARNED_MAX_CHARS if max_chars is None else int(max_chars)
        # ★ 임시 방(측정 · 바깥 AI 의 과제)에서 배운 것은 **싣지 않는다** (2026-10-08). 그 방에서는 이제 배우지도 않지만
        #   (`fact_extract.ephemeral_session`), 이미 들어가 있는 것이 살아 있는 사실의 37%였다. 지우지 않고 여기서 거른다 —
        #   서랍은 그대로라 되돌릴 수 있고, 사람이 화면에서 보고 지울 수 있다.
        rows = [
            row for row in self.live_facts(kinds=self.LEARNED_KINDS, limit=1200)
            if not fact_extract.ephemeral_session(str(row.get("session_id") or ""))
        ][:300]
        if not rows:
            return ""

        # 갈래 순서대로. 같은 갈래 안에서는 최신이 먼저 — 사람이 최근에 말한
        # 것이 대개 더 맞다.
        order = {kind: at for at, kind in enumerate(self.LEARNED_KINDS)}
        rows.sort(key=lambda row: (order.get(str(row["kind"]), 99), -int(row["id"])))

        lines: list[str] = []
        used = 0
        dropped = 0
        current = ""
        for row in rows:
            kind = str(row["kind"])
            piece = f"- {row['subject']}: {row['fact']}"
            head = "" if kind == current else f"[{self._KIND_LABEL.get(kind, kind)}]\n"
            cost = len(head) + len(piece) + 1
            if used + cost > cap:
                dropped += 1
                continue
            if head:
                lines.append(head.rstrip("\n"))
                current = kind
            lines.append(piece)
            used += cost

        if not lines:
            return ""
        body = "\n".join(lines)
        note = ""
        if dropped:
            note = f"\n(자리가 모자라 {dropped}줄은 안 실었다. 필요하면 물어봐라.)"
        return (
            "다음은 네가 이전 대화에서 **배운 것**이다. 사용자가 직접 관리하는 "
            "프로필과 달리 **틀릴 수 있으니**, 사용자가 지금 하는 말과 어긋나면 "
            "지금 말을 따르고 배운 것은 낡은 것으로 취급해라. "
            # ★ 2026-09-17: 모델이 이 블록을 「상시 프로필」이라고 불렀다. 사람은 「프로필에서 걷어냈는데?」가 된다.
            "사용자에게 출처를 말할 때는 「대화에서 배운 기억」이라고 부르고, 상시 프로필이라고 부르지 마라.\n"
            f"<jarvis-learned>\n{body}{note}\n</jarvis-learned>"
        )

    def supersede_fact(self, old_id: int, new_id: int | None = None) -> None:
        """틀린 사실을 **덮는다**(지우지 않는다).

        `new_id` 가 없으면 「그냥 틀렸다」는 뜻으로 자기 id 를 적는다 — 그래야
        「아직 안 덮였다(NULL)」와 구별된다. 빈 값이 두 가지를 뜻하면 조용히
        고장 난다는 것을 이 저장소는 여러 번 배웠다.
        """
        with self._connection() as conn:
            conn.execute(
                "UPDATE facts SET superseded_by = ? WHERE id = ?",
                (int(new_id) if new_id else int(old_id), int(old_id)),
            )

    def facts_with_sources(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """배운 사실 + **그 근거가 된 말.**

        ★ 출처를 같이 안 주면 사람이 고칠 수가 없다. "사무실은 부산에 있다"만
          보여 주면 그게 왜 들어왔는지 알 수 없고, 지울지 말지도 못 정한다.
          어느 대화의 어느 말에서 나왔는지를 보여 줘야 판단이 선다.

        `source_message_id` 를 필수로 만든 이유가 여기서 값을 한다 — 저장할 때의
        규율이 고칠 때의 근거가 된다.
        """
        rows = self.live_facts(limit=limit)
        if not rows:
            return []
        ids = sorted({int(row["source_message_id"]) for row in rows if row["source_message_id"]})
        sources: dict[int, dict[str, Any]] = {}
        if ids:
            with self._connection() as conn:
                for found in conn.execute(
                    f"""SELECT id, role, content, created_at, session_id
                        FROM conversation_messages WHERE id IN ({','.join('?' * len(ids))})""",
                    ids,
                ):
                    sources[int(found["id"])] = {
                        "role": str(found["role"]),
                        # 근거는 **한 줄이면 된다.** 사람이 "아 그때 그 말" 하고
                        # 알아보면 충분하고, 길면 목록이 못 읽게 된다.
                        "excerpt": " ".join(str(found["content"]).split())[:160],
                        "created_at": float(found["created_at"]),
                        "session_id": str(found["session_id"]),
                    }
        out: list[dict[str, Any]] = []
        for row in rows:
            source = sources.get(int(row["source_message_id"] or 0))
            out.append(
                {
                    "id": int(row["id"]),
                    "kind": str(row["kind"]),
                    "subject": str(row["subject"]),
                    "fact": str(row["fact"]),
                    "origin": str(row["origin"]),
                    "created_at": float(row["created_at"]),
                    "source_message_id": int(row["source_message_id"] or 0),
                    # 출처를 못 찾는 경우가 있다(오래돼 지워졌다든지). **비었다고
                    # 숨기지 않는다** — 근거를 못 보여 주는 사실이 있다는 것 자체가
                    # 사람이 알아야 할 정보다.
                    "source": source,
                }
            )
        return out

    def live_facts(
        self, *, kinds: Sequence[str] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """아직 유효한 사실들. 덮인 것은 안 나온다.

        최신이 먼저다 — 사람이 최근에 말한 것이 대개 더 맞다.
        """
        query = "SELECT * FROM facts WHERE superseded_by IS NULL"
        params: list[Any] = []
        if kinds:
            query += f" AND kind IN ({','.join('?' * len(kinds))})"
            params.extend(kinds)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._connection() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    CODE_NOTE_KIND = "code"

    def add_code_note(
        self,
        *,
        path: str,
        note: str,
        source_message_id: int,
        session_id: str = "",
        origin: str = "learned",
    ) -> int:
        """이 저장소의 **이 경로**에 대해 알게 된 것을 남긴다.

        경로에 붙이는 이유: 「gemma_bundle 은 자동 생성물이라 직접 고치면 다음
        sync 때 사라진다」 같은 지식은 사람의 취향이 아니라 **그 자리의 성질**
        이다. 전역 선호로 넣으면 엉뚱한 판에서 튀어나오고, 정작 그 폴더를 열
        때는 안 나온다.
        """
        cleaned = str(path or "").replace("\\", "/").strip()
        cleaned = cleaned if cleaned == "." else cleaned.strip("/")
        if not cleaned:
            raise ValueError("path_required")
        return self.add_fact(
            kind=self.CODE_NOTE_KIND,
            subject=cleaned,
            fact=str(note or "").strip(),
            source_message_id=source_message_id,
            session_id=session_id,
            origin=origin,
        )

    def code_notes_for(
        self, paths: list[str], *, limit: int = 8
    ) -> list[dict[str, Any]]:
        """이 경로들에 대해 아는 것. 경로 자체와 **상위 폴더**까지 본다.

        `src/alture_jarvis/agent.py` 를 열면 그 파일에 붙은 것뿐 아니라
        `src/alture_jarvis` 에 붙은 것도 같이 올라와야 한다.
        """
        # 저장소 전체에 걸리는 노트는 어떤 경로를 물어도 같이 나온다.
        wanted: set[str] = {"."}
        for raw in paths:
            cleaned = str(raw or "").replace("\\", "/").strip().strip("/")
            if not cleaned:
                continue
            parts = cleaned.split("/")
            for index in range(len(parts), 0, -1):
                wanted.add("/".join(parts[:index]))
        if not wanted:
            return []
        found: list[dict[str, Any]] = []
        for row in self.live_facts(limit=500):
            if str(row.get("kind")) != self.CODE_NOTE_KIND:
                continue
            subject = str(row.get("subject") or "").strip().strip("/")
            if subject in wanted:
                found.append(
                    {
                        "path": subject,
                        "note": str(row.get("fact") or ""),
                        "fact_id": row.get("id"),
                    }
                )
            if len(found) >= limit:
                break
        return found

    def search_facts(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        """사실 중에서 낱말이 겹치는 것. 회상이 조각과 **함께** 쓴다 (P4).

        사실은 짧아서 낱말 겹침이 조각보다 훨씬 잘 듣는다 — "사용자 이름은
        홍길동다" 한 줄에 '이름'이 들어 있으므로, 조각에서는 못 찾던 것이
        여기서는 걸린다.
        """
        terms = _search_terms(query)
        if not terms:
            return []
        found: list[dict[str, Any]] = []
        for row in self.live_facts(limit=500):
            text = str(row["searchable_text"])
            matched = [term for term in terms if term in text]
            if not matched:
                continue
            score = sum(min(len(term), 8) for term in matched) + len(matched) * 2
            found.append({**row, "score": score, "matched_terms": matched})
        found.sort(key=lambda item: (-item["score"], -int(item["id"])))
        return found[:limit]

    def compaction_candidate(self, session_id: str) -> dict[str, Any] | None:
        session_id = normalize_session_id(session_id)
        current = self.summary(session_id)
        through_id = int(current.get("through_message_id") or 0)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT id, role, content, metadata_json FROM conversation_messages
                   WHERE session_id = ? AND id > ? ORDER BY id""",
                (session_id, through_id),
            ).fetchall()
        if len(rows) <= self.recent_messages + self.compact_batch:
            return None
        compact_rows = rows[: -self.recent_messages]
        return {
            "session_id": session_id,
            "previous_summary": str(current.get("content") or ""),
            "through_message_id": int(compact_rows[-1]["id"]),
            # 요약도 모델이 실제로 받은 지시로 만든다 — 인계문이 요약에서 빠지면
            # 대화가 길어진 뒤에 카드가 사라진다.
            "messages": [
                {
                    "role": row["role"],
                    "content": _model_content({
                        "role": row["role"], "content": row["content"],
                        "metadata": _decode(row["metadata_json"] or "", {}),
                    }),
                }
                for row in compact_rows
            ],
        }

    def save_summary(self, session_id: str, content: str, through_message_id: int) -> None:
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO conversation_summaries
                   (session_id, content, through_message_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     content = excluded.content,
                     through_message_id = MAX(conversation_summaries.through_message_id, excluded.through_message_id),
                     updated_at = excluded.updated_at""",
                (session_id, content.strip()[:6000], int(through_message_id), time.time()),
            )

    def add_visual(
        self,
        session_id: str,
        *,
        focus: str,
        summary: str,
        frame_id: int,
        captured_at: float,
    ) -> int:
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO visual_observations
                   (session_id, focus, summary, frame_id, captured_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, focus[:300], summary.strip()[:3000], int(frame_id), captured_at, time.time()),
            )
        return int(cursor.lastrowid)

    def inspect(self, session_id: str) -> dict[str, Any]:
        session_id = normalize_session_id(session_id)
        with self._connection() as conn:
            message_count = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            visual_count = conn.execute(
                "SELECT COUNT(*) FROM visual_observations WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            searchable_count = conn.execute(
                "SELECT COUNT(*) FROM memory_documents"
            ).fetchone()[0]
        summary = self.summary(session_id)
        return {
            "session_id": session_id,
            "message_count": int(message_count),
            "visual_observation_count": int(visual_count),
            "searchable_memory_count": int(searchable_count),
            "summary": str(summary.get("content") or ""),
            "summary_through_message_id": int(summary.get("through_message_id") or 0),
            "recent": self.recent(session_id),
            "latest_visual": self.latest_visual(session_id),
        }
