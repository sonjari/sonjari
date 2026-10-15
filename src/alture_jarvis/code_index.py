from __future__ import annotations

import ast
import fnmatch
import functools
import hashlib
import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .config import setting

CODE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".ps1": "powershell",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
}

SKIP_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    # ★ 산출물은 소스가 아니다 (2026-08-28 실측).
    # `tools/alture-jarvis/outputs` 하나가 16GB · 12,588 파일이었고 그중 11,633 개가
    # 코드 확장자였다 — 벤치가 저장소를 통째로 복사해 두기 때문이다. 훑는 시간도
    # 시간이지만, 그 사본이 색인에 들어가면 검색이 진짜 소스 대신 사본을 집는다.
    # (읽기는 그대로 된다 — 여기서 빼는 것은 **색인**뿐이다.)
    "outputs",
}

SENSITIVE_NAMES = re.compile(
    r"^(?:\.env(?:\..*)?|id_(?:rsa|ed25519)|credentials\.json)$|"
    r"(?:client_secret|control\.token|token\.dpapi|\.p12$|\.pfx$|\.pem$)",
    re.IGNORECASE,
)

SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|enum|struct|trait)\s+"
    r"([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
IMPORT_RE = re.compile(
    r"(?:from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\)|"
    r"use\s+([A-Za-z_][\w:]*)|mod\s+([A-Za-z_][\w]*))"
)

#: 참조 그래프를 만들 때 쓰는 식별자. 심볼 이름의 주인을 역추적한다.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")

QUERY_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*|[가-힣]{2,}")
QUERY_STOP_WORDS = {
    "그다음", "이제", "한번", "해줘", "해주세요", "코드", "파일", "수정",
    "추가", "패치", "문제", "작업", "프로젝트", "에서", "으로", "the", "and",
    "for", "with", "this", "that", "code", "file", "fix", "change", "please",
}



#: 폴더 전체가 이 글자 수 이하면 「작은 폴더」다 — 파일 읽기 도구의 기본 상한(`local_computer.SURVEY_READ_CHARS`)과 같은 값.
#: 그보다 작으면 통째로 읽는 것이 줄 범위를 골라 읽는 것보다 싸다. (값이 갈리면 시험이 잡는다.)
WHOLE_FOLDER_READ_CHARS = 15_000
#: 작은 폴더의 지도 머리말. 이 머리말이면 지도가 **그 폴더의 파일 전부**다.
SMALL_FOLDER_CARD_HEAD = "[저장소 지도 — 이 폴더의 파일은 이것이 전부다] 고치기 전에 열어서 읽어라."

class CodeIndex:
    """저장소 밖 SQLite에 mtime/hash 기반 코드 지도를 증분 유지한다."""

    def __init__(self, storage_root: Path) -> None:
        #: 마지막 따라잡기가 어떻게 끝났나 — 시간 상한에 걸렸으면 도구 결과가 그 사실을 말한다(`local_computer`).
        self.last_refresh: dict[str, Any] = {}
        self.storage_root = storage_root.resolve(strict=False)

    def _database_path(self, root: Path) -> Path:
        key = hashlib.sha256(str(root).lower().encode("utf-8")).hexdigest()[:20]
        self.storage_root.mkdir(parents=True, exist_ok=True)
        return self.storage_root / f"{key}.sqlite3"

    @staticmethod
    def _gitignore_patterns(root: Path) -> list[str]:
        target = root / ".gitignore"
        if not target.is_file():
            return []
        patterns: list[str] = []
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return patterns
        for raw in lines:
            value = raw.strip()
            if not value or value.startswith("#") or value.startswith("!"):
                continue
            patterns.append(value.lstrip("/"))
        return patterns

    @staticmethod
    @functools.lru_cache(maxsize=8)
    def _ignore_matchers(patterns: tuple[str, ...]) -> tuple["re.Pattern[str] | None", "re.Pattern[str] | None"]:
        """`.gitignore` 규칙을 **한 번** 정규식 둘로 굳힌다 — 경로 전체용, 경로 조각용.

        ★ 2026-09-28 코드 모드 「아무것도 안 된다」. 모노레포 `.gitignore` 가 규칙 약 380줄이라
        파일마다 fnmatch 를 규칙 수 × 3번 불렀다(첫 색인 한 번에 560만 번). 캐시가 따뜻해도 색인
        24초 중 20초가 여기였다. 뜻은 예전 그대로다 — 윈도우의 fnmatch 처럼 대소문자를 안 가린다.
        """
        flags = re.IGNORECASE if os.name == "nt" else 0
        whole: list[str] = []
        parts: list[str] = []
        for pattern in patterns:
            normalized = pattern.rstrip("/")
            whole.append(fnmatch.translate(normalized))
            whole.append(fnmatch.translate(f"{normalized}/**"))
            if "/" not in normalized:
                parts.append(fnmatch.translate(normalized))
        compile_any = lambda items: re.compile("|".join(f"(?:{item})" for item in items), flags) if items else None  # noqa: E731
        return compile_any(whole), compile_any(parts)

    @classmethod
    def _ignored(cls, relative: str, patterns: list[str]) -> bool:
        whole, parts = cls._ignore_matchers(tuple(patterns))
        path = relative.replace("\\", "/")
        if whole is not None and whole.match(path):
            return True
        return parts is not None and any(parts.match(part) for part in path.split("/"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _python_facts(text: str) -> tuple[list[dict[str, Any]], list[str]]:
        symbols: list[dict[str, Any]] = []
        imports: list[str] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return symbols, imports
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(
                    {"name": node.name, "kind": type(node).__name__, "line": node.lineno}
                )
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return symbols[:500], sorted(set(imports))[:500]

    @staticmethod
    def _generic_facts(text: str) -> tuple[list[dict[str, Any]], list[str]]:
        symbols = [
            {"name": match.group(1), "kind": "symbol", "line": text.count("\n", 0, match.start()) + 1}
            for match in SYMBOL_RE.finditer(text)
        ][:500]
        imports = sorted(
            {
                value
                for match in IMPORT_RE.finditer(text)
                for value in match.groups()
                if value
            }
        )[:500]
        return symbols, imports

    # ── 운동장: 파일이 아니라 덩어리를 색인한다 ─────────────────────────
    #
    # 예전 색인은 **경로·심볼 이름·import 만** 담았다. 본문은 한 글자도 안
    # 들어갔다. 그래서 한글로 증상을 말하면 영문 심볼과 한 조각도 안 겹쳐
    # `semantic_fallback`(= src 파일을 경로순으로)으로 떨어졌다. 2026-08-27
    # 실측: 24개 질의 중 19개를 **아예 못 찾았고** recall@5 가 0.0% 였다.
    #
    # 덩어리로 자르는 이유는 둘이다. 하나는 8,000줄짜리 browser.py 가 통째로
    # 하나의 후보가 되면 "찾았다"가 아무 뜻이 없기 때문이고, 둘은 나중에 정찰기
    # 에게 **이름 대신 실제 코드 조각**을 줘야 하기 때문이다.

    @staticmethod
    def _python_chunks(text: str) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        lines = text.splitlines()
        chunks: list[dict[str, Any]] = []
        module_doc = ast.get_docstring(tree) or ""
        if module_doc:
            chunks.append(
                {
                    "kind": "module",
                    "symbol": "",
                    "start_line": 1,
                    "end_line": min(len(lines), module_doc.count(chr(10)) + 3),
                    "signature": "",
                    "doc": module_doc[:4000],
                    "text": module_doc[:4000],
                }
            )

        def emit(node: Any, prefix: str = "") -> None:
            start = int(getattr(node, "lineno", 1))
            end = int(getattr(node, "end_lineno", start) or start)
            name = f"{prefix}{node.name}"
            body = chr(10).join(lines[start - 1 : end])
            chunks.append(
                {
                    "kind": type(node).__name__.replace("Def", "").lower(),
                    "symbol": name,
                    "start_line": start,
                    "end_line": end,
                    "signature": (lines[start - 1].strip() if start <= len(lines) else "")[:300],
                    "doc": (ast.get_docstring(node) or "")[:2000],
                    "text": body[:8000],
                }
            )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                emit(node)
            elif isinstance(node, ast.ClassDef):
                emit(node)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        emit(child, prefix=f"{node.name}.")
        return chunks[:400]

    @staticmethod
    def _generic_chunks(text: str, *, window: int = 120) -> list[dict[str, Any]]:
        """파이썬이 아닌 파일은 줄 창으로 자른다. 문서·설정도 근거가 된다."""
        lines = text.splitlines()
        chunks: list[dict[str, Any]] = []
        for start in range(0, len(lines), window):
            body = chr(10).join(lines[start : start + window])
            if not body.strip():
                continue
            heading = next(
                (line.strip() for line in lines[start : start + window] if line.strip()),
                "",
            )
            chunks.append(
                {
                    "kind": "block",
                    "symbol": "",
                    "start_line": start + 1,
                    "end_line": min(len(lines), start + window),
                    "signature": heading[:300],
                    "doc": "",
                    "text": body[:8000],
                }
            )
            if len(chunks) >= 200:
                break
        return chunks

    @classmethod
    def _chunks_for(cls, text: str, language: str) -> list[dict[str, Any]]:
        if language == "python":
            chunks = cls._python_chunks(text)
            if chunks:
                return chunks
        return cls._generic_chunks(text)


    # ── FTS: 본문을 실제로 검색한다 ──────────────────────────────────────
    #
    # 토크나이저는 재서 정한다. unicode61 은 낱말 단위(한글은 조사가 붙은 채
    # 한 낱말), trigram 은 부분일치까지 되지만 세 글자 이상만 쓸 수 있다.
    # 2026-08-27 A/B 실측(24개 질의):
    #   unicode61  문서티어 @5 78.6% / 증상티어 @5 20.0%
    #   trigram    문서티어 @5 71.4% / 증상티어 @5 40.0%
    # 서로 다른 것을 잘한다. 하나를 고르지 않고 **둘 다 색인해 RRF 로 합친다.**
    FTS_TOKENIZERS = ("unicode61", "trigram")

    @staticmethod
    def _tune(db: sqlite3.Connection) -> sqlite3.Connection:
        """색인 DB 는 **소스에서 언제든 다시 만들 수 있다.** 그래서 안전 대신 속도.

        2026-08-28 프로파일: 콜드 색인 521.8초 중 **sqlite execute 가 306.4초(59%)**
        였다. PRAGMA 가 하나도 없어 기본값(journal=delete, synchronous=FULL)으로
        돌았고, 청크 하나당 3번씩 총 386,632 번을 매번 fsync 하며 썼다.

        최악의 경우 잃는 것은 색인뿐이고, 다음 refresh 가 다시 만든다.
        """
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=OFF",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-65536",
        ):
            try:
                db.execute(pragma)
            except sqlite3.DatabaseError:
                # 다른 프로세스가 쥐고 있으면 journal_mode 전환이 거절될 수 있다.
                # 그때는 그냥 기본값으로 도는 게 맞다 — 느릴 뿐 틀리지 않는다.
                pass
        return db

    @classmethod
    def _ensure_chunk_tables(cls, db: sqlite3.Connection) -> None:
        db.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL, language TEXT NOT NULL,
                kind TEXT NOT NULL, symbol TEXT NOT NULL,
                start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
                signature TEXT NOT NULL, doc TEXT NOT NULL, text TEXT NOT NULL
            )"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")
        for tokenizer in cls.FTS_TOKENIZERS:
            db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts_{tokenizer} USING fts5("
                "body, path UNINDEXED, chunk_id UNINDEXED, "
                f"tokenize='{tokenizer}')"
            )

    @staticmethod
    def _safe(value: Any) -> str:
        """짝 없는 서러게이트를 지운다.

        윈도우 파일 이름이나 깨진 원문에서 올라온 로운 서러게이트는 sqlite 에
        넣는 순간 UnicodeEncodeError 로 색인 전체를 죽인다. 한 파일 때문에
        저장소 전체 색인이 실패하는 것은 너무 비싸다.
        """
        text = str(value or "")
        return text.encode("utf-8", "replace").decode("utf-8", "replace")

    @staticmethod
    def _fts_body(path: str, chunk: dict[str, Any]) -> str:
        parts = [
            path.replace("/", " ").replace("_", " "),
            str(chunk.get("symbol") or "").replace("_", " "),
            str(chunk.get("signature") or ""),
            str(chunk.get("doc") or ""),
            str(chunk.get("text") or "")[:6000],
        ]
        return chr(10).join(part for part in parts if part)

    @classmethod
    def _replace_chunks(
        cls, db: sqlite3.Connection, path: str, language: str, chunks: list[dict[str, Any]]
    ) -> None:
        # ★ 옛 조각은 **파일당 한 번**에 지운다 (2026-10-06 대표 실사용: 「이 파일 열어 줘」 한마디에 색인이 2분).
        #
        #   예전에는 옛 조각 하나마다 `DELETE … WHERE chunk_id = ?` 를 불렀다. 그런데 FTS 표의 `chunk_id` 는
        #   UNINDEXED 라 그 한 줄이 **표 전체를 훑는다.** 운영 색인(조각 31,965개) 사본에서 재 보니 조각당 60ms —
        #   `browser.py`(조각 343개) 하나를 다시 넣는 데 약 41초였고, 바뀐 파일이 16개면 몇 분이다.
        #   `path` 로 한 번에 지우면 같은 파일이 0.2초다(같은 사본, 0.08 + 0.14초). 지워지는 줄은 같다 —
        #   FTS 줄의 `path` 는 아래에서 조각과 같은 값으로 넣는다.
        had_chunks = db.execute("SELECT 1 FROM chunks WHERE path = ? LIMIT 1", (path,)).fetchone()
        if had_chunks:
            for tokenizer in cls.FTS_TOKENIZERS:
                db.execute(f"DELETE FROM chunk_fts_{tokenizer} WHERE path = ?", (cls._safe(path),))
            db.execute("DELETE FROM chunks WHERE path = ?", (path,))
        # ★ 청크 하나당 3 번 부르던 것을 **파일당 3 번**으로 묶는다 (2026-08-28).
        #
        # 프로파일: 콜드 색인 521.8초 중 sqlite execute 386,632 회가 306.4초(59%).
        # 청크가 119,539 개이고 하나마다 chunks 1 + FTS 2 = 3 번을 개별 execute 로
        # 불렀다. `id` 가 INTEGER PRIMARY KEY(rowid 별칭)라 **번호를 미리 떼어 두면**
        # lastrowid 를 기다릴 필요가 없어 executemany 로 한 번에 넣을 수 있다.
        if not chunks:
            return
        next_id = int(
            db.execute("SELECT COALESCE(MAX(id), 0) FROM chunks").fetchone()[0]
        ) + 1
        chunk_rows = []
        fts_rows = []
        for offset, chunk in enumerate(chunks):
            chunk_id = next_id + offset
            chunk_rows.append(
                (
                    chunk_id,
                    cls._safe(path),
                    cls._safe(language),
                    cls._safe(chunk.get("kind")),
                    cls._safe(chunk.get("symbol")),
                    int(chunk.get("start_line") or 1),
                    int(chunk.get("end_line") or 1),
                    cls._safe(chunk.get("signature")),
                    cls._safe(chunk.get("doc")),
                    cls._safe(chunk.get("text")),
                )
            )
            fts_rows.append(
                (
                    cls._safe(cls._fts_body(path, chunk)),
                    cls._safe(path),
                    chunk_id,
                )
            )
        db.executemany(
            """INSERT INTO chunks(id, path, language, kind, symbol, start_line, end_line,
               signature, doc, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            chunk_rows,
        )
        for tokenizer in cls.FTS_TOKENIZERS:
            db.executemany(
                f"INSERT INTO chunk_fts_{tokenizer}(body, path, chunk_id) "
                "VALUES (?, ?, ?)",
                fts_rows,
            )

    @classmethod
    def _fts_terms(cls, terms: list[str], tokenizer: str = "unicode61") -> list[str]:
        """FTS 에 넣을 낱말. 한글은 조사를 떼어 낸 줄기도 같이 넣는다."""
        out: list[str] = []
        minimum = 3 if tokenizer == "trigram" else 2
        for term in terms:
            for candidate in (term, term[:-1] if len(term) > 3 else ""):
                value = candidate.strip()
                if len(value) >= minimum and value not in out:
                    out.append(value)
        return out[:24]

    def search_chunks(
        self, root: Path, query: str, *, limit: int = 40, with_text: int = 0
    ) -> list[dict[str, Any]]:
        """본문 검색. 점수가 낮을수록(bm25) 좋은 것을 뒤집어 돌려준다."""
        # refresh 는 root 를 resolve 해서 DB 이름을 정한다. 여기서 안 맞추면
        # 조용히 **빈 다른 DB** 를 열어 "검색 결과 없음"이 된다.
        root = root.resolve(strict=False)
        base_terms = self._query_terms(query)
        if not base_terms:
            return []
        per_tokenizer: list[list[dict[str, Any]]] = []
        with self._tune(sqlite3.connect(self._database_path(root))) as db:
            self._ensure_chunk_tables(db)
            for tokenizer in self.FTS_TOKENIZERS:
                terms = self._fts_terms(base_terms, tokenizer)
                if not terms:
                    per_tokenizer.append([])
                    continue
                expression = " OR ".join(f'"{term}"' for term in terms)
                try:
                    found = db.execute(
                        f"""SELECT c.path, c.symbol, c.kind, c.start_line, c.end_line,
                                  c.signature, bm25(chunk_fts_{tokenizer}) AS rank
                           FROM chunk_fts_{tokenizer}
                           JOIN chunks c ON c.id = chunk_fts_{tokenizer}.chunk_id
                           WHERE chunk_fts_{tokenizer} MATCH ? ORDER BY rank LIMIT ?""",
                        (expression, int(limit)),
                    ).fetchall()
                except sqlite3.OperationalError:
                    found = []
                per_tokenizer.append(
                    [
                        {
                            "path": path,
                            "symbol": symbol,
                            "kind": kind,
                            "start_line": start,
                            "end_line": end,
                            "signature": signature,
                            "bm25": round(float(rank), 4),
                        }
                        for path, symbol, kind, start, end, signature, rank in found
                    ]
                )
            if with_text:
                wanted = {
                    (str(hit["path"]), int(hit["start_line"]))
                    for hits in per_tokenizer
                    for hit in hits
                }
                excerpts = {
                    (str(row[0]), int(row[1])): str(row[2] or "")[: int(with_text)]
                    for row in db.execute(
                        "SELECT path, start_line, text FROM chunks"
                    )
                    if (str(row[0]), int(row[1])) in wanted
                }
                for hits in per_tokenizer:
                    for hit in hits:
                        hit["excerpt"] = excerpts.get(
                            (str(hit["path"]), int(hit["start_line"])), ""
                        )
        # 두 토크나이저의 순위를 RRF 로 합친다. 하나만 쓰면 문서 티어와 증상
        # 티어 중 한쪽이 반드시 손해를 본다(위 주석의 A/B 참고).
        fused: dict[tuple[str, int], dict[str, Any]] = {}
        for hits in per_tokenizer:
            for position, hit in enumerate(hits, 1):
                key = (str(hit["path"]), int(hit["start_line"]))
                entry = fused.setdefault(key, {**hit, "rrf": 0.0})
                entry["rrf"] = round(float(entry["rrf"]) + 1.0 / (60 + position), 6)
        return sorted(fused.values(), key=lambda row: -float(row["rrf"]))[: int(limit)]


    # ── 의미 검색: 한글 질의 ↔ 영문 코드 ────────────────────────────────
    #
    # 렉시컬은 여기서 천장이다. "잡이 승인 대기로 바뀌는 자리"에 `WAITING_APPROVAL`
    # 이라는 영어가 겹칠 리 없다. 2026-08-27 실측으로 증상 티어가 30~40% 에서
    # 막혔다. bge-m3(다국어)로 재 보니 한글 질의 ↔ 관련 코드 0.608, 무관 코드
    # 0.404 로 실제로 갈린다.
    EMBED_MODEL = setting("JARVIS_CODE_EMBED_MODEL", "bge-m3")
    EMBED_BASE_URL = setting(
        "JARVIS_CODE_EMBED_BASE_URL", "http://127.0.0.1:11435"
    )
    EMBED_BATCH = int(setting("JARVIS_CODE_EMBED_BATCH", "32"))
    EMBED_PER_REFRESH = int(setting("JARVIS_CODE_EMBED_PER_REFRESH", "400"))
    EMBED_TEXT_CHARS = 2_000

    #: 임베딩 서버에 **붙지 못했을 때** 이 시각(monotonic)까지는 다시 두드리지 않는다.
    #
    # ★ 2026-10-04 실측(헤르메스 전수조사의 「첫 걸음까지 17초」를 다시 재다가): 파일 3개짜리 폴더의 색인이 매번 2.3초였고,
    #   그중 2.05초가 `socket.connect` 한 줄이었다. 임베딩 서버(기본 `127.0.0.1:11435` — 둘째 Ollama)가 없으면
    #   윈도우는 연결 거절에 약 2초를 쓴다. 의미 검색은 조용히 빈 결과로 넘어가므로 아무도 몰랐다 — 임베딩 서버가 없는
    #   PC(= 거의 모든 사용자)에서 색인·저장소 지도를 부를 때마다 2초를 버렸다(코드 판 하나에 두 번, 약 4.5초).
    #   한 번 못 붙으면 한동안 건너뛰고, 연결 대기 자체도 짧게 건다. 서버를 나중에 띄우면 그 시간이 지난 뒤 다시 붙는다.
    _embed_down_until: float = 0.0
    EMBED_RETRY_SEC = float(setting("JARVIS_CODE_EMBED_RETRY_SEC", "600"))
    EMBED_CONNECT_SEC = float(setting("JARVIS_CODE_EMBED_CONNECT_SEC", "0.75"))

    @classmethod
    def _embed(cls, texts: list[str]) -> list[list[float]]:
        if not texts or not cls.EMBED_MODEL:
            return []
        if time.monotonic() < cls._embed_down_until:
            raise ConnectionError("embed_server_unreachable — 조금 전에 붙지 못해 이번에는 건너뛴다")
        import httpx

        try:
            response = httpx.post(
                cls.EMBED_BASE_URL.rstrip("/") + "/api/embed",
                json={
                    "model": cls.EMBED_MODEL,
                    "input": texts,
                    "keep_alive": "30m",
                },
                timeout=httpx.Timeout(300.0, connect=cls.EMBED_CONNECT_SEC),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # 서버가 없다. 다음 부름들이 같은 벽을 다시 두드리지 않게 적어 둔다.
            cls._embed_down_until = time.monotonic() + cls.EMBED_RETRY_SEC
            raise
        response.raise_for_status()
        vectors = response.json().get("embeddings") or []
        return [list(map(float, vector)) for vector in vectors]

    @staticmethod
    def _pack(vector: list[float]) -> bytes:
        import numpy as np

        array = np.asarray(vector, dtype="float32")
        norm = float(np.linalg.norm(array))
        if norm:
            array = array / norm
        return array.tobytes()

    @classmethod
    def _ensure_embed_table(cls, db: sqlite3.Connection) -> None:
        db.execute(
            """CREATE TABLE IF NOT EXISTS chunk_vectors (
                chunk_id INTEGER PRIMARY KEY, model TEXT NOT NULL, vector BLOB NOT NULL
            )"""
        )

    def embed_missing(self, root: Path, *, limit: int = 0) -> dict[str, Any]:
        """벡터가 없는 덩어리만 채운다. limit=0 이면 전부."""
        root = root.resolve(strict=False)
        embedded = 0
        failed = ""
        with self._tune(sqlite3.connect(self._database_path(root))) as db:
            self._ensure_chunk_tables(db)
            self._ensure_embed_table(db)
            pending = db.execute(
                """SELECT c.id, c.path, c.symbol, c.signature, c.doc, c.text
                   FROM chunks c LEFT JOIN chunk_vectors v
                     ON v.chunk_id = c.id AND v.model = ?
                   WHERE v.chunk_id IS NULL""",
                (self.EMBED_MODEL,),
            ).fetchall()
            if limit:
                pending = pending[: int(limit)]
            for start in range(0, len(pending), max(1, self.EMBED_BATCH)):
                batch = pending[start : start + max(1, self.EMBED_BATCH)]
                texts = [
                    self._safe(
                        self._fts_body(
                            str(row[1]),
                            {
                                "symbol": row[2],
                                "signature": row[3],
                                "doc": row[4],
                                "text": row[5],
                            },
                        )
                    )[: self.EMBED_TEXT_CHARS]
                    for row in batch
                ]
                try:
                    vectors = self._embed(texts)
                except Exception as exc:
                    failed = f"{type(exc).__name__}: {str(exc)[:160]}"
                    break
                if len(vectors) != len(batch):
                    failed = "embedding_count_mismatch"
                    break
                db.executemany(
                    "INSERT OR REPLACE INTO chunk_vectors(chunk_id, model, vector) "
                    "VALUES (?, ?, ?)",
                    [
                        (int(row[0]), self.EMBED_MODEL, self._pack(vector))
                        for row, vector in zip(batch, vectors)
                    ],
                )
                db.commit()
                embedded += len(batch)
            remaining = int(
                db.execute(
                    """SELECT COUNT(*) FROM chunks c LEFT JOIN chunk_vectors v
                       ON v.chunk_id = c.id AND v.model = ?
                       WHERE v.chunk_id IS NULL""",
                    (self.EMBED_MODEL,),
                ).fetchone()[0]
            )
        return {"embedded": embedded, "remaining": remaining, "error": failed}

    def semantic_search(
        self, root: Path, query: str, *, limit: int = 40
    ) -> list[dict[str, Any]]:
        root = root.resolve(strict=False)
        if not str(query or "").strip():
            return []
        try:
            import numpy as np

            vectors = self._embed([query[:1000]])
        except Exception:
            return []
        if not vectors:
            return []
        needle = np.asarray(vectors[0], dtype="float32")
        norm = float(np.linalg.norm(needle))
        if not norm:
            return []
        needle = needle / norm
        with self._tune(sqlite3.connect(self._database_path(root))) as db:
            self._ensure_embed_table(db)
            try:
                rows = db.execute(
                    """SELECT v.chunk_id, v.vector, c.path, c.symbol, c.kind,
                              c.start_line, c.end_line, c.signature
                       FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id
                       WHERE v.model = ?""",
                    (self.EMBED_MODEL,),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(row[1] for row in rows), dtype="float32")
        matrix = matrix.reshape(len(rows), -1)
        if matrix.shape[1] != needle.shape[0]:
            return []
        scores = matrix @ needle
        order = np.argsort(-scores)[: int(limit)]
        return [
            {
                "path": rows[int(i)][2],
                "symbol": rows[int(i)][3],
                "kind": rows[int(i)][4],
                "start_line": rows[int(i)][5],
                "end_line": rows[int(i)][6],
                "signature": rows[int(i)][7],
                "cosine": round(float(scores[int(i)]), 4),
            }
            for i in order
        ]


    # ── 저장소 스킬 카드 ────────────────────────────────────────────────
    #
    # 앤트로픽 스킬의 첫 층과 같은 생각이다: **이름과 한 줄 설명만 항상 띄워 두고,
    # 본문은 필요할 때 부른다.** 모델에게 필요한 것은 내용이 아니라 "그게 어디
    # 있는지"다.
    #
    # 이걸 안 주면 모델은 눈감고 목록부터 훑는다. 66개 모듈의 한 줄 설명은
    # 1,500 토큰이면 들어가고, **시스템 메시지에 박으면 프리픽스라 캐시가 먹는다**
    # — 즉 두 번째 걸음부터는 공짜다.

    def _reference_graph(
        self, db: sqlite3.Connection
    ) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
        """어느 파일이 어느 파일의 심볼을 부르는가 — 방향 그래프.

        Aider 의 repo map 이 tree-sitter 로 하는 일을 우리 색인으로 한다. 우리는
        이미 파일마다 심볼과 덩어리 원문을 들고 있으므로, 심볼 이름의 주인을
        찾아 두고 각 파일의 식별자에서 역참조하면 같은 그래프가 나온다.
        """
        owners: dict[str, str] = {}
        signatures: dict[str, list[str]] = {}
        rows = db.execute(
            "SELECT path, symbol, signature FROM chunks WHERE symbol != ''"
        ).fetchall()
        for path, symbol, signature in rows:
            name = str(symbol).split(".")[-1]
            # 흔한 짧은 이름은 잡음이다. 주인이 여럿이면 그래프에서 뺀다.
            if len(name) < 4 or name.startswith("_"):
                continue
            if name in owners and owners[name] != path:
                owners[name] = ""
            else:
                owners.setdefault(name, str(path))
            signatures.setdefault(str(path), [])
            if len(signatures[str(path)]) < 6 and signature:
                signatures[str(path)].append(str(signature)[:90])
        owners = {name: path for name, path in owners.items() if path}

        edges: dict[str, dict[str, float]] = {}
        bodies = db.execute("SELECT path, text FROM chunks").fetchall()
        merged: dict[str, list[str]] = {}
        for path, text in bodies:
            merged.setdefault(str(path), []).append(str(text or ""))
        for path, parts in merged.items():
            identifiers = set(_IDENTIFIER_RE.findall(chr(10).join(parts)))
            for name in identifiers & owners.keys():
                target = owners[name]
                if target == path:
                    continue
                edges.setdefault(path, {})
                edges[path][target] = edges[path].get(target, 0.0) + 1.0
        return edges, signatures

    @staticmethod
    def _pagerank(
        edges: dict[str, dict[str, float]],
        personalization: dict[str, float] | None = None,
        *,
        damping: float = 0.85,
        rounds: int = 24,
    ) -> dict[str, float]:
        """거듭제곱법 PageRank. networkx 없이 스무 줄이면 된다."""
        nodes = set(edges) | {dst for row in edges.values() for dst in row}
        if not nodes:
            return {}
        size = len(nodes)
        personal = personalization or {}
        total = sum(personal.values())
        seed = (
            {node: personal.get(node, 0.0) / total for node in nodes}
            if total > 0
            else {node: 1.0 / size for node in nodes}
        )
        score = {node: 1.0 / size for node in nodes}
        for _ in range(rounds):
            nxt = {node: (1.0 - damping) * seed.get(node, 0.0) for node in nodes}
            leaked = 0.0
            for node in nodes:
                out = edges.get(node) or {}
                weight = sum(out.values())
                if not weight:
                    leaked += damping * score[node]
                    continue
                for dst, value in out.items():
                    nxt[dst] += damping * score[node] * value / weight
            if leaked:
                for node in nodes:
                    nxt[node] += leaked * seed.get(node, 1.0 / size)
            score = nxt
        return score

    def repo_card(
        self, root: Path, query: str = "", *, max_chars: int = 3_000
    ) -> str:
        """저장소 지도 — **무엇이 있나**가 아니라 **무엇이 중요한가.**

        ## 왜 PageRank 인가 (2026-08-28)

        첫 판은 모듈 독스트링을 경로순으로 늘어놓았다. 그러면 `scripts/` 가
        알파벳 앞이라 카드를 다 먹고 정작 `src/` 가 잘린다. 중요도순으로 바꿔도
        「무엇이 있나」까지다.

        Aider 가 쓰는 방법이 더 낫다: 심볼 참조로 방향 그래프를 만들고 PageRank
        로 세운다. **20개 함수가 부르는 함수가, 한 번 불리는 private 헬퍼보다
        가치 있는 맥락이다.** 그리고 지금 질의에 나온 심볼 쪽으로 편향시키면
        같은 예산으로 훨씬 정확해진다. Aider 의 기본 예산이 1,000 토큰인 것도
        같은 이유다 — 잘 고르면 작아도 된다.
        """
        root = root.resolve(strict=False)
        try:
            with self._tune(sqlite3.connect(self._database_path(root))) as db:
                self._ensure_chunk_tables(db)
                docs = {
                    str(path): next(
                        (
                            line.strip()
                            for line in str(doc or "").splitlines()
                            if line.strip()
                        ),
                        "",
                    )
                    for path, doc in db.execute(
                        "SELECT path, doc FROM chunks WHERE kind = 'module' AND doc != ''"
                    )
                }
                edges, signatures = self._reference_graph(db)
                try:
                    every_file = [(str(path), int(size or 0)) for path, size in db.execute("SELECT path, size FROM files")]
                except sqlite3.OperationalError:
                    every_file = []
        except sqlite3.OperationalError:
            return ""
        if not edges and not docs:
            return ""

        # 질의 쪽으로 재시작 벡터를 기울인다.
        #
        # ★ 처음엔 질의 낱말을 심볼 이름과 문자열로 대조했다. **한글 질의는 영문
        #   심볼과 한 조각도 안 겹치므로** 편향이 통째로 0 이었다(실측: 질의를
        #   줘도 카드가 한 글자도 안 바뀌었다). 색인에서 이미 겪고 고친 문제다.
        #   그래서 하이브리드 검색(본문 FTS + bge-m3 의미)의 상위 파일을 그대로
        #   재시작 벡터로 쓴다 — 한글↔영문은 그쪽이 이미 넘는다.
        personal: dict[str, float] = {}
        if str(query or "").strip():
            for rank, hit in enumerate(self.search_chunks(root, query, limit=20), 1):
                path = str(hit.get("path") or "")
                if path:
                    personal[path] = personal.get(path, 0.0) + 1.0 / rank
            for rank, hit in enumerate(self.semantic_search(root, query, limit=20), 1):
                path = str(hit.get("path") or "")
                if path:
                    personal[path] = personal.get(path, 0.0) + 1.0 / rank
        score = self._pagerank(edges, personal or None)
        for path in docs:
            score.setdefault(path, 0.0)

        # 재시작 벡터만으로는 편향이 안 산다 — damping 0.85 라 씨앗의 몫이 15%
        # 뿐이고, 중심성 높은 파일이 그대로 위를 차지한다(실측: 질의를 줘도
        # 정답 파일이 3위·32위였다). Aider 가 질의 심볼의 간선에 10배 가중을
        # 주는 것과 같은 뜻으로, 검색 신호를 **점수에 직접** 곱한다.
        boost_scale = 4.0

        def rank(path: str) -> tuple[float, str]:
            weight = score.get(path, 0.0) * (1.0 + boost_scale * personal.get(path, 0.0))
            if "/src/" in path or path.startswith("src/"):
                weight *= 3.0
            elif "/tests/" in path or path.startswith("tests/"):
                weight *= 0.6
            return (-weight, path)

        ordered = sorted(score, key=rank)
        header = "[저장소 지도] 참조가 많은 순. 자세한 것은 열어서 읽어라."
        lines = [header]
        used = len(header)
        listed: set[str] = set()
        for path in ordered:
            summary = docs.get(path) or "; ".join(signatures.get(path, [])[:2])
            if not summary:
                continue
            line = f"  {path} — {summary[:100]}"
            if used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            listed.add(path)
            used += len(line) + 1
        # ★ 작은 폴더는 **파일을 전부** 적고 그렇다고 말한다 (2026-10-07 코딩 사다리).
        #   파일 셋짜리 폴더에서 코드 판은 이 지도를 받고, 곧이어 색인 결과(같은 파일들 + 줄 범위, 약 2,500토큰)를 또 받았다.
        #   폴더 전체가 읽기 한 번의 기본 상한보다 작으면 「어느 줄부터 읽어라」가 줄 것이 없다 — 통째로 읽으면 된다.
        #   그런 폴더는 요약이 없는 파일(README·설정)도 이름으로 적어 **빠진 파일이 없게** 하고 머리말을 바꾼다.
        #   부르는 쪽은 그 머리말을 보고 색인 걸음을 건너뛴다(`agent` 의 `SMALL_FOLDER_CARD_HEAD`).
        if every_file and sum(size for _, size in every_file) <= WHOLE_FOLDER_READ_CHARS:
            rest = sorted(path for path, _ in every_file if path not in listed)
            extra = [f"  {path}" for path in rest]
            if used + sum(len(line) + 1 for line in extra) + (len(SMALL_FOLDER_CARD_HEAD) - len(header)) <= max_chars:
                lines = [SMALL_FOLDER_CARD_HEAD, *lines[1:], *extra]
        return chr(10).join(lines) if len(lines) > 1 else ""

    #: 요청 한 번이 색인 따라잡기에 쓰는 시간. 넘으면 **거기까지 저장하고** 멈춘다 — 다음 요청이 이어서 읽는다.
    #: (같은 16파일을 다시 읽는 데 14.8초였다 — 2026-10-06. 처음 보는 큰 저장소는 여러 번에 나눠 읽힌다.)
    REFRESH_BUDGET_SEC = 45.0

    def refresh(
        self, root: Path, *, scan_limit: int = 50_000,
        on_progress: "Callable[[dict[str, int]], None] | None" = None,
        budget_sec: float | None = None,
    ) -> dict[str, Any]:
        """바뀐 파일만 다시 읽는다. 데워져 있으면 1초 안팎이지만, 오래 안 쓴 저장소는 밀린 파일을 한꺼번에 읽는다.

        ★ 2026-09-28 16:37 코드 모드: 모노레포(파일 4,184개)에서 이 따라잡기가 약 100초 걸렸고, 첫 걸음 전이라 화면엔
        「도구를 고르는 중」만 떠 있었다(사람은 「4분 넘게 멈췄다」고 느꼈다). `on_progress` 로 훑은 수·새로 읽은 수를 1.5초마다 내보낸다.
        """
        # ★ 시간 상한 (2026-10-06 대표 실사용 — 「색인이 너무 느린데 방어하는 로직을 넣어 놓지 않았나」).
        #   09-28 에 넣은 것은 진행 표시뿐이었다. 첫 걸음 전에 동기로 도는 일이라 오래 걸리면 판 전체가 그만큼 서 있는다.
        #   `budget_sec` 를 넘기면 그때까지 읽은 것을 저장하고 멈춘다(`stopped: "time"`). 새로 읽은 파일이 하나도 없으면
        #   멈추지 않는다 — 훑기만 하다 끝나면 다음 요청도 같은 자리에서 멈춘다.
        started = time.monotonic()
        out_of_time = False
        last_report = time.monotonic()
        root = root.resolve(strict=True)
        db_path = self._database_path(root)
        patterns = self._gitignore_patterns(root)
        seen: set[str] = set()
        indexed = 0
        unchanged = 0
        skipped_large = 0
        scanned = 0
        languages: Counter[str] = Counter()
        with self._tune(sqlite3.connect(db_path)) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, language TEXT NOT NULL,
                    symbols_json TEXT NOT NULL, imports_json TEXT NOT NULL
                )"""
            )
            self._ensure_chunk_tables(db)
            existing = {
                row[0]: (int(row[1]), int(row[2]))
                for row in db.execute("SELECT path, mtime_ns, size FROM files")
            }
            # 덩어리 색인은 나중에 생겼다. 이미 있는 색인은 파일이 「변경 없음」
            # 이라 통째로 건너뛰므로 본문이 **영원히 안 들어간다** — 새 기능이
            # 조용히 아무 일도 안 하는 모양이다. 덩어리가 없는 파일은 파일 행을
            # 다시 쓰지 않고 본문만 채운다.
            chunked = {
                row[0] for row in db.execute("SELECT DISTINCT path FROM chunks")
            }
            backfilled = 0
            for current, directories, files in os.walk(root):
                current_path = Path(current)
                directories[:] = [
                    name
                    for name in directories
                    if name not in SKIP_DIRS
                    and not name.startswith(".")
                    and not self._ignored(
                        (current_path / name).relative_to(root).as_posix(), patterns
                    )
                ]
                for name in files:
                    scanned += 1
                    if scanned > scan_limit:
                        break
                    if budget_sec is not None and indexed and time.monotonic() - started >= budget_sec:
                        out_of_time = True
                        break
                    if on_progress is not None and time.monotonic() - last_report >= 1.5:
                        last_report = time.monotonic()
                        try:
                            on_progress({"scanned": scanned, "updated": indexed, "unchanged": unchanged})
                        except Exception:  # noqa: BLE001 — 알림 때문에 색인을 죽이지 않는다
                            pass
                    path = current_path / name
                    relative = path.relative_to(root).as_posix()
                    language = CODE_EXTENSIONS.get(path.suffix.lower())
                    if (
                        language is None
                        or SENSITIVE_NAMES.search(name)
                        or self._ignored(relative, patterns)
                    ):
                        continue
                    stat = path.stat()
                    if stat.st_size > 2 * 1024 * 1024:
                        skipped_large += 1
                        continue
                    seen.add(relative)
                    languages[language] += 1
                    if existing.get(relative) == (stat.st_mtime_ns, stat.st_size):
                        unchanged += 1
                        if relative not in chunked:
                            text = path.read_text(encoding="utf-8", errors="replace")
                            self._replace_chunks(
                                db, relative, language, self._chunks_for(text, language)
                            )
                            backfilled += 1
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                    symbols, imports = (
                        self._python_facts(text)
                        if language == "python"
                        else self._generic_facts(text)
                    )
                    self._replace_chunks(
                        db, relative, language, self._chunks_for(text, language)
                    )
                    db.execute(
                        """INSERT INTO files(path, mtime_ns, size, sha256, language,
                           symbols_json, imports_json) VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(path) DO UPDATE SET mtime_ns=excluded.mtime_ns,
                           size=excluded.size, sha256=excluded.sha256,
                           language=excluded.language, symbols_json=excluded.symbols_json,
                           imports_json=excluded.imports_json""",
                        (
                            relative,
                            stat.st_mtime_ns,
                            stat.st_size,
                            self._sha256(path),
                            language,
                            json.dumps(symbols, ensure_ascii=False),
                            json.dumps(imports, ensure_ascii=False),
                        ),
                    )
                    indexed += 1
                if scanned > scan_limit or out_of_time:
                    break
            # ★ 끝까지 못 훑었으면 「없어진 파일」을 지우지 않는다. 안 지우면, 아직 못 본 파일이 전부 「사라진 것」으로
            #   읽혀 색인에서 빠진다 — 파일 수 상한(`scan_limit`)에 걸린 큰 저장소가 원래 그랬다.
            stopped_early = scanned > scan_limit or out_of_time
            stale = set() if stopped_early else set(existing) - seen
            if stale:
                db.executemany("DELETE FROM files WHERE path = ?", [(path,) for path in stale])
                for path in stale:
                    self._replace_chunks(db, path, "", [])
            db.commit()
            total = int(db.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            chunk_total = int(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        self.last_refresh = {"root": str(root), "stopped": "time" if out_of_time else "scan_limit" if stopped_early else "",
                             "updated_files": indexed, "scanned": scanned,
                             "seconds": round(time.monotonic() - started, 1)}
        return {
            "database": str(db_path),
            "total_files": total,
            "total_chunks": chunk_total,
            "backfilled_chunks": backfilled,
            "updated_files": indexed,
            "unchanged_files": unchanged,
            "removed_files": len(stale),
            "skipped_large": skipped_large,
            "scanned": scanned,
            "truncated": stopped_early,
            "stopped": "time" if out_of_time else "scan_limit" if stopped_early else "",
            "languages": dict(languages.most_common(12)),
        }

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return list(
            dict.fromkeys(
                token.casefold()
                for token in QUERY_TOKEN_RE.findall(query)
                if len(token) >= 2 and token.casefold() not in QUERY_STOP_WORDS
            )
        )[:24]

    @staticmethod
    def _test_key(path: str) -> str:
        stem = Path(path).stem.casefold()
        stem = re.sub(r"^(?:test_|spec_)", "", stem)
        stem = re.sub(r"(?:_test|_spec|\.test|\.spec)$", "", stem)
        return re.sub(r"[^a-z0-9가-힣]", "", stem)

    @classmethod
    def _score(
        cls,
        *,
        path: str,
        language: str,
        symbols: list[dict[str, Any]],
        imports: list[str],
        query: str,
        terms: list[str],
    ) -> tuple[int, list[str]]:
        lowered_path = path.casefold()
        basename = Path(path).name.casefold()
        symbol_names = [str(item.get("name") or "").casefold() for item in symbols]
        lowered_imports = [str(value).casefold() for value in imports]
        haystack = " ".join([lowered_path, language.casefold(), *symbol_names, *lowered_imports])
        score = 0
        reasons: list[str] = []
        full = query.strip().casefold()
        if full and full in haystack:
            score += 24
            reasons.append("exact_query")
        for term in terms:
            if term == basename or term == Path(path).stem.casefold():
                score += 16
                reasons.append(f"filename:{term}")
            elif term in basename:
                score += 12
                reasons.append(f"filename:{term}")
            elif term in lowered_path:
                score += 8
                reasons.append(f"path:{term}")
            if term in symbol_names:
                score += 14
                reasons.append(f"symbol:{term}")
            elif any(term in value for value in symbol_names):
                score += 9
                reasons.append(f"symbol:{term}")
            if any(term in value for value in lowered_imports):
                score += 5
                reasons.append(f"import:{term}")
        if terms and all(term in haystack for term in terms):
            score += 10
            reasons.append("all_terms")
        return score, list(dict.fromkeys(reasons))[:8]

    def query(
        self,
        root: Path,
        query: str = "",
        *,
        max_results: int = 30,
        max_chars: int = 16_000,
    ) -> dict[str, Any]:
        root = root.resolve(strict=True)
        stats = self.refresh(root, budget_sec=self.REFRESH_BUDGET_SEC)
        terms = self._query_terms(query)
        candidates: list[dict[str, Any]] = []
        all_candidates: list[dict[str, Any]] = []
        with self._tune(sqlite3.connect(self._database_path(root))) as db:
            records = db.execute(
                "SELECT path, language, symbols_json, imports_json FROM files ORDER BY path"
            )
            for path, language, symbols_json, imports_json in records:
                symbols = json.loads(symbols_json)
                imports = json.loads(imports_json)
                score, reasons = self._score(
                    path=path,
                    language=language,
                    symbols=symbols,
                    imports=imports,
                    query=query,
                    terms=terms,
                )
                row = {
                        "path": path,
                        "language": language,
                        "symbols": symbols[:20],
                        "imports": imports[:20],
                        "score": score,
                        "why": reasons or ["repo_overview"],
                    }
                all_candidates.append(row)
                if not terms or score > 0:
                    candidates.append(row)
        if terms and not candidates:
            # 한글 요청이 영문 파일명·심볼과 단어 한 조각도 겹치지 않으면
            # 빈 지도를 내던 자리다. 보조 정찰기가 의미로 고를 수 있도록
            # source→test→설정 순의 유한 후보를 준다. 이것도 원문은 아니므로
            # 후속 읽기 규칙은 그대로다.
            def fallback_rank(row: dict[str, Any]) -> tuple[int, str]:
                path = str(row["path"]).casefold()
                if re.search(r"(?:^|/)(?:src|app|lib|packages?)/", path):
                    bucket = 0
                elif re.search(r"(?:^|/)(?:tests?|specs?)/", path):
                    bucket = 1
                elif Path(path).name in {"agents.md", "claude.md", "readme.md", "pyproject.toml"}:
                    bucket = 2
                else:
                    bucket = 3
                return bucket, path

            candidates = []
            for source in sorted(all_candidates, key=fallback_rank)[:80]:
                fallback = dict(source)
                fallback["why"] = ["semantic_fallback"]
                candidates.append(fallback)
        # ── 융합: 이름 순위와 본문 순위를 RRF 로 합친다 ─────────────────
        #
        # 이름만 보던 예전 순위는 한글 증상 질의에서 recall@5 가 0.0% 였다
        # (2026-08-27, 24개 중 19개는 아예 못 찾음). 본문 순위만 쓰면 이번엔
        # 파일명이 정확히 일치하는 쉬운 판을 놓친다. 둘 다 남긴다.
        chunk_hits = self.search_chunks(root, query, limit=120) if terms else []
        # 의미 순위는 낱말이 하나도 안 겹쳐도 걸린다. 렉시컬이 못 넘던 자리다.
        semantic_hits = self.semantic_search(root, query, limit=120) if query.strip() else []
        best_chunk: dict[str, list[dict[str, Any]]] = {}
        content_rank: dict[str, int] = {}
        semantic_rank: dict[str, int] = {}
        for position, hit in enumerate(chunk_hits, 1):
            path = str(hit.get("path") or "")
            content_rank.setdefault(path, position)
            best_chunk.setdefault(path, [])
            if len(best_chunk[path]) < 3:
                best_chunk[path].append(hit)
        for position, hit in enumerate(semantic_hits, 1):
            path = str(hit.get("path") or "")
            semantic_rank.setdefault(path, position)
            best_chunk.setdefault(path, [])
            if len(best_chunk[path]) < 3:
                best_chunk[path].append(hit)

        by_path = {str(row["path"]): row for row in all_candidates}
        for path in list(content_rank) + list(semantic_rank):
            if path not in {str(row["path"]) for row in candidates} and path in by_path:
                extra = dict(by_path[path])
                extra["why"] = ["content_match"]
                candidates.append(extra)

        name_rank = {
            str(row["path"]): position
            for position, row in enumerate(
                sorted(candidates, key=lambda r: (-int(r["score"]), str(r["path"]))), 1
            )
        }
        fusion_k = 60

        def fused(row: dict[str, Any]) -> float:
            path = str(row["path"])
            total = 0.0
            if int(row.get("score") or 0) > 0:
                total += 1.0 / (fusion_k + name_rank.get(path, 10_000))
            if path in content_rank:
                total += 1.0 / (fusion_k + content_rank[path])
            if path in semantic_rank:
                total += 1.0 / (fusion_k + semantic_rank[path])
            return total

        for row in candidates:
            path = str(row["path"])
            row["fusion"] = round(fused(row), 6)
            if path in best_chunk:
                row["chunks"] = [
                    {
                        "symbol": hit.get("symbol"),
                        "kind": hit.get("kind"),
                        "lines": [hit.get("start_line"), hit.get("end_line")],
                        "signature": hit.get("signature"),
                    }
                    for hit in best_chunk[path]
                ]
                label = (
                    "semantic_match"
                    if str(row["path"]) in semantic_rank
                    and str(row["path"]) not in content_rank
                    else "content_match"
                )
                if label not in row.get("why", []):
                    row["why"] = [*row.get("why", []), label][:8]

        candidates.sort(
            key=lambda row: (-float(row.get("fusion") or 0.0), -int(row["score"]), str(row["path"]))
        )
        limit = max(1, min(max_results, 80))
        rows = candidates[:limit]

        # 상위 구현 후보와 이름이 같은 테스트는 질의 단어가 없어도 함께 올린다.
        all_keys = {self._test_key(str(row["path"])) for row in rows}
        selected_paths = {str(row["path"]) for row in rows}
        for candidate in all_candidates:
            path = str(candidate["path"])
            lowered = path.casefold()
            if path in selected_paths or not re.search(r"(?:^|/)(?:tests?|specs?)/|(?:test|spec)", lowered):
                continue
            if self._test_key(path) in all_keys:
                related = dict(candidate)
                related["score"] = max(1, int(related["score"]))
                related["why"] = ["related_test", *related.get("why", [])][:8]
                rows.append(related)
                selected_paths.add(path)
                if len(rows) >= limit:
                    break

        all_paths = [str(row["path"]) for row in all_candidates]
        top_level = Counter(path.split("/", 1)[0] for path in all_paths)
        # ★ 정찰기가 놀 운동장. 예전에는 경로·심볼 이름만 받아서, 사실상
        # 파일명으로 순위를 매기는 LLM 이었다. 실제 코드 조각을 준다.
        evidence = [
            {
                "path": hit.get("path"),
                "symbol": hit.get("symbol"),
                "lines": [hit.get("start_line"), hit.get("end_line")],
                "excerpt": str(hit.get("excerpt") or "")[:2_400],
            }
            for hit in (
                # 정찰기의 창은 65,536 인데 700자씩만 보여 주고 있었다. 대신
                # 읽으라고 하려면 실제로 읽을 만큼은 줘야 한다.
                self.search_chunks(root, query, limit=8, with_text=2_400)
                if terms
                else []
            )
        ]
        repo_map = {
            "top_level": dict(top_level.most_common(20)),
            "query_terms": terms,
            "matches": rows,
            "evidence": evidence,
        }
        budget = max(4_000, min(int(max_chars), 16_000)) + (20_000 if evidence else 0)
        while rows and len(json.dumps(repo_map, ensure_ascii=False)) > budget:
            if len(rows) > 1:
                rows.pop()
            else:
                rows[0]["symbols"] = rows[0].get("symbols", [])[:5]
                rows[0]["imports"] = rows[0].get("imports", [])[:5]
                break
        return {
            "action": "local_index_codebase",
            "root": str(root),
            "query": query,
            "index": stats,
            "repo_map": repo_map,
            "repo_map_chars": len(json.dumps(repo_map, ensure_ascii=False)),
            "instruction": (
                "이 지도는 후보를 좁히는 색인이다. 변경 전에는 관련 파일을 "
                "local_read_text_file로 실제로 읽고, 심볼 이름만으로 구현을 추측하지 마라."
            ),
        }
