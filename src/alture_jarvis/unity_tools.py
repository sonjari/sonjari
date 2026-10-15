"""유니티를 **스크립트로** 다룬다 — 게임 팩의 첫 앱 (2026-09-27).

## 왜 화면이 아니라 스크립트인가

웹사이트는 매일 바뀌고 봇 검사가 있다. 유니티는 **공식 명령줄 실행**(배치 모드 `-executeMethod`)이 있다 —
에디터 창 없이 프로젝트를 열고, 우리가 준 C# 에디터 스크립트를 돌리고, 결과를 파일로 남기고 닫는다.
화면을 더듬을 이유가 없고, 결과는 **스크립트가 쓴 파일**로 판정한다(모델의 「됐다」는 증거가 아니다).

실측(2026-09-27, 집 PC): Unity 6000.6.3f1 · FPS Microgame(파일 24,791개)을 배치 모드로 열고 닫는 데 71초,
종료 코드 0, 개인판 라이선스가 배치 모드에서도 잡혔다.

## 레시피 = 고정된 C# + 모델이 채우는 **값(JSON)**

`recipes/unity/<이름>.json` 이 레시피 한 장이고, 같은 이름의 `.cs` 가 실제로 도는 코드다.
모델은 **값만** 넘긴다(`-sonjariArgs` 로 전하는 JSON 파일). 코드에 모델 글을 끼워 넣지 않으니
스크립트 주입 길이 없다. 값은 레시피가 적어 둔 모양(`params`)으로만 받는다.

## 지키는 것

- 프로젝트는 **허락된 자리**(코드 모드에서 고른 작업 폴더·쓰기 허용 폴더)만. 레시피는 실행 동안
  `Assets/Editor/SonjariRecipes/` 에 스크립트를 잠깐 두고 **끝나면 지운다**(.meta 까지). 흔적이 남으면 결과에 적는다.
- 에디터가 그 프로젝트를 열고 있으면 돌리지 않는다(잠금 — 배치 모드가 어차피 못 연다). 사람에게 닫아 달라고 한다.
- 프로젝트의 에디터 버전과 **같은 버전**만 쓴다. 다른 버전으로 열면 프로젝트가 업그레이드된다 — 되돌리기 어려운 변경이다.
- 읽기만 하는 점검 레시피는 L1, 무언가 바꾸는 레시피는 L2(승인 카드).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec
from .unity_editor import EDITOR_TOOL_NAMES, UnityEditorBridge

UNITY_TOOL_NAMES = frozenset({"unity_list_recipes", "unity_project_info", "unity_run_recipe"})
#: 바깥 AI(클로드·코덱스) 전용 문. 온텔릭 자신의 모델에게는 안 보인다 — 작은 모델이 C# 을 처음부터 짜는 것은
#: 「안 되는 걸 억지로」다(전략안 §50). 설계·코딩은 클로드·코덱스가, 실제 프로젝트에서 돌려 보는 것은 온텔릭이.
UNITY_EXTERNAL_TOOLS = frozenset({"unity_try_script"})

_RECIPE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
#: 옛 초안(`Ontelic.Recipes`)도 받는다 — 공용 입출력 파일이 옛 이름 통로를 둔다(이름 2단계 2026-09-29).
_METHOD = re.compile(r"^(?:Sonjari|Ontelic)\.Recipes\.[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")
_VERSION = re.compile(r"m_EditorVersion:\s*(\S+)")
#: 레시피가 잠깐 머무는 자리. 끝나면 통째로 지운다.
_STAGE_DIR = ("Assets", "Editor", "SonjariRecipes")
#: 모든 레시피가 같이 쓰는 입출력 도우미(C#). 레시피 폴더에 한 장만 둔다.
_SHARED_CS = "_SonjariRecipeIO.cs"
_PARAM_TYPES = {"string": str, "integer": int, "boolean": bool}
_RESULT_LIST_MAX = 60


class UnityRecipeError(ValueError):
    pass


def project_version(project: Path) -> str:
    try:
        text = (project / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = _VERSION.search(text)
    return match.group(1) if match else ""


def is_unity_project(path: Path) -> bool:
    return (path / "ProjectSettings" / "ProjectVersion.txt").is_file() and (path / "Assets").is_dir()


def editor_is_open(project: Path) -> bool:
    """에디터가 이 프로젝트를 열고 있나. 잠금 파일이 있고 **다른 프로세스가 쥐고 있으면** 열린 것이다.

    에디터가 죽고 남은 잠금 파일은 아무도 안 쥐고 있어 열린다 — 그건 열린 것으로 치지 않는다(유니티도 새로 열 때 치운다).
    """
    lock = project / "Temp" / "UnityLockfile"
    if not lock.exists():
        return False
    try:
        with open(lock, "r+b"):
            pass
    except PermissionError:
        return True
    except OSError:
        return True
    return False


def _hub_install_roots() -> list[Path]:
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        extra = Path(appdata) / "UnityHub" / "secondaryInstallPath.json"
        try:
            value = json.loads(extra.read_text(encoding="utf-8"))
            if isinstance(value, str) and value.strip():
                roots.append(Path(value.strip()))
        except (OSError, ValueError):
            pass
    return roots


class UnityTools:
    def __init__(self, config: JarvisConfig, local_computer: Any, packs: Any = None) -> None:
        self.config = config
        self.local = local_computer
        # 게임 팩(2026-09-27). 레시피는 팩 폴더에 있고, 팩이 꺼져 있으면 도구 목록에서 빠진다.
        self.packs = packs
        self.recipe_dir = Path(getattr(config, "packs_dir", Path(config.site_recipe_dir).parent / "packs")) / "game" / "recipes" / "unity"
        self.run_root = Path(config.data_dir) / "unity_runs"
        # 같은 판에서 같은 레시피·같은 값·같은 프로젝트로 이미 **검증된 결과**가 있으면 유니티를 또 띄우지 않는다.
        # ★ 2026-09-27 벤치: 35B 가 texture_audit 을 같은 인자로 **10번** 돌렸다(매번 검증된 결과, 한 번에 10초 남짓).
        #   원인이 무엇이든 같은 질문에 같은 답을 10번 받는 것은 낭비다 — 앞 결과를 돌려주며 그걸로 답하라고 말한다.
        self._recent: dict[str, dict[str, Any]] = {}
        # 열린 에디터 다리(2026-09-27 · 2단계). 배치 모드가 못 도는 때(사람이 에디터로 일하는 중)의 길이다.
        self.editor = UnityEditorBridge(config, self)

    # ── 에디터 찾기 ──────────────────────────────────────────────────────────
    def editor_roots(self) -> list[Path]:
        configured = [
            Path(part.strip()) for part in str(getattr(self.config, "unity_editor_roots", "") or "").split(";")
            if part.strip()
        ]
        return [*configured, *_hub_install_roots()]

    def installed_editors(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in self.editor_roots():
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            for child in children:
                exe = child / "Editor" / "Unity.exe"
                if exe.is_file():
                    found.setdefault(child.name, exe)
        return found

    def editor_for(self, version: str) -> Path:
        editors = self.installed_editors()
        if version in editors:
            return editors[version]
        installed = ", ".join(sorted(editors)) or "(설치된 에디터 없음)"
        raise FileNotFoundError(
            f"unity_editor_missing: 이 프로젝트는 {version or '(버전 모름)'} 인데 설치된 에디터는 {installed} 이다. "
            "다른 버전으로 열면 프로젝트가 업그레이드되므로 쓰지 않는다 — 유니티 허브에서 같은 버전을 설치해 달라고 사람에게 말해라."
        )

    # ── 마법사: 유니티가 이 PC 에 어떻게 있나 (Ollama 마법사와 같은 결) ────────────────
    #
    # 사람이 경로를 외우게 하지 않는다. 허브·에디터·라이선스·프로젝트를 **스스로 찾고**, 막힌 첫 칸 하나에 대해
    # 「무엇을 하면 되는지」를 한 줄로 돌려준다. 화면은 계산하지 않는다 — 그 한 줄과 단추 종류를 그대로 그린다.
    _HUB_CANDIDATES = (
        r"C:\Program Files\Unity Hub\Unity Hub.exe",
        r"%LOCALAPPDATA%\Programs\Unity Hub\Unity Hub.exe",
    )
    _LICENSE_CANDIDATES = (
        r"%LOCALAPPDATA%\Unity\licenses\UnityEntitlementLicense.xml",
        r"C:\ProgramData\Unity\Unity_lic.ulf",
    )
    #: 프로젝트를 찾아볼 자리. 드라이브 통째는 안 훑는다 — 흔히 두는 자리와 사람이 고른 자리만.
    _PROJECT_ROOTS = (
        r"%USERPROFILE%\Documents", r"%USERPROFILE%\Desktop", r"%USERPROFILE%\Unity Projects",
        r"%USERPROFILE%\UnityProjects", r"%USERPROFILE%",
    )

    _DRIVE_ROOTS = tuple(f"{letter}:\\UnityProjects" for letter in "CDEFGH")

    def hub_path(self) -> str:
        for raw in self._HUB_CANDIDATES:
            path = Path(os.path.expandvars(raw))
            if path.is_file():
                return str(path)
        return ""

    def license_present(self) -> bool:
        """라이선스 파일이 **있는지만** 본다. 내용은 열지 않는다(계정 정보가 들어 있다)."""
        return any(Path(os.path.expandvars(raw)).is_file() for raw in self._LICENSE_CANDIDATES)

    def _project_state_path(self) -> Path:
        return Path(self.config.data_dir) / "unity_projects.json"

    def remembered_projects(self) -> list[str]:
        try:
            data = json.loads(self._project_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [str(item) for item in data.get("projects") or () if str(item).strip()]

    def remember_project(self, path: Path) -> None:
        known = [item for item in self.remembered_projects() if Path(item).resolve(strict=False) != path]
        target = self._project_state_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"projects": [str(path), *known][:20]}, ensure_ascii=False, indent=1), encoding="utf-8")

    def find_projects(self) -> list[Path]:
        seen: dict[str, Path] = {}

        def consider(path: Path) -> None:
            key = str(path.resolve(strict=False)).lower()
            if key not in seen and is_unity_project(path):
                seen[key] = path.resolve(strict=False)

        for raw in self.remembered_projects():
            consider(Path(raw))
        roots = [Path(os.path.expandvars(raw)) for raw in self._PROJECT_ROOTS]
        # 드라이브마다 흔한 이름 하나(`X:\UnityProjects`)만 본다.
        roots.extend(Path(raw) for raw in self._DRIVE_ROOTS)
        for root in roots:
            try:
                children = [root, *[child for child in root.iterdir() if child.is_dir()]]
            except OSError:
                continue
            for child in children[:400]:
                consider(child)
                if len(seen) >= 30:
                    break
        return list(seen.values())

    def _allowed(self, path: Path) -> bool:
        try:
            self.local.resolve_export_path(str(path))
            return True
        except Exception:  # noqa: BLE001 — 허락 밖이면 False 가 답이다
            return False

    def setup_status(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """마법사가 그리는 전부. 막힌 첫 칸의 `next` 하나가 이 화면의 행동이다."""
        hub = self.hub_path()
        editors = self.installed_editors()
        licensed = self.license_present()
        projects = []
        for path in self.find_projects():
            version = project_version(path)
            projects.append({
                "path": str(path),
                "name": path.name,
                "version": version,
                "editor_installed": version in editors,
                "editor_open": editor_is_open(path),
                "allowed": self._allowed(path),
            })
        ready = [row for row in projects if row["editor_installed"] and row["allowed"] and not row["editor_open"]]
        if not hub and not editors:
            next_step = {"kind": "install_hub", "text": "유니티 허브(유니티를 깔고 여는 프로그램)가 없습니다. 공식 사이트에서 허브를 받아 설치해 주세요."}
        elif not editors:
            next_step = {"kind": "open_hub", "text": "유니티 에디터가 없습니다. 허브의 「설치」에서 「LTS」(오래 고쳐 주는 안정판)가 붙은 버전을 하나 설치해 주세요."}
        elif not licensed:
            next_step = {"kind": "open_hub", "text": "라이선스가 안 보입니다. 허브에 로그인하면 개인용 무료 라이선스를 받을 수 있습니다."}
        elif not projects:
            next_step = {"kind": "pick_project", "text": "프로젝트를 못 찾았습니다. 쓰실 유니티 프로젝트 폴더를 골라 주세요."}
        elif not any(row["allowed"] for row in projects):
            # 찾아 놓은 프로젝트를 또 고르게 하지 않는다 — 단추 한 번으로 그 폴더를 허락한다.
            first = projects[0]
            next_step = {"kind": "allow_project", "path": first["path"],
                         "text": f"{first['name']} 프로젝트를 찾았습니다. 손자리가 이 폴더를 점검하도록 허락해 주세요."}
        elif not ready:
            missing = next((row for row in projects if row["allowed"] and not row["editor_installed"]), None)
            if missing:
                next_step = {"kind": "open_hub", "text": f"{missing['name']} 은 Unity {missing['version']} 프로젝트입니다. 허브에서 그 버전을 설치해 주세요."}
            else:
                # 2단계(2026-09-27): 에디터가 온텔릭과 이어져 있으면 닫을 필요가 없다 — 연 채로 같이 본다.
                live = {os.path.normcase(os.path.normpath(row["project"])) for row in self.editor.live_editors() if row["alive"]}
                linked = next((row for row in projects if row["allowed"] and row["editor_open"]
                               and os.path.normcase(os.path.normpath(row["path"])) in live), None)
                if linked:
                    next_step = {"kind": "ready", "text": (
                        f"준비됐습니다 — {linked['name']} 에디터와 이어져 있어 연 채로 같이 봅니다. 손자리 대화창에 "
                        "「지금 씬 계층 보여줘」처럼 말해 보세요. 아래 점검들은 유니티를 닫으면 돕니다.")}
                else:
                    next_step = {"kind": "close_editor", "text": (
                        "유니티가 이 프로젝트를 열고 있습니다. 둘 중 하나를 하시면 됩니다 — 아래 「에디터 잇기」를 누르면 "
                        "연 채로 같이 보고, 유니티를 닫으면 아래 점검들을 돌릴 수 있습니다.")}
        else:
            next_step = {"kind": "ready", "text": f"준비됐습니다 — 손자리 대화창에 「유니티 {ready[0]['name']} 프로젝트 텍스처 점검해 줘」처럼 말해 보세요."}
        return {
            "action": "unity_setup_status",
            "hub": {"installed": bool(hub), "path": hub},
            "editors": [{"version": version, "path": str(path)} for version, path in sorted(editors.items())],
            "license": licensed,
            "projects": projects,
            "next": next_step,
        }

    def editor_view(self, stage: Any = None) -> dict[str, Any]:
        """설정 화면의 「열린 에디터」 칸 — 기억한 프로젝트마다 이어졌나·에디터가 떠 있나, 우리 방 요약, 무대 상태."""
        live = {os.path.normcase(os.path.normpath(row["project"])): row for row in self.editor.live_editors()}
        projects: list[dict[str, Any]] = []
        for raw in self.remembered_projects():
            path = Path(raw)
            if not is_unity_project(path):
                continue
            row = live.get(os.path.normcase(os.path.normpath(str(path))))
            projects.append({
                "path": str(path), "name": path.name, **self.editor.install_state(path),
                "editor_open": editor_is_open(path), "connected": bool(row and row["alive"]),
                "reloading": bool(row and row["reloading"]),
            })
        return {
            "projects": projects,
            "room": self.editor.room(),
            "stage": stage.status() if stage is not None else {"status": "unavailable"},
            "package_version": self.editor._package_version(),  # noqa: SLF001
        }

    def open_hub(self) -> dict[str, Any]:
        """사람이 누른 단추로만 부른다. 허브가 있으면 켜고, 없으면 공식 다운로드 페이지를 연다."""
        hub = self.hub_path()
        if hub:
            subprocess.Popen([hub], shell=False, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            return {"ok": True, "opened": "hub"}
        import webbrowser

        webbrowser.open("https://unity.com/download")
        return {"ok": True, "opened": "download_page"}

    # ── 프로젝트 자리 ────────────────────────────────────────────────────────
    #: 모델이 프로젝트를 다른 이름으로 보내는 일(첫 벤치: `project_path`). 막지 않고 받는다(사고 R).
    _PROJECT_ALIASES = ("project", "project_path", "projectPath", "project_dir", "path", "root")

    def _project_by_name(self, raw: str) -> Path | None:
        """`raw` 가 경로가 아니라 **이름**이면 아는 프로젝트(기억·찾은 것)에서 같은 이름 하나. 없거나 둘 이상이면 None."""
        text = raw.strip().strip("\"'")
        if not text or any(sep in text for sep in ("\\", "/", ":")) or text.startswith(("%", "~", ".")):
            return None
        matches = [path for path in self.find_projects() if path.name.casefold() == text.casefold()]
        if len(matches) > 1:
            raise ValueError(
                "unity_project_ambiguous: 이름이 같은 프로젝트가 여럿이다 — "
                + ", ".join(str(path) for path in matches[:5]) + " · 사람에게 어느 것인지 물어라."
            )
        return matches[0] if matches else None

    def _project(self, arguments: dict[str, Any], *, write: bool) -> Path:
        raw = next((str(arguments.get(key) or "").strip() for key in self._PROJECT_ALIASES if str(arguments.get(key) or "").strip()), "")
        job_id = str(arguments.get("__job_id") or "")
        workspace = getattr(self.local, "_code_workspaces", {}).get(job_id) if job_id else None
        if not raw and workspace is not None:
            raw = str(workspace)
        if not raw:
            # ★ 프로젝트를 빼고 부르면 **허락된 것이 하나뿐일 때** 그것을 쓴다 (2026-10-01 테스터 시험 2판).
            #   모델이 `unity_project_info` 를 `{}` 로 불러 이 오류를 받고는 사람에게 「프로젝트가 어디 있나요?」를 물었다 —
            #   마법사에서 허락한 프로젝트는 하나였다. 여럿이면 고르지 않고 목록을 준다.
            allowed = [path for path in self.find_projects() if self._allowed(path)]
            if len(allowed) == 1:
                raw = str(allowed[0])
            elif allowed:
                raise ValueError(
                    "unity_project_required: 허락된 프로젝트가 여럿이다 — "
                    + ", ".join(str(path) for path in allowed[:5])
                    + " · 사람이 말한 이름과 맞는 것을 project 에 전체 경로로 줘라. 모르겠으면 사람에게 물어라."
                )
            else:
                raise ValueError(
                    "unity_project_required: 허락된 유니티 프로젝트가 없다 — 사람에게 「설정 › 팩 › 게임 팩」에서 "
                    "프로젝트를 허락해 달라고 말해라."
                )
        # ★ 경로 대신 **이름**이 오면 아는 프로젝트에서 찾는다 (2026-10-01 베타 전 테스터 시험).
        #   「OntelicPlayground 유니티 프로젝트 점검해 줘」에 모델이 `project: "OntelicPlayground"` 를 보냈고, 이 함수가 그걸
        #   앱이 도는 폴더 기준 상대 경로(`…\app\backend\OntelicPlayground`)로 풀어 9걸음·531초를 헛돌았다. 마법사에서 허락한
        #   프로젝트 목록에 같은 이름이 있었다. 이름이 같은 것이 둘 이상이면 **고르지 않는다** — 목록을 주고 묻게 한다.
        named = self._project_by_name(raw)
        if named is not None:
            raw = str(named)
        candidate = Path(os.path.expandvars(raw)).expanduser().resolve(strict=False)
        inside_workspace = workspace is not None and _inside(candidate, Path(workspace).resolve(strict=False))
        if not inside_workspace:
            try:
                candidate = (
                    self.local.resolve_export_path(str(candidate)) if write
                    else self.local.resolve_allowed_path(str(candidate), must_exist=True)
                )
            except (PermissionError, ValueError, FileNotFoundError) as exc:
                # 안내는 **사람이 실제로 누를 자리**로 — 예전 문구(「코드 모드에서 작업 폴더로 골라라」)는 코워크에서
                #   게임 팩으로 허락한 사람에게 틀린 길이었다. 아는 프로젝트를 같이 줘서 모델이 경로를 지어내지 않게 한다.
                allowed = [str(path) for path in self.find_projects() if self._allowed(path)]
                hint = (f" 허락된 프로젝트: {', '.join(allowed[:5])} — 이 중 하나를 project 에 **전체 경로로** 줘라."
                        if allowed else " 허락된 프로젝트가 없다.")
                raise PermissionError(
                    f"unity_project_not_allowed: {candidate} — 사람에게 「설정 › 팩 › 게임 팩」에서 이 프로젝트를 허락해 "
                    f"달라고 말해라(Code 탭이면 그 폴더를 작업 폴더로 골라도 된다).{hint} ({exc})"
                ) from exc
        if not is_unity_project(candidate):
            raise ValueError(f"not_a_unity_project: {candidate} 에 ProjectSettings/ProjectVersion.txt 와 Assets 가 없다.")
        return candidate

    # ── 레시피 ───────────────────────────────────────────────────────────────
    @property
    def user_recipe_dir(self) -> Path:
        """사람이 초안을 확정해 **등록한** 레시피 자리 — 사용자 데이터 폴더라 앱을 새로 깔아도 남는다."""
        return Path(self.config.data_dir) / "packs" / "game" / "recipes" / "unity"

    @property
    def drafts_dir(self) -> Path:
        """클로드·코덱스(또는 온텔릭)가 짠 초안. **여기 있는 것은 레시피가 아니다** — 사람이 등록해야 레시피가 된다."""
        return Path(self.config.data_dir) / "packs" / "game" / "drafts"

    def recipes(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        # 팩에 든 것이 먼저다 — 등록한 레시피가 같은 이름으로 팩 레시피를 덮지 못한다.
        for folder, origin in ((self.recipe_dir, "pack"), (self.user_recipe_dir, "registered")):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                name = str(data.get("name") or "")
                if name in out or not _RECIPE_NAME.fullmatch(name) or name != path.stem:
                    continue
                if not _METHOD.fullmatch(str(data.get("method") or "")):
                    continue
                if not (folder / f"{name}.cs").is_file():
                    continue
                out[name] = {**data, "_dir": str(folder), "_origin": origin}
        return out

    @staticmethod
    def _params(recipe: dict[str, Any], given: Any) -> dict[str, Any]:
        """값을 레시피가 적어 둔 모양으로만 받는다. 모르는 키·틀린 형은 거절한다(조용히 버리지 않는다)."""
        schema = dict(recipe.get("params") or {})
        given = dict(given or {}) if isinstance(given, dict) else {}
        unknown = sorted(set(given) - set(schema))
        if unknown:
            raise UnityRecipeError(f"unknown_params: {unknown} — 이 레시피가 받는 값: {sorted(schema)}")
        out: dict[str, Any] = {}
        for key, spec in schema.items():
            kind = str(spec.get("type") or "string")
            value = given.get(key, spec.get("default"))
            if value is None:
                raise UnityRecipeError(f"param_required: {key}")
            expected = _PARAM_TYPES.get(kind, str)
            if expected is int and isinstance(value, str) and value.strip().lstrip("-").isdigit():
                value = int(value)
            if expected is bool and isinstance(value, str) and value.lower() in {"true", "false"}:
                value = value.lower() == "true"
            if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
                raise UnityRecipeError(f"param_type: {key} 는 {kind} 여야 한다")
            if expected is int:
                low, high = spec.get("min"), spec.get("max")
                if (low is not None and value < low) or (high is not None and value > high):
                    raise UnityRecipeError(f"param_range: {key} 는 {low}~{high}")
            if expected is str:
                value = value.strip().replace("\\", "/")
                if len(value) > 300:
                    raise UnityRecipeError(f"param_too_long: {key}")
                if spec.get("asset_folder"):
                    # 프로젝트 안의 Assets 아래만. 절대 경로·상위 폴더로 나가는 길은 막는다.
                    if not (value == "Assets" or value.startswith("Assets/")) or ".." in value.split("/"):
                        raise UnityRecipeError(f"param_folder: {key} 는 'Assets' 또는 'Assets/...' 여야 한다")
            out[key] = value
        return out

    #: 모델이 레시피·값을 다른 이름으로 보내는 일(2026-09-27 3모델 벤치: 35B·9B 가 `recipe_name`·`recipe_id`·`parameters`).
    #: 막으면 「모르는 레시피」가 세 번 나고 모델은 파일을 뒤지러 간다. 받아 준다(사고 R).
    _RECIPE_ALIASES = ("recipe", "recipe_name", "recipe_id", "name", "recipe_key")
    _PARAM_ALIASES = ("params", "parameters", "args", "arguments", "options")

    @classmethod
    def _normalized(cls, arguments: dict[str, Any]) -> dict[str, Any]:
        out = dict(arguments)
        recipe = next((str(arguments.get(key) or "").strip() for key in cls._RECIPE_ALIASES
                       if str(arguments.get(key) or "").strip()), "")
        out["recipe"] = recipe
        params: Any = None
        for key in cls._PARAM_ALIASES:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip().startswith("{"):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = None
            if isinstance(value, dict) and value:
                params = value
                break
        out["params"] = params
        return out

    def _risk(self, arguments: dict[str, Any]) -> RiskLevel:
        arguments = self._normalized(arguments)
        recipe = self.recipes().get(str(arguments.get("recipe") or ""))
        if recipe is None:
            # ★ 이름이 없거나 모르는 레시피는 **어차피 실행 전에 거절된다**(unknown_recipe). 여기서 L2 로 올리면
            #   실패할 호출이 승인 카드를 띄우고 판을 세운다 — 2026-09-27 벤치에서 두 판이 `{}` 인자로 그렇게 섰다.
            return RiskLevel.L1
        declared = str(recipe.get("risk") or "L2").upper()
        return RiskLevel.L1 if declared in {"L0", "L1"} else RiskLevel.L2

    # ── 도구 본문 ────────────────────────────────────────────────────────────
    def recipe_cards(self) -> list[dict[str, Any]]:
        """설정 화면의 「바로 시킬 수 있는 점검」 — 이름 · 쉬운 한 줄 · 그대로 말하면 되는 문장.

        ★ 2026-10-12 게임 팩을 처음 켠 사람에게 화면이 보여 준 것은 `missing_references · scene_stats …` 같은 파일
          이름 넷이었다. 무엇을 해 주는지도, 뭐라고 말하면 되는지도 없었다. 레시피 파일의 `plain`(사람이 읽는 한 줄)과
          `ask`(예시 문장)를 싣는다. `description` 은 모델이 읽는 글이라 「Missing Script」 같은 말이 그대로 있다 —
          `plain` 이 없을 때만 쓴다. 사람이 등록한 레시피에는 `ask` 가 없을 수 있다(빈 글 — 화면이 문장 칸을 뺀다).
        """
        return [
            {
                "name": name,
                "title": str(data.get("title") or name),
                "description": str(data.get("plain") or data.get("description") or ""),
                "ask": str(data.get("ask") or ""),
                "origin": str(data.get("_origin") or "pack"),
            }
            for name, data in sorted(self.recipes().items())
        ]

    def list_recipes(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        items = [
            {
                "recipe": name,
                "title": str(data.get("title") or ""),
                "description": str(data.get("description") or ""),
                "risk": str(data.get("risk") or "L2"),
                "params": {
                    key: {k: v for k, v in dict(spec).items() if k in {"type", "default", "description", "min", "max"}}
                    for key, spec in dict(data.get("params") or {}).items()
                },
            }
            for name, data in sorted(self.recipes().items())
        ]
        return {
            "action": "unity_list_recipes", "recipes": items, "count": len(items),
            # ★ 맞는 레시피가 없으면 억지로 하지 않는다 — 막히면 넘긴다(전략안 §49·§50).
            "no_fitting_recipe": (
                "맞는 레시피가 없으면 파일을 뒤지거나 스크립트를 짜서 억지로 하지 말고, 사용자에게 이렇게 말해라: "
                "「이 일은 아직 레시피가 없습니다. 클로드 코드나 코덱스에 손자리를 연결해 두셨다면 거기서 "
                "『이 일을 손자리 유니티 레시피로 만들어 줘』라고 하시면, 그쪽이 스크립트를 짜고 제가 이 PC 의 프로젝트에서 "
                "실제로 돌려 확인합니다. 결과가 맞으면 설정 › 팩에서 등록하시면 다음부터는 제가 혼자 합니다.」"
            ),
        }

    def project_info(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """유니티를 안 띄우고 파일만 본다 — 몇 초 안에 끝난다."""
        project = self._project(arguments, write=False)
        version = project_version(project)
        editors = self.installed_editors()
        counts: dict[str, int] = {}
        big: list[tuple[int, str]] = []
        kinds = {
            ".unity": "scenes", ".prefab": "prefabs", ".cs": "scripts", ".mat": "materials",
            ".png": "textures", ".jpg": "textures", ".jpeg": "textures", ".tga": "textures", ".psd": "textures",
            ".exr": "textures", ".tif": "textures", ".tiff": "textures", ".bmp": "textures", ".gif": "textures", ".hdr": "textures", ".psb": "textures", ".fbx": "models", ".obj": "models", ".blend": "models",
            ".anim": "animations", ".controller": "animators", ".wav": "audio", ".mp3": "audio", ".ogg": "audio",
            ".shader": "shaders", ".shadergraph": "shaders", ".asset": "assets",
        }
        scenes: list[str] = []
        for path in (project / "Assets").rglob("*"):
            if not path.is_file() or path.suffix == ".meta":
                continue
            kind = kinds.get(path.suffix.lower(), "other")
            counts[kind] = counts.get(kind, 0) + 1
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            big.append((size, path.relative_to(project).as_posix()))
            if kind == "scenes" and len(scenes) < 40:
                scenes.append(path.relative_to(project).as_posix())
        big.sort(reverse=True)
        packages: list[str] = []
        try:
            manifest = json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))
            packages = sorted(dict(manifest.get("dependencies") or {}))
        except (OSError, ValueError):
            pass
        pipeline = (
            "URP" if "com.unity.render-pipelines.universal" in packages
            else "HDRP" if "com.unity.render-pipelines.high-definition" in packages
            else "Built-in"
        )
        return {
            "action": "unity_project_info",
            "project": str(project),
            "editor_version": version,
            "editor_installed": version in editors,
            "installed_editors": sorted(editors),
            "editor_open": editor_is_open(project),
            "render_pipeline": pipeline,
            "asset_counts": dict(sorted(counts.items())),
            "scenes": scenes,
            "largest_assets": [{"path": p, "mb": round(s / 1_048_576, 2)} for s, p in big[:10]],
            "packages": packages[:80],
            "recipes": sorted(self.recipes()),
            "verified": True,
        }

    def run_recipe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = self._normalized(arguments)
        name = str(arguments.get("recipe") or "").strip()
        recipes = self.recipes()
        if name not in recipes:
            raise UnityRecipeError(f"unknown_recipe: {name!r} — 있는 레시피: {sorted(recipes)}")
        recipe = recipes[name]
        given = arguments.get("params")
        if not isinstance(given, dict) or not given:
            # ★ 첫 벤치: 모델이 값을 `params` 안이 아니라 **겉에** 흩어 보냈다(folder·max_size·limit).
            #   레시피가 받는 이름만 주워 담는다 — 모르는 키는 여전히 안 받는다(겉의 다른 인자와 섞이지 않게).
            schema = set(dict(recipe.get("params") or {}))
            given = {key: value for key, value in arguments.items() if key in schema}
        params = self._params(recipe, given)
        project = self._project(arguments, write=True)
        cache_key = json.dumps(
            [str(arguments.get("__job_id") or ""), name, params, str(project).lower()], sort_keys=True, ensure_ascii=False
        )
        previous = self._recent.get(cache_key) if arguments.get("__job_id") else None
        if previous is not None:
            return {
                **previous,
                "reused_previous_run": True,
                "instruction": (
                    "★ [도구가 보낸 안내] 이 판에서 같은 레시피를 같은 값으로 이미 돌려 **검증된 결과**가 있다(위 result). "
                    "유니티를 다시 띄우지 않았다. 이 결과로 바로 답해라 — 다시 돌려도 같은 답이 나온다."
                ),
            }
        outcome = self._execute(
            name=name, method=str(recipe["method"]), source=Path(recipe["_dir"]) / f"{name}.cs",
            project=project, params=params, timeout_sec=arguments.get("timeout_sec"), action="unity_run_recipe",
        )
        if outcome["verified"] and arguments.get("__job_id"):
            if len(self._recent) > 64:
                self._recent.clear()
            self._recent[cache_key] = outcome
        return outcome

    def _execute(
        self, *, name: str, method: str, source: Path, project: Path, params: dict[str, Any],
        timeout_sec: Any, action: str,
    ) -> dict[str, Any]:
        """레시피든 초안이든 **같은 길**로 돌린다 — 잠깐 두고, 배치 모드로 돌리고, 결과 파일로 판정하고, 흔적을 지운다."""
        if editor_is_open(project):
            connected = any(
                row["alive"] and os.path.normcase(os.path.normpath(row["project"])) == os.path.normcase(os.path.normpath(str(project)))
                for row in self.editor.live_editors()
            )
            raise RuntimeError(
                "unity_editor_open: 유니티 에디터가 이 프로젝트를 열고 있다. 배치 모드는 같은 프로젝트를 못 연다. "
                + ("에디터가 손자리와 이어져 있으니 unity_editor_status·unity_editor_look 으로 **열린 에디터 안을** 읽어라 "
                   "(바꾸는 일은 unity_editor_change — 승인). 레시피가 꼭 필요하면 사람에게 에디터를 닫아 달라고 해라."
                   if connected else
                   "사람에게 에디터를 닫아 달라고 말해라(저장 안 한 변경이 있을 수 있으니 대신 닫지 않는다). "
                   "설정 › 팩 › 게임 팩에서 「에디터 잇기」를 해 두면 다음부터는 닫지 않고 에디터 안에서 읽을 수 있다.")
            )
        editor = self.editor_for(project_version(project))

        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = self.run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        args_file, out_file, log_file = run_dir / "args.json", run_dir / "result.json", run_dir / "unity.log"
        args_file.write_text(json.dumps(params, ensure_ascii=False), encoding="utf-8")

        stage = project.joinpath(*_STAGE_DIR)
        # 우리가 **새로 만드는** 폴더만 적어 둔다 — 끝나면 그것만(비어 있을 때) .meta 까지 지운다.
        # ★ 첫 실행에서 `Assets/Editor` 가 원래 없던 프로젝트에 빈 폴더와 Editor.meta 가 남았다(2026-09-27 실측).
        created = [
            project.joinpath(*_STAGE_DIR[:depth])
            for depth in range(2, len(_STAGE_DIR) + 1)
            if not project.joinpath(*_STAGE_DIR[:depth]).exists()
        ]
        stage.mkdir(parents=True, exist_ok=True)
        staged = [stage / _SHARED_CS, stage / f"{name}.cs"]
        shutil.copyfile(self.recipe_dir / _SHARED_CS, staged[0])
        shutil.copyfile(source, staged[1])
        timeout = max(60, min(int(timeout_sec or getattr(self.config, "unity_run_timeout_sec", 900)), 3600))
        command = [
            str(editor), "-batchmode", "-quit", "-nographics",
            "-projectPath", str(project),
            "-executeMethod", method,
            "-logFile", str(log_file),
            "-sonjariArgs", str(args_file),
            "-sonjariOut", str(out_file),
        ]
        started = time.monotonic()
        timed_out = False
        try:
            done = subprocess.run(
                command, capture_output=True, timeout=timeout, shell=False, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            exit_code = int(done.returncode)
        except subprocess.TimeoutExpired:
            exit_code, timed_out = 124, True
        finally:
            leftover = self._unstage(staged, created)
        elapsed = round(time.monotonic() - started, 1)

        log_text = ""
        try:
            log_text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        compile_errors = [line.strip()[:300] for line in log_text.splitlines() if "error CS" in line][:10]
        result: dict[str, Any] = {}
        try:
            result = json.loads(out_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
        verified = exit_code == 0 and not timed_out and bool(result) and result.get("ok") is True
        failure = ""
        if not verified:
            failure = (
                "timeout" if timed_out
                else "compile_error" if compile_errors
                else "no_result_file" if not result
                else str(result.get("error") or "recipe_reported_failure")
            )
        return {
            "action": action,
            "recipe": name,
            "project": str(project),
            "params": params,
            "exit_code": exit_code,
            "elapsed_sec": elapsed,
            "verified": verified,
            **({"failure": failure} if failure else {}),
            **({"compile_errors": compile_errors} if compile_errors else {}),
            "result": _trim(result),
            "log_file": str(log_file),
            "result_file": str(out_file),
            "left_in_project": leftover,
            # 원장이 「무엇을 읽었나」의 지문으로 쓴다(evidence._HASH_KEYS).
            **({"content_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()}
               if result else {}),
        }

    # ── 클로드·코덱스와 같이 쓰기: 초안 → 실제 프로젝트에서 돌려 보기 → 사람이 레시피로 등록 ─────────────
    #
    # 레시피가 없는 새 일을 온텔릭 혼자 억지로 하지 않는다. 설계·코딩은 클로드·코덱스가 하고(MCP 로 이 문을 부른다),
    # 온텔릭은 그 C# 을 **사용자 PC 의 실제 프로젝트에서** 돌려 컴파일 오류와 결과를 그대로 돌려준다(에셋은 밖에 안 나간다).
    # 사람이 결과를 보고 등록하면, 다음부터는 온텔릭 혼자(작은 모델로도) 같은 일을 공짜로 한다.
    #
    # 초안 코드는 실행 전에 훑는다. 읽기만 하는 코드는 바로 돌리고, 바꾸는·내보내는 코드가 보이면 승인 카드(L2).
    # 훑기는 실수를 거르는 장치다 — 코드 작성자는 사용자가 붙인 AI 라 공격자를 가정하지는 않지만, 리플렉션·
    # 네이티브 호출처럼 훑기를 비껴가는 길은 그 자체를 「승인이 필요한 것」으로 센다.
    _DRAFT_RISKS: tuple[tuple[str, str], ...] = (
        (r"\bFile\.(?:Write|Delete|Move|Copy|Append|Replace|Create|Open(?:Write)?)\w*", "파일 쓰기·지우기"),
        (r"\b(?:StreamWriter|FileStream|BinaryWriter)\b", "파일 쓰기"),
        (r"\bDirectory\.(?:Delete|Move|Create)\w*", "폴더 바꾸기"),
        (r"\bFileUtil\.", "파일 바꾸기"),
        (r"\bAssetDatabase\.(?:DeleteAsset|DeleteAssets|MoveAsset|MoveAssetToTrash|RenameAsset|CreateAsset|CopyAsset|"
         r"SaveAssets|SaveAssetIfDirty|ImportAsset|CreateFolder|ForceReserializeAssets|StartAssetEditing)", "에셋 바꾸기·저장"),
        (r"\.SaveAndReimport\s*\(", "가져오기 설정 저장"),
        (r"\bEditorSceneManager\.(?:SaveScene|SaveScenes|SaveOpenScenes|MarkSceneDirty|MarkAllScenesDirty)", "씬 저장"),
        (r"\bPrefabUtility\.(?:SaveAsPrefabAsset\w*|SavePrefabAsset|ApplyPrefabInstance|ApplyObjectOverride|UnpackPrefabInstance)", "프리팹 저장"),
        (r"\bEditorUtility\.SetDirty\b|\bUndo\.", "변경 기록"),
        (r"\bSystem\.Diagnostics\.Process\b|\bProcess\.Start\b", "외부 프로그램 실행"),
        (r"\b(?:HttpClient|WebClient|UnityWebRequest|WebRequest|TcpClient|UdpClient|Socket)\b", "인터넷·네트워크"),
        (r"\bSystem\.Reflection\b|\bAssembly\.Load\w*|\bActivator\.|\bDllImport\b|\bunsafe\b|\bMarshal\.", "숨은 실행(리플렉션·네이티브)"),
        (r"\b(?:PlayerPrefs|EditorPrefs)\.(?:Set|Delete)\w*", "설정 바꾸기"),
        (r"\bBuildPipeline\.", "빌드"),
        (r"\bEditorApplication\.(?:Exit|ExecuteMenuItem)\b", "에디터 명령 실행"),
    )
    _DRAFT_CLASS = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")

    @classmethod
    def screen_draft(cls, code: str) -> list[dict[str, Any]]:
        """바꾸거나 내보내는 코드가 있는 줄을 찾는다. 비었으면 읽기만 하는 초안이다."""
        findings: list[dict[str, Any]] = []
        for number, line in enumerate(code.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            for pattern, label in cls._DRAFT_RISKS:
                if re.search(pattern, line):
                    findings.append({"line": number, "what": label, "code": stripped[:160]})
                    break
        return findings

    def _draft_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        return RiskLevel.L2 if self.screen_draft(str(arguments.get("csharp") or "")) else RiskLevel.L1

    def try_script(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """클로드·코덱스가 짠 C# 초안을 **실제 프로젝트에서** 한 번 돌려 보고, 초안으로 남긴다(레시피는 아니다)."""
        name = str(arguments.get("name") or "").strip()
        if not _RECIPE_NAME.fullmatch(name):
            raise UnityRecipeError("draft_name: name 은 영어 소문자·숫자·밑줄 2~49자(예: find_large_meshes)")
        if name in self.recipes():
            raise UnityRecipeError(f"draft_name_taken: {name} 는 이미 레시피다 — 다른 이름을 쓰거나 unity_run_recipe 로 돌려라")
        code = str(arguments.get("csharp") or "")
        if not code.strip() or len(code) > 60_000:
            raise UnityRecipeError("draft_code: csharp 에 C# 전체를 넣어라(6만 자 이하)")
        namespace = next((ns for ns in ("Sonjari.Recipes", "Ontelic.Recipes") if f"namespace {ns}" in code), "")
        if not namespace or not re.search(r"public\s+static\s+void\s+Run\s*\(\s*\)", code):
            raise UnityRecipeError(
                "draft_shape: `namespace Sonjari.Recipes` 안의 public static class 에 `public static void Run()` 을 두고, "
                "값은 RecipeIO.ReadArgs<T>() 로 받고 결과는 RecipeIO.Write(dict) 로 남겨라(ok=true 필수). "
                "unity_list_recipes 의 기존 레시피가 본보기다."
            )
        classes = self._DRAFT_CLASS.findall(code)
        method = f"{namespace}.{classes[0]}.Run" if classes else ""
        if not _METHOD.fullmatch(method):
            raise UnityRecipeError("draft_shape: 클래스 이름을 찾지 못했다")
        schema = arguments.get("params_schema") if isinstance(arguments.get("params_schema"), dict) else {}
        draft = {
            "name": name,
            "title": str(arguments.get("title") or name)[:80],
            "description": str(arguments.get("description") or "")[:600],
            "method": method,
            "params": schema,
        }
        params = self._params(draft, arguments.get("params") if isinstance(arguments.get("params"), dict) else {})
        project = self._project(arguments, write=True)
        findings = self.screen_draft(code)
        folder = self.drafts_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.cs").write_text(code, encoding="utf-8")
        draft_record = {
            **draft,
            "risk": "L2" if findings else "L1",
            "findings": findings,
            "author": str(arguments.get("author") or "바깥 AI")[:40],
            "updated_at": time.time(),
        }
        (folder / f"{name}.json").write_text(json.dumps(draft_record, ensure_ascii=False, indent=1), encoding="utf-8")
        outcome = self._execute(
            name=name, method=method, source=folder / f"{name}.cs", project=project, params=params,
            timeout_sec=arguments.get("timeout_sec"), action="unity_try_script",
        )
        (folder / "last_run.json").write_text(json.dumps({
            "verified": outcome["verified"], "failure": outcome.get("failure", ""), "at": time.time(),
            "project": str(project), "compile_errors": outcome.get("compile_errors", []),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        outcome["draft"] = name
        outcome["changes_things"] = bool(findings)
        outcome["findings"] = findings
        outcome["next"] = (
            "결과가 맞으면 사용자에게 「손자리 설정 › 팩 › 게임 팩에서 이 초안을 레시피로 등록해 달라」고 말하세요. "
            "등록은 사람만 할 수 있고, 등록하면 다음부터 손자리가 혼자 unity_run_recipe 로 돌립니다."
            if outcome["verified"] else
            "compile_errors·failure 를 보고 csharp 를 고쳐 같은 name 으로 다시 부르세요(초안을 덮어씁니다)."
        )
        return outcome

    def drafts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.drafts_dir.is_dir():
            return rows
        for folder in sorted(p for p in self.drafts_dir.iterdir() if p.is_dir()):
            try:
                record = json.loads((folder / f"{folder.name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            try:
                last = json.loads((folder / "last_run.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                last = {}
            rows.append({
                "name": folder.name, "title": record.get("title", folder.name), "description": record.get("description", ""),
                "risk": record.get("risk", "L2"), "findings": record.get("findings", []), "author": record.get("author", ""),
                "verified": bool(last.get("verified")), "failure": last.get("failure", ""), "ran_at": last.get("at"),
            })
        return rows

    def promote_draft(self, name: str) -> dict[str, Any]:
        """**사람만** 부른다(설정 화면). 마지막 실행이 검증된 초안만 레시피가 된다."""
        folder = self.drafts_dir / name
        record_path, code_path = folder / f"{name}.json", folder / f"{name}.cs"
        if not _RECIPE_NAME.fullmatch(name) or not record_path.is_file() or not code_path.is_file():
            raise UnityRecipeError(f"unknown_draft: {name}")
        try:
            last = json.loads((folder / "last_run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = {}
        if not last.get("verified"):
            raise UnityRecipeError("draft_not_verified: 마지막 실행이 성공한 초안만 등록할 수 있습니다 — 먼저 제대로 돌려 보세요.")
        if name in self.recipes():
            raise UnityRecipeError(f"draft_name_taken: {name}")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        # 등록할 때 코드를 **다시** 훑는다 — 초안 파일이 그 사이 바뀌었을 수 있다.
        findings = self.screen_draft(code_path.read_text(encoding="utf-8"))
        recipe = {
            "name": name, "title": record.get("title", name), "description": record.get("description", ""),
            "method": record["method"], "risk": "L2" if findings else "L1", "params": record.get("params", {}),
            "_why": f"{record.get('author', '바깥 AI')}가 짠 초안을 사람이 확인해 등록({time.strftime('%Y-%m-%d')}).",
        }
        self.user_recipe_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code_path, self.user_recipe_dir / f"{name}.cs")
        (self.user_recipe_dir / f"{name}.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        return {"ok": True, "recipe": name, "risk": recipe["risk"]}

    def discard_draft(self, name: str) -> dict[str, Any]:
        folder = self.drafts_dir / name
        if not _RECIPE_NAME.fullmatch(name) or not folder.is_dir():
            raise UnityRecipeError(f"unknown_draft: {name}")
        shutil.rmtree(folder, ignore_errors=True)
        return {"ok": True, "discarded": name}

    @staticmethod
    def _unstage(staged: list[Path], created: list[Path]) -> list[str]:
        """잠깐 둔 스크립트를 .meta 까지 지우고, **우리가 만든 폴더**를 안쪽부터 비어 있을 때만 지운다.
        원래 있던 폴더나 사람이 그 사이 넣은 파일은 건드리지 않는다. 못 지운 것은 **숨기지 않고** 돌려준다."""
        left: list[str] = []
        for path in staged:
            for target in (path, path.with_name(path.name + ".meta")):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    left.append(str(target))
        for folder in sorted(created, key=lambda item: len(item.parts), reverse=True):
            try:
                if folder.exists() and not any(folder.iterdir()):
                    folder.rmdir()
                if not folder.exists():
                    folder.with_name(folder.name + ".meta").unlink(missing_ok=True)
                else:
                    left.append(str(folder))
            except OSError:
                left.append(str(folder))
        return left

    # ── 등록 ─────────────────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        listing = ", ".join(sorted(self.recipes())) or "(레시피 없음)"
        return [
            {"type": "function", "function": {
                "name": "unity_project_info",
                "description": (
                    "유니티 프로젝트를 **에디터를 띄우지 않고** 훑는다: 에디터 버전·설치 여부·에디터가 열려 있는지·"
                    "씬/프리팹/텍스처 개수·렌더 파이프라인·큰 에셋·패키지. 유니티 일을 시작할 때 먼저 부른다."
                ),
                "parameters": {"type": "object", "properties": {
                    "project": {"type": "string", "description": "유니티 프로젝트 폴더(ProjectSettings 가 있는 곳). 코드 모드면 비워도 된다."},
                }, "required": []},
            }},
            {"type": "function", "function": {
                "name": "unity_list_recipes",
                "description": "유니티 레시피(검증된 점검·작업 절차) 목록과 각 레시피가 받는 값을 본다.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "unity_try_script",
                "description": (
                    "(클로드·코덱스용) 레시피가 없는 새 유니티 일을 위해 **당신이 짠 C# 에디터 스크립트**를 사용자 PC 의 실제 "
                    "프로젝트에서 배치 모드로 한 번 돌려 컴파일 오류·결과를 받는다. 에셋은 밖으로 나가지 않는다. 모양: "
                    "`namespace Sonjari.Recipes` 의 public static class 에 `public static void Run()`, 값은 "
                    "`RecipeIO.ReadArgs<T>()`, 결과는 `RecipeIO.Write(new Dictionary<string, object>{{\"ok\", true}, ...})`. "
                    "읽기만 하는 코드는 바로 돌고, 파일·에셋·씬을 바꾸거나 인터넷·외부 프로그램을 쓰는 코드는 손자리 창의 "
                    "승인이 필요하다. 성공한 초안은 사람이 손자리 화면에서 레시피로 등록한다 — 그 뒤로는 손자리 혼자 돌린다."
                ),
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string", "description": "영어 소문자·숫자·밑줄(예: find_large_meshes). 같은 이름이면 초안을 덮어쓴다"},
                    "title": {"type": "string", "description": "사람이 볼 한국어 제목"},
                    "description": {"type": "string", "description": "무엇을 찾고/하는지 한두 문장"},
                    "csharp": {"type": "string", "description": "C# 전체 소스"},
                    "params_schema": {"type": "object", "description": "받는 값의 모양 {이름: {type: string|integer|boolean, default, min, max, asset_folder}}"},
                    "params": {"type": "object"},
                    "project": {"type": "string", "description": "유니티 프로젝트 폴더(허락된 곳)"},
                }, "required": ["name", "csharp", "project"]},
            }},
            {"type": "function", "function": {
                "name": "unity_run_recipe",
                "description": (
                    "유니티 레시피를 배치 모드로 실행하고 결과(JSON)를 받는다. 스크립트를 새로 짜지 말고 이것부터 써라. "
                    f"값은 params 로만 준다. 사용 가능: {listing}. 에디터가 그 프로젝트를 열고 있으면 못 돈다."
                ),
                "parameters": {"type": "object", "properties": {
                    "recipe": {"type": "string"},
                    "project": {"type": "string", "description": "코드 모드면 비워도 된다."},
                    "params": {"type": "object"},
                    "timeout_sec": {"type": "integer"},
                }, "required": ["recipe"]},
            }},
            *self.editor.ollama_tools,
        ]

    @property
    def names(self) -> set[str]:
        return set(UNITY_TOOL_NAMES) | set(EDITOR_TOOL_NAMES)

    def enabled(self) -> bool:
        """게임 팩이 켜져 있나. 팩 장부가 없으면(시험·옛 부르는 쪽) 켜진 것으로 본다."""
        return self.packs is None or self.packs.is_enabled("game")

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        """에이전트 카탈로그가 보는 목록 — 팩이 꺼져 있으면 비어 있다(게임을 안 하는 사람의 도구 목록에 안 낀다).
        바깥 AI 전용 문(초안 돌려 보기)은 온텔릭 자신의 모델에게 주지 않는다."""
        if not self.enabled():
            return []
        return [tool for tool in self.ollama_tools if tool["function"]["name"] not in UNITY_EXTERNAL_TOOLS]

    def _guard(self, handler: Any) -> Any:
        def run(arguments: dict[str, Any]) -> dict[str, Any]:
            if not self.enabled():
                raise PermissionError("pack_disabled: 게임 팩이 꺼져 있다 — 설정 › 팩에서 켜야 유니티를 다룰 수 있다고 사람에게 말해라.")
            return handler(arguments)
        return run

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "unity_project_info": (self.project_info, RiskLevel.L0, None),
            "unity_list_recipes": (self.list_recipes, RiskLevel.L0, None),
            "unity_run_recipe": (self.run_recipe, RiskLevel.L1, self._risk),
            # 바꾸는 코드가 보이면 L2(온텔릭 창 승인) — `_draft_risk` 가 코드를 훑는다.
            "unity_try_script": (self.try_script, RiskLevel.L1, self._draft_risk),
        }
        self.editor.register(gateway, guard=self._guard)
        for tool in self.ollama_tools:
            spec = tool["function"]
            if spec["name"] in EDITOR_TOOL_NAMES:
                continue
            handler, risk, dynamic = handlers[spec["name"]]
            gateway.register(ToolSpec(
                name=spec["name"],
                description=str(spec["description"]),
                parameters=dict(spec["parameters"]),
                risk_level=risk,
                dynamic_risk=dynamic,
                handler=self._guard(handler),
                enabled=bool(getattr(self.config, "local_computer_enabled", True)),
                # ★ 코드 모드 작업 폴더를 찾으려면 잡 번호가 필요하다. 이게 없어서 첫 벤치 판이
                #   「project 를 줘라」로 두 번 헛걸었다(2026-09-27) — 게이트웨이는 표시한 도구에만 넘긴다.
                needs_job_context=True,
            ))


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path).lower(), str(root).lower()]) == str(root).lower()
    except ValueError:
        return False


def _trim(value: Any, depth: int = 0) -> Any:
    """결과가 크면 목록을 자른다 — **잘랐다고 적는다**(조용히 사라지면 「없던 것」과 구별이 안 된다)."""
    if isinstance(value, dict):
        return {key: _trim(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > _RESULT_LIST_MAX:
            return [*(_trim(item, depth + 1) for item in value[:_RESULT_LIST_MAX]),
                    {"_truncated": len(value) - _RESULT_LIST_MAX}]
        return [_trim(item, depth + 1) for item in value]
    return value
