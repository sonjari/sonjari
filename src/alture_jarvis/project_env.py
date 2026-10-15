"""코드 모드의 **프로젝트 가상환경**과 **선언된 패키지** (2026-09-26).

## 왜

노트북 코드 모드 E2E 뒤에 설치 길을 따라가 보니 두 군데가 비어 있었다.

    1. `python -m pip install …` 이 **온텔릭 자기 파이썬**(`sys.executable`)에 깔렸다.
       포장본에서는 그 자리가 `WindowsApps` 안이라 읽기 전용 → 설치가 늘 실패한다.
       개발 PC 에서는 거꾸로 **온텔릭 venv 를 더럽힌다**.
    2. 명령을 글자 한 줄로 주면(09-20 에 받아 주기로 한 모양) `_install_risk` 가 목록만 봐서
       **승인 판정을 건너뛰었다** — 이름을 댄 새 패키지가 승인 없이 깔릴 수 있었다.

## 규칙

- 설치는 **그 프로젝트의 `.venv`** 에만 한다. 없으면 우리 파이썬으로 만들고
  (`--system-site-packages` — 우리가 싣고 다니는 pytest·ruff·mypy 가 그 안에서도 보이게),
  프로젝트 것이 먼저 잡힌다.
- **프로젝트 파일에 적힌 것**(requirements*.txt · pyproject.toml)은 저장소가 이미 선언한 것의
  재현이라 승인 없이 — 09-01 에 정한 그대로다. **적히지 않은 새 이름**은 승인 카드.
- 받는 곳을 바꾸는 옵션(`--index-url`·`--find-links`…)과 프로젝트 밖에 까는 옵션
  (`--user`·`--target`·`--prefix`…)은 승인으로도 안 연다. 오타 이름 공격(typosquat)과
  시스템 오염이 거기로 들어온다.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator

#: 프로젝트 가상환경으로 보는 폴더 이름. 앞이 우선.
VENV_DIRNAMES = (".venv", "venv")

#: 승인으로도 안 여는 pip 옵션. 받는 곳을 바꾸거나 프로젝트 밖에 깐다.
_PIP_FORBIDDEN = frozenset({
    "--user", "--target", "-t", "--prefix", "--root", "--break-system-packages",
    "--index-url", "-i", "--extra-index-url", "--find-links", "-f", "--trusted-host",
})
#: 값을 하나 받는 pip 옵션 — 그 값은 패키지 이름이 아니다.
_PIP_TAKES_VALUE = frozenset({
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable",
    "--timeout", "--retries", "--python-version", "--platform", "--only-binary", "--no-binary",
    "--progress-bar", "--log", "--cache-dir", "--src", "--upgrade-strategy",
})
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """PEP 503 이름 — `PyYAML`·`pyyaml`·`py_yaml` 을 하나로."""
    return re.sub(r"[-_.]+", "-", name).lower()


def venv_dir(root: Path) -> Path | None:
    for name in VENV_DIRNAMES:
        candidate = root / name
        if venv_python(candidate) is not None:
            return candidate
    return None


def venv_python(venv: Path) -> Path | None:
    for relative in ("Scripts/python.exe", "bin/python"):
        candidate = venv / relative
        if candidate.is_file():
            return candidate
    return None


def venv_has_module(venv: Path, module: str) -> bool:
    """그 가상환경 **자기 칸**에 모듈이 깔려 있나 (시스템 칸은 안 본다)."""
    for site in (venv / "Lib" / "site-packages", *sorted((venv / "lib").glob("python*/site-packages"))):
        if (site / module).is_dir() or (site / f"{module}.py").is_file():
            return True
    return False


def venv_bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if (venv / "Scripts").is_dir() else "bin")


#: 손자리 **자신의** 설정을 나르는 환경변수의 머리. 손자리가 띄우는 사용자 명령에는 넘기지 않는다.
OUR_SETTING_PREFIXES = ("JARVIS_",)


def without_our_settings(environment: dict[str, str]) -> dict[str, str]:
    """손자리 자신의 설정(`JARVIS_*`)을 뺀 환경. 손자리가 띄우는 **사용자의 명령**에 넘길 환경은 이것이다.

    ★ 2026-10-09 새벽 — 우리 숙제를 손자리에게 맡긴 판(585028c5)에서 실제로 일어난 일.
      손자리가 작업 폴더(이 저장소의 사본)에서 `pytest` 를 돌렸다. 운영 프로세스는 시작할 때 자기가 선 자리를
      `JARVIS_RUNTIME_ROOT` 에 적어 두고(`scripts/task_entry.py`), 명령을 띄울 때 환경을 통째로 넘겼다. 사본의 시험이
      만든 런타임이 그 값을 읽어 **돌고 있는 손자리의 DB** 에 붙었고, 거기서 진행 중인 진짜 판을 집어 실패로 찍었다
      (판은 「stopped -> idle is not allowed」로 보였다가 운영 쪽이 끝나며 제자리로 돌아왔다).
      사용자의 프로젝트가 우연히 같은 이름의 값을 읽는 일은 드물지만, **우리 저장소를 손자리로 고치는 사람**(기여자)은
      반드시 이 길을 밟는다. 그리고 제어 토큰 같은 비밀도 같은 머리로 올라와 있다 — 모델이 돌리는 명령에 실어 보낼 이유가 없다.

    물려받아야 하는 값은 없다: 손자리 MCP 서버는 연결 설정에 적힌 값을 따로 받는다(`mcp_connect`).
    """
    return {key: value for key, value in environment.items() if not key.upper().startswith(OUR_SETTING_PREFIXES)}


@contextlib.contextmanager
def scratch_home(environment: dict[str, str]) -> Iterator[dict[str, str]]:
    """명령 하나가 도는 동안만 있는 **새 빈 데이터 자리**를 손자리의 자리 이름으로 넘긴다 — 끝나면 지운다.

    ★ 2026-10-10 — `without_our_settings` 로 우리 설정을 안 넘기게 한 날, 그 방법이 한 번 더 뚫렸다: 설정이 없으니 사본의 코드가
      **기본값**으로 갔고, 그 기본값이 진짜 앱 폴더였다(시험 쪽에서 먼저 걸려 실제 데이터는 안 다쳤다). 「안 넘긴다」는 누가
      진짜 자리를 가리키는 기본값을 넣는 순간 무너진다. 그래서 한 겹을 더 둔다: 사본이 경로를 찾아내더라도 **지워질 곳**에
      떨어지게. 최악이어도 시험 하나가 깨질 뿐 진짜 데이터는 안 다친다. (레딧에서 받은 조언 — 매번 새 빈 폴더 · 끝나면 지우기.)

    손자리 자신의 저장소를 손자리로 고치는 사람에게만 뜻이 있다. 다른 프로젝트는 이 이름을 읽지 않으니 아무 일도 없다.
    만든 자리는 우리가 방금 만든 임시 폴더라 지워도 되는 것뿐이다.
    """
    folder = Path(tempfile.mkdtemp(prefix="sonjari-scratch-"))
    child = dict(environment)
    child["JARVIS_RUNTIME_ROOT"] = str(folder)
    child["JARVIS_BACKUP_DIR"] = str(folder / "backup")
    try:
        yield child
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def with_project_venv_first(environment: dict[str, str], root: Path) -> dict[str, str]:
    """프로젝트 가상환경이 있으면 PATH 맨 앞에 — 셸의 `pip`·`python` 도 그리로 간다."""
    venv = venv_dir(root)
    if venv is None:
        return environment
    rest = environment.get("PATH") or ""
    environment["PATH"] = os.pathsep.join([str(venv_bin_dir(venv)), rest]) if rest else str(venv_bin_dir(venv))
    environment["VIRTUAL_ENV"] = str(venv)
    return environment


def with_project_sources_first(environment: dict[str, str], root: Path) -> dict[str, str]:
    """작업 폴더가 `src/` 배치면 그 `src` 를 `PYTHONPATH` 맨 앞에 — 작업 폴더의 코드가 **우리 환경에 깔린 같은 이름**보다 먼저 불려 오게.

    ★ 2026-10-09 새벽 — 한 줄짜리 숙제를 맡긴 판(hw5 재실행). 손자리는 이 저장소의 **사본**을 고친 뒤 `python _probe.py` 로
      확인했는데, 그 파이썬은 우리 것이고 우리 환경에는 **운영 손자리의 같은 패키지**가 깔려 있다. `pytest` 는 프로젝트
      설정(`pythonpath = ["src"]`)을 따라 사본을 불러오지만 `python 스크립트.py` 는 깔린 쪽을 불러온다 — 고친 것이 안 먹은
      것처럼 보였고, 모델은 「불러와지는 쪽」을 고치려고 **돌고 있는 손자리의 설치 폴더**로 갔다(허용 범위 문이 막았다).
      사용자의 프로젝트가 우리 환경에 깔린 패키지와 이름이 겹칠 때도 같은 일이 난다.

    `src` 안에 파이썬 패키지나 모듈이 실제로 있을 때만 건다. 이미 들어 있으면 두 번 넣지 않는다.
    """
    source = Path(root) / "src"
    try:
        has_code = source.is_dir() and any(
            (child.is_dir() and (child / "__init__.py").is_file()) or (child.is_file() and child.suffix == ".py")
            for child in source.iterdir()
        )
    except OSError:
        has_code = False
    if not has_code:
        return environment
    existing = [part for part in str(environment.get("PYTHONPATH") or "").split(os.pathsep) if part]
    if str(source) not in existing:
        environment["PYTHONPATH"] = os.pathsep.join([str(source), *existing])
    return environment


def create_venv_command(root: Path) -> list[str]:
    """우리 파이썬으로 `.venv` 를 만든다. 우리가 싣고 다니는 도구가 그 안에서도 보이게."""
    return [sys.executable, "-m", "venv", "--system-site-packages", str(root / VENV_DIRNAMES[0])]


def _requirement_names(path: Path, seen: set[Path]) -> set[str]:
    resolved = path.resolve()
    if resolved in seen or not path.is_file():
        return set()
    seen.add(resolved)
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return names
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            names |= _requirement_names(path.parent / line.split(None, 1)[1].strip(), seen)
            continue
        if line.startswith("-"):
            continue
        match = _NAME.match(line)
        if match:
            names.add(normalize(match.group(1)))
    return names


def declared_packages(root: Path) -> set[str]:
    """프로젝트가 **스스로 적어 둔** 의존성 이름들 (정규화됨)."""
    names: set[str] = set()
    seen: set[Path] = set()
    for path in sorted(root.glob("requirements*.txt")):
        names |= _requirement_names(path, seen)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                # 망가진 toml 은 선언이 없는 것으로
            data = {}
        project = data.get("project") or {}
        specs: list[str] = list(project.get("dependencies") or [])
        for group in (project.get("optional-dependencies") or {}).values():
            specs.extend(group or [])
        for group in (data.get("dependency-groups") or {}).values():
            specs.extend(item for item in (group or []) if isinstance(item, str))
        poetry = ((data.get("tool") or {}).get("poetry") or {})
        specs.extend(name for name in (poetry.get("dependencies") or {}) if name.lower() != "python")
        for spec in specs:
            match = _NAME.match(str(spec))
            if match:
                names.add(normalize(match.group(1)))
    return names


def requirement_files(root: Path) -> list[str]:
    return [path.name for path in sorted(root.glob("requirements*.txt"))]


class PipInstall:
    """`pip install` 인자를 읽은 결과."""

    def __init__(self, args: list[str], root: Path) -> None:
        self.forbidden: list[str] = []
        self.requirement_files: list[str] = []
        self.outside_files: list[str] = []
        self.names: list[str] = []
        self.local_self = False
        skip_next_for = ""
        for token in args:
            if skip_next_for:
                if skip_next_for in {"-r", "--requirement", "-c", "--constraint"}:
                    target = (root / token).resolve()
                    inside = _inside(target, root.resolve())
                    (self.requirement_files if inside else self.outside_files).append(token)
                elif skip_next_for in {"-e", "--editable"}:
                    target = (root / token).resolve()
                    if _inside(target, root.resolve()) and not re.match(r"^[a-z+]+://", token):
                        self.local_self = True
                    else:
                        self.names.append(token)
                skip_next_for = ""
                continue
            option = token.split("=", 1)[0]
            if option in _PIP_FORBIDDEN:
                self.forbidden.append(option)
                continue
            if token.startswith("-"):
                if option in _PIP_TAKES_VALUE and "=" not in token:
                    skip_next_for = option
                elif option in {"-r", "--requirement", "-c", "--constraint"}:
                    value = token.split("=", 1)[1]
                    target = (root / value).resolve()
                    (self.requirement_files if _inside(target, root.resolve()) else self.outside_files).append(value)
                continue
            if token in {".", "./"} or (root / token).resolve() == root.resolve():
                self.local_self = True
                continue
            self.names.append(token)

    def undeclared(self, declared: set[str]) -> list[str]:
        """선언 목록에 없는 이름. URL·경로·휠 파일도 여기로 간다(이름으로 확인할 수 없다)."""
        out: list[str] = []
        for token in self.names:
            match = _NAME.match(token)
            plain = match is not None and match.group(0).strip() == re.split(r"[\[<>=!~; @]", token, maxsplit=1)[0]
            if not plain or normalize(match.group(1)) not in declared:     # type: ignore[union-attr]
                out.append(token)
        return out


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path).lower(), str(root).lower()]) == str(root).lower()
    except ValueError:
        return False


_MISSING = re.compile(r"No module named ['\"]?([A-Za-z0-9_.]+)")


def missing_module_hint(output: str, root: Path) -> dict[str, str] | None:
    """`No module named X` 로 실패했으면 **무엇을 깔면 되는지**를 결과에 싣는다 (사고 R — 안내문 대신 결정론).

    모듈 이름과 패키지 이름이 다를 수 있어(`yaml`→`PyYAML`) 선언 목록에서 못 찾으면 이름을 지어내지 않고
    requirements 파일로 보낸다. 지어낸 이름으로 까는 것이 오타 이름 공격이 들어오는 문이다.
    """
    match = _MISSING.search(output or "")
    if not match:
        return None
    module = match.group(1).split(".", 1)[0]
    declared = declared_packages(root)
    files = requirement_files(root)
    if normalize(module) in declared:
        return {
            "missing_module": module,
            "declared": "yes",
            "next": f"프로젝트가 선언한 패키지다 — `python -m pip install {module}` (승인 없이 이 프로젝트 .venv 에)",
        }
    if files:
        return {
            "missing_module": module,
            "declared": "maybe",
            "next": f"`python -m pip install -r {files[0]}` 로 프로젝트가 적어 둔 것을 먼저 깔아라(승인 없이 .venv 에). "
                    "그래도 없으면 패키지 이름을 지어내지 말고 사용자에게 물어라",
        }
    if (root / "pyproject.toml").is_file():
        return {
            "missing_module": module,
            "declared": "maybe",
            "next": "`python -m pip install -e .` 로 이 프로젝트를 설치해라(승인 없이 .venv 에). "
                    "그래도 없으면 패키지 이름을 지어내지 말고 사용자에게 물어라",
        }
    return {
        "missing_module": module,
        "declared": "no",
        "next": "프로젝트가 선언한 의존성 파일이 없다 — 새 패키지 설치는 승인 카드를 거친다. 이름이 확실할 때만 요청해라",
    }
