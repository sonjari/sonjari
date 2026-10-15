from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal

from .brand import LEGACY_NAMES, NAME_KO


PROJECT_MARKERS = (
    ".git",
    "AGENTS.md",
    "CLAUDE.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".idea",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "backups",
        "build",
        "dist",
        "node_modules",
        "outputs",
        "target",
    }
)

# 대화에서는 한글 이름을 쓰고 폴더는 영문인 이 PC의 실제 관례를 잇는다. 이 표는
# 경로를 허용하는 권한표가 아니다. 이미 허용된 루트 안에서 이름을 맞추는 검색 별칭뿐이다.
TOKEN_ALIASES = {
    # 저장소 폴더는 아직 `alture-jarvis` 다 — 새 이름·옛 이름 어느 쪽으로 불러도 찾는다(brand.py).
    **{name: "jarvis" for name in (NAME_KO, *LEGACY_NAMES) if not name.isascii()},
    "\uc54c\ud29c\uc5b4": "alture",
    "\uc544\uce74\ub370\ubbf8": "academy",
    "\ucf54\ud30c\uc77c\ub7ff": "copilot",
    "\uc785\uc2dc": "admission",
    "\ube0c\ub77c\uc6b0\uc800": "browser",
    "\uc6cc\ucee4": "worker",
}


@dataclass(frozen=True)
class ProjectCandidate:
    path: str
    name: str
    confidence: float
    reasons: tuple[str, ...]
    markers: tuple[str, ...]


@dataclass(frozen=True)
class ProjectDiscoveryResult:
    status: Literal["resolved", "ambiguous", "not_found"]
    workspace: str
    confidence: float
    source: str
    candidates: tuple[ProjectCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "workspace": self.workspace,
            "confidence": self.confidence,
            "source": self.source,
            "candidates": [asdict(candidate) for candidate in self.candidates],
        }


class ProjectDiscovery:
    """허용 루트 안에서 대화에 맞는 코드 프로젝트를 능동적으로 찾는다.

    고득점 후보가 하나일 때만 자동 선택한다. 이름 단서가 없거나 비슷한 후보가 둘이면
    ``ambiguous`` 로 멈춘다. 이것이 폴더 선택 반복은 없애면서 엉뚱한 저장소를 고칠
    가능성을 열지 않는 경계다.
    """

    def __init__(
        self,
        allowed_roots: Iterable[Path],
        state_path: Path,
        *,
        max_depth: int = 4,
        scan_limit: int = 8_000,
        cache_ttl_sec: float = 60.0,
    ) -> None:
        self.allowed_roots = tuple(dict.fromkeys(Path(root).resolve(strict=False) for root in allowed_roots))
        self.state_path = Path(state_path)
        self.max_depth = max(1, int(max_depth))
        self.scan_limit = max(100, int(scan_limit))
        self.cache_ttl_sec = max(0.0, float(cache_ttl_sec))
        self._catalog: tuple[tuple[Path, tuple[str, ...]], ...] = ()
        self._catalog_at = 0.0

    @staticmethod
    def _normalized_tokens(value: str) -> set[str]:
        lowered = value.casefold()
        for korean, english in TOKEN_ALIASES.items():
            if korean in lowered:
                lowered += " " + english
        return {
            token
            for token in re.split(r"[^0-9a-zA-Z가-힣]+", lowered)
            if len(token) >= 2
        }

    def _inside_allowed_root(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=False)
            return any(
                os.path.commonpath([str(resolved).casefold(), str(root).casefold()])
                == str(root).casefold()
                for root in self.allowed_roots
            )
        except (OSError, ValueError):
            return False

    def _load_state(self) -> dict[str, dict[str, object]]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        rows = value.get("sessions") if isinstance(value, dict) else None
        return rows if isinstance(rows, dict) else {}

    def remember(self, session_id: str, workspace: str) -> None:
        session = str(session_id or "").strip()
        path = Path(workspace).resolve(strict=False)
        if not session or not path.is_dir() or not self._inside_allowed_root(path):
            return
        sessions = self._load_state()
        previous = sessions.get(session) if isinstance(sessions.get(session), dict) else {}
        sessions[session] = {
            "path": str(path),
            "last_used": time.time(),
            "uses": int(previous.get("uses") or 0) + 1,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "sessions": sessions}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def _catalog_projects(self) -> tuple[tuple[Path, tuple[str, ...]], ...]:
        now = time.monotonic()
        if self._catalog and now - self._catalog_at <= self.cache_ttl_sec:
            return self._catalog
        found: dict[str, tuple[Path, tuple[str, ...]]] = {}
        scanned = 0
        queue: deque[tuple[Path, int]] = deque(
            (root, 0) for root in self.allowed_roots if root.exists() and root.is_dir()
        )
        while queue and scanned < self.scan_limit:
            folder, depth = queue.popleft()
            scanned += 1
            try:
                names = {entry.name: entry for entry in os.scandir(folder)}
            except OSError:
                continue
            markers = tuple(marker for marker in PROJECT_MARKERS if marker in names)
            if markers:
                resolved = folder.resolve(strict=False)
                found[str(resolved).casefold()] = (resolved, markers)
            if depth >= self.max_depth:
                continue
            for name, entry in names.items():
                if name.startswith(".") or name.casefold() in SKIP_DIRECTORIES:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        queue.append((Path(entry.path), depth + 1))
                except OSError:
                    continue
        self._catalog = tuple(found.values())
        self._catalog_at = now
        return self._catalog

    @staticmethod
    def _path_tokens(path: Path) -> set[str]:
        tokens: set[str] = set()
        for part in path.parts[-4:]:
            tokens.update(
                token
                for token in re.split(r"[^0-9a-zA-Z가-힣]+", part.casefold())
                if len(token) >= 2
            )
        return tokens

    @staticmethod
    def _name_tokens(path: Path) -> set[str]:
        return {
            token
            for token in re.split(r"[^0-9a-zA-Z가-힣]+", path.name.casefold())
            if len(token) >= 2
        }

    def _candidate(
        self,
        path: Path,
        markers: tuple[str, ...],
        query_tokens: set[str],
        recent_path: Path | None,
        query_names_project: bool,
    ) -> ProjectCandidate:
        reasons: list[str] = []
        score = 0.08 if markers else 0.0
        path_tokens = self._path_tokens(path)
        matches = sorted(query_tokens & path_tokens)
        direct_matches = sorted(query_tokens & self._name_tokens(path))
        if direct_matches:
            # 프로젝트명 한 단어(예: "자비스")만 말해도 충분한 단서다. 흔한
            # 이름이 여러 저장소에 겹치면 아래 margin 규칙이 자동 선정을 막는다.
            score += min(0.80, 0.62 + 0.18 * (len(direct_matches) - 1))
            reasons.append("프로젝트 이름 직접 일치: " + ", ".join(direct_matches[:4]))
        elif matches:
            # 부모 저장소 이름을 경로로 물려받은 ui/src-tauri 같은 하위 패키지가
            # 루트와 동점이 되면 "자비스" 한마디가 매번 ambiguous가 된다. 후보에는
            # 남기되 직접 이름 일치보다 낮게 둔다.
            score += min(0.48, 0.32 + 0.08 * (len(matches) - 1))
            reasons.append("상위 경로 이름 일치: " + ", ".join(matches[:4]))
        if recent_path is not None and path == recent_path:
            # 이름 단서가 있으면 최근 폴더가 그것과도 맞아야 한다. 단서가 전혀 없는
            # 후속 질문에서는 같은 대화의 최근 작업공간을 그대로 잇는다.
            score += 0.82 if not query_names_project else 0.26
            reasons.append("이 대화의 최근 작업공간")
        if ".git" in markers:
            score += 0.04
            reasons.append("Git 루트")
        if "AGENTS.md" in markers or "CLAUDE.md" in markers:
            score += 0.04
            reasons.append("에이전트 지침 발견")
        return ProjectCandidate(
            path=str(path),
            name=path.name,
            confidence=round(min(score, 0.99), 3),
            reasons=tuple(reasons or ["프로젝트 표식 발견"]),
            markers=markers,
        )

    def discover(self, query: str, *, session_id: str = "") -> ProjectDiscoveryResult:
        query_tokens = self._normalized_tokens(query)
        sessions = self._load_state()
        recent = sessions.get(session_id) if session_id else None
        recent_path: Path | None = None
        if isinstance(recent, dict) and recent.get("path"):
            candidate = Path(str(recent["path"])).resolve(strict=False)
            if candidate.is_dir() and self._inside_allowed_root(candidate):
                recent_path = candidate

        catalog = self._catalog_projects()
        query_names_project = any(query_tokens & self._path_tokens(path) for path, _ in catalog)
        rows = [
            self._candidate(path, markers, query_tokens, recent_path, query_names_project)
            for path, markers in catalog
        ]
        rows.sort(key=lambda item: (-item.confidence, len(Path(item.path).parts), item.path.casefold()))
        visible = tuple(rows[:5])
        if not visible:
            return ProjectDiscoveryResult("not_found", "", 0.0, "scan", ())
        top = visible[0]
        runner_up = visible[1].confidence if len(visible) > 1 else 0.0
        # 0.70은 이름 두 토큰, 또는 같은 대화의 최근 폴더에 해당한다. 0.12 차이가
        # 안 나면 사람 눈에도 비슷한 후보이므로 자동으로 쓰기 권한을 주지 않는다.
        if top.confidence >= 0.70 and top.confidence - runner_up >= 0.12:
            source = "recent" if "이 대화의 최근 작업공간" in top.reasons else "conversation"
            return ProjectDiscoveryResult("resolved", top.path, top.confidence, source, visible)
        return ProjectDiscoveryResult("ambiguous", "", top.confidence, "scan", visible)
