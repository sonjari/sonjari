"""첫 실행 3단계 — 클로드·코덱스·커서에 자비스를 **한 번에** 잇는다 (전략안 §43 P5 · §44).

## 공개 제품 기준 (2026-09-14 사용자: 전 세계 사용자가 쓴다고 가정하라)

- **이 PC 에 맞춘 것은 전부 버그다.** 설치 경로·파이썬·포트·데이터 폴더를 **지금 도는 자비스
  자신**에게서 가져온다. 예전 스크립트(`setup_mcp.py`·`apply_mcp_config.py`)는
  특정 설치 경로와 토큰을 박았다.
- **토큰을 남의 설정 파일에 넣지 않는다.** MCP 서버가 자비스 토큰 파일을 직접 읽는다
  (`JARVIS_TOKEN_FILE`). 비밀이 설정 세 곳에 퍼지지 않고, 토큰을 바꿔도 갈라지지 않는다
  (2026-08-08 `.env` ↔ `control.token` 갈림 사고).
- **공식 문서에 적힌 자리·방법만.** 추측한 경로를 박지 않는다.

| 도구 | 방법 | 근거 |
|---|---|---|
| Claude Desktop | `claude_desktop_config.json` 의 `mcpServers` 키만 더함. **스토어판은 패키지 폴더에도 같은 파일**이 있어 둘 다 | 개발 PC 실측(두 파일 크기·시각 동일) |
| Claude Code | `claude mcp add-json … --scope user` (파일 직접 수정 안 함 — 앱이 `.claude.json` 을 수시로 다시 씀) | code.claude.com/docs/en/mcp |
| Cursor | `~/.cursor/mcp.json` 의 `mcpServers` | cursor.com/docs/context/mcp |
| Codex | `codex mcp add` 가 있으면 그것, 없으면 `~/.codex/config.toml` 의 `[mcp_servers.<이름>]` | learn.chatgpt.com/docs/extend/mcp |
| Windsurf | **안 넣음** — 설치된 PC 에서 확인 전 | P4 와 같은 규율 |

## 이미 겪은 것

- 클로드 데스크톱이 **켜진 채로** 설정을 고치면 앱이 종료하며 덮어쓴다(2026-08-08 등록이 사라진 이유).
  → 켜져 있으면 쓰지 않고 「완전히 종료해 주세요」라고 말한다.
- 「설정이 유효한 JSON」은 「그 명령이 뜬다」의 증거가 아니다 → `verify` 가 같은 명령으로 **실제로 띄워**
  도구 목록을 받는다.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from . import msix
from .brand import LEGACY_MCP_SERVER_NAMES, MCP_SERVER_NAME
from .brand import MCP_ALIAS as BRAND_MCP_ALIAS

#: 클로드·커서·코덱스 연결 목록에 뜨는 이름(상표 정리 2026-09-15). 옛 이름(`alture-jarvis`)으로
#: 이미 이어 둔 PC 가 있다 — 잇거나 풀 때 옛 항목도 같이 걷어, 같은 서버가 두 줄로 남지 않게 한다.
SERVER_NAME = MCP_SERVER_NAME
LEGACY_SERVER_NAMES = LEGACY_MCP_SERVER_NAMES
HOOK_MARK = "takeover_hook.py"
# 스토어 패키지의 실행 별칭(`uap5:AppExecutionAlias`). WindowsApps 안 파일은 밖의 앱이 경로로 바로
# 못 띄울 수 있어, 패키지로 돌 때는 설정의 `command` 를 이 이름으로 쓴다(packaging/msix 매니페스트와 같은 값).
MCP_ALIAS = BRAND_MCP_ALIAS
Runner = Callable[..., subprocess.CompletedProcess]


def package_src() -> Path:
    return Path(__file__).resolve().parents[1]


def server_entry(config: Any, *, python: str | None = None) -> dict[str, Any]:
    """MCP 클라이언트에 넣을 한 덩어리. **비밀이 없다.**

    패키지(MSIX)로 돌면 두 가지가 바뀐다(W1).
    - 토큰 경로: 우리가 새로 만든 토큰은 앱 전용 칸에 있다. 밖의 앱이 여는 실제 경로로 푼다.
    - 명령: WindowsApps 안 파이썬 대신 실행 별칭. 별칭 대상이 동봉 파이썬이라 PYTHONPATH 는
      패키지 안 기본 경로를 쓰고, 여기서 개발 소스 경로를 박지 않는다.
    """
    host = str(getattr(config, "host", "127.0.0.1") or "127.0.0.1")
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    token_file = msix.external_path(Path(config.data_dir) / "control.token")
    env = {
        "PYTHONPATH": str(package_src()),
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_BASE_URL": f"http://{host}:{int(getattr(config, 'port', 8091))}",
        "JARVIS_TOKEN_FILE": str(token_file),
        # 되돌릴 수 없는 도구는 밖으로 안 내보낸다(승인 카드가 자비스 창에만 뜬다).
        "JARVIS_MCP_MAX_RISK": "L1",
    }
    command = python or sys.executable
    if msix.is_packaged() and python is None:
        command = str(msix_alias_path())
        env.pop("PYTHONPATH")
    return {"command": command, "args": ["-m", "alture_jarvis.mcp_server"], "env": env}


def msix_alias_path() -> Path:
    """실행 별칭이 놓이는 자리. Windows 가 `%LOCALAPPDATA%\\Microsoft\\WindowsApps` 에 만든다."""
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "Microsoft" / "WindowsApps" / MCP_ALIAS


def _shim_target(exe: str) -> list[str] | None:
    """npm 의 `.cmd` 심이 실제로 띄우는 것 — `"%dp0%\\...\\claude.exe" %*` 나 `node "%dp0%\\...\\cli.js" %*`.

    ★ 2026-09-17 첫 실행 E2E: Claude Code 잇기가 `Invalid configuration: : Invalid input` 으로 실패했다. 연결 설정
      JSON 을 `cmd.exe /s /c` 로 감싸 넘기니 따옴표가 깨져 claude 가 JSON 을 못 읽었다. cmd 를 거치지 않으면 인자가
      그대로 간다. 심을 못 읽으면 None — 예전처럼 cmd 로 감싼다.
    """
    try:
        text = Path(exe).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    folder = Path(exe).parent
    targets = [folder / match.replace("\\", os.sep) for match in re.findall(r'"%dp0%\\([^"]+)"', text)]
    for target in targets:
        if target.suffix.lower() == ".exe" and target.name.lower() != "node.exe" and target.is_file():
            return [str(target)]
    scripts = [t for t in targets if t.suffix.lower() in (".js", ".mjs", ".cjs") and t.is_file()]
    if scripts:
        node = folder / "node.exe"
        node_path = str(node) if node.is_file() else shutil.which("node")
        if node_path:
            return [node_path, str(scripts[0])]
    return None


def _run_cli(run: Runner, exe: str, args: list[str], timeout: float = 90) -> subprocess.CompletedProcess:
    """윈도우의 npm 설치는 `.cmd` 다 — CreateProcess 로 바로 못 띄워, 심이 가리키는 것을 직접 띄운다(못 찾으면 cmd)."""
    if exe.lower().endswith((".cmd", ".bat")):
        direct = _shim_target(exe)
        cmd = [*direct, *args] if direct else ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline([exe, *args])]
    else:
        cmd = [exe, *args]
    return run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _backup(path: Path, clock: Callable[[], float]) -> Path:
    target = path.with_name(f"{path.name}.bak-jarvis-{time.strftime('%Y%m%d-%H%M%S', time.localtime(clock()))}")
    shutil.copy2(path, target)
    return target


#: 이름 바꾸기가 「접근 거부」로 막힐 때 다시 해 보는 간격(초). 합쳐 약 2초.
_REPLACE_RETRY_SEC = (0.05, 0.1, 0.2, 0.3, 0.5, 0.8)


def _atomic_write(path: Path, text: str) -> None:
    """임시 파일에 쓰고 진짜 이름으로 바꾼다 — **남의 프로그램이 그 파일을 읽는 순간이면 잠깐 기다렸다 다시.**

    ★ 2026-10-23 공개 저장소 main 검사(Windows)에서 `claude_desktop_config.json.jarvis-tmp → claude_desktop_config.json` 이
      `PermissionError: [WinError 5]` 로 떨어졌다(PR 검사에서는 통과 · 시험 안의 감시 스레드가 같은 파일을 읽던 순간). 윈도우는 다른 쪽이
      대상 파일을 열고 있으면 이름 바꾸기를 거절한다. 실제 PC 에서도 클로드 데스크톱 · 클로드 코드가 제 설정을 읽는 순간과 겹칠 수 있다
      (서기 훅도 이 함수로 `~/.claude/settings.json` 을 쓴다). 그래서 짧게 몇 번 다시 하고, 끝내 안 되면 임시 파일을 지우고 그대로 알린다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".jarvis-tmp")
    temp.write_text(text, encoding="utf-8")
    for wait in (*_REPLACE_RETRY_SEC, None):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if wait is None:
                try:
                    temp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(wait)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ── Claude Desktop 다시 열기 ──────────────────────────────────────────────────
def _ps_quote(value: str) -> str:
    """PowerShell 작은따옴표 문자열 안에 넣을 값."""
    return str(value).replace("'", "''")


def desktop_reopen_script(exes: list[str]) -> str:
    """닫기 전에 본 실행 파일들로, Claude Desktop 을 다시 여는 PowerShell 한 토막. 열 것이 없으면 빈 값.

    스토어판(`…\\WindowsApps\\Claude_…`)은 실행 파일을 직접 못 띄운다 — 시작 메뉴에 등록된 이름(`Get-StartApps`)으로 연다.
    설치형은 돌던 그 파일을 연다. 이 토막은 **앱 밖에서** 돌린다(`store_update._spawn_outside`): 스토어판 손자리의
    자식으로 뜬 프로그램은 손자리의 전용 칸 안에서 돈다(2026-09-28 — 그렇게 깔린 남의 프로그램이 크롬을 못 띄웠다).
    """
    exes = [str(exe) for exe in exes if exe]
    if not exes:
        return ""
    if any("\\windowsapps\\" in exe.replace("/", "\\").lower() for exe in exes):
        return ("$app = (Get-StartApps | Where-Object { $_.AppID -like 'Claude_*!*' } | Select-Object -First 1).AppID\n"
                "if ($app) { Start-Process explorer.exe \"shell:AppsFolder\\$app\" }\n")
    return f"Start-Process -FilePath '{_ps_quote(min(exes, key=len))}'\n"


# ── TOML (코덱스) — 다른 줄은 한 글자도 안 건드린다 ─────────────────────────────
def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def codex_block(entry: dict[str, Any]) -> str:
    env = ", ".join(f"{k} = {_toml_str(v)}" for k, v in entry["env"].items())
    args = ", ".join(_toml_str(a) for a in entry["args"])
    return (f"[mcp_servers.{SERVER_NAME}]\ncommand = {_toml_str(entry['command'])}\n"
            f"args = [{args}]\nenv = {{ {env} }}\n")


_TABLE = re.compile(r"^\s*\[{1,2}\s*([^\]]+?)\s*\]{1,2}\s*$")


def toml_without_server(text: str) -> str:
    """`[mcp_servers.ontelic]` 표(와 그 하위 표)만 뺀다 — 옛 이름 `alture-jarvis` 표도 같이."""
    out: list[str] = []
    skipping = False
    names = (SERVER_NAME, *LEGACY_SERVER_NAMES)
    for line in text.splitlines(keepends=True):
        match = _TABLE.match(line)
        if match:
            name = match.group(1).strip().strip('"')
            skipping = any(
                name in {f"mcp_servers.{n}", f'mcp_servers."{n}"'} or name.startswith(f"mcp_servers.{n}.")
                for n in names)
        if not skipping:
            out.append(line)
    return "".join(out)


class ConnectService:
    def __init__(
        self,
        config: Any,
        *,
        run: Runner = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        processes: Callable[[], list[str]] | None = None,
        home: Path | None = None,
        appdata: Path | None = None,
        localappdata: Path | None = None,
        clock: Callable[[], float] = time.time,
        python: str | None = None,
        # 지침 블록이 가리킬 스킬 파일을 만들 때 쓰는 도구 목록(없으면 지침만 넣는다).
        exported_tools: Callable[[], list[dict[str, Any]]] | None = None,
        # 켜진 분야 팩의 바깥 AI 용 사용서(2026-09-27) — 잇기가 지침에 「이 분야면 이 파일」 한 줄씩 더한다.
        pack_guides: Callable[[], list[dict[str, Any]]] | None = None,
        # 가이드 본문의 언어(2026-10-19) — 잇기가 코덱스 옆에 두는 가이드 사본도 화면 언어를 따른다. 없으면 한국어.
        guide_lang: Callable[[], str] | None = None,
        # Claude Desktop 을 끄고 켜는 손(`restart_desktop`). 시험은 가짜를 넣는다 — 실제 앱을 끄는 시험을 만들지 않는다.
        desktop_stop: Callable[[list[str]], None] | None = None,
        desktop_launch: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.config = config
        self.run = run
        self.which = which
        self._processes = processes
        self._home = home
        self._appdata = appdata
        self._localappdata = localappdata
        self.clock = clock
        self._python_override = python
        self.python = python or sys.executable
        self.exported_tools = exported_tools
        self.pack_guides = pack_guides
        self.guide_lang = guide_lang
        # Claude Desktop 이 켜져 있어 못 이은 것 — 닫히면 이어 준다(`_wait_for_desktop_close`).
        self._desktop_waiting = False
        self._desktop_wait_result: dict[str, Any] | None = None
        self.desktop_poll_sec = 3.0
        self.desktop_wait_limit_sec = 3 * 3600.0
        self._desktop_write_lock = threading.Lock()
        self._desktop_stop = desktop_stop
        self._desktop_launch = desktop_launch
        # 끈 뒤 다 꺼질 때까지 기다리는 시간 · 다 꺼진 뒤 설정을 쓰기 전에 두는 틈.
        self.desktop_close_poll_sec = 0.3
        self.desktop_close_wait_sec = 20.0
        self.desktop_settle_sec = 1.0

    # ---- 자리 ------------------------------------------------------------
    @property
    def home(self) -> Path:
        return self._home or Path.home()

    @property
    def appdata(self) -> Path:
        return self._appdata or Path(os.environ.get("APPDATA") or self.home / "AppData" / "Roaming")

    @property
    def localappdata(self) -> Path:
        return self._localappdata or Path(os.environ.get("LOCALAPPDATA") or self.home / "AppData" / "Local")

    def entry(self) -> dict[str, Any]:
        return server_entry(self.config, python=self._python_override)

    def desktop_paths(self) -> list[Path]:
        paths = [self.appdata / "Claude" / "claude_desktop_config.json"]
        paths += [Path(p) for p in glob.glob(str(
            self.localappdata / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"))]
        return paths

    def running_processes(self) -> list[str]:
        if self._processes is not None:
            return self._processes()
        try:
            import psutil  # type: ignore

            return [str(p.info.get("exe") or "") for p in psutil.process_iter(["exe"])]
        except Exception:
            pass
        try:
            done = self.run(["powershell", "-NoProfile", "-Command",
                             "Get-CimInstance Win32_Process | ForEach-Object { $_.ExecutablePath }"],
                            capture_output=True, text=True, timeout=20)
            return [line.strip() for line in done.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    #: 이름이 같은 `claude.exe` 지만 **클로드 코드(CLI)** 인 자리. Desktop 앱이 아니다.
    #: ★ 2026-10-01 베타 테스터(회사 PC): 클로드 코드를 **따로 깐** 사람은 `%USERPROFILE%\.local\bin\claude.exe` 가 돈다.
    #:   예전 판별은 `claude-code\`·`npm\` 만 걸러서 이걸 「Desktop 이 켜져 있다」로 봤고, Desktop 을 꺼도 「닫으면 잇습니다」에서
    #:   영영 안 넘어갔다 — 재부팅 뒤 「온텔릭도 해 봤는데 클로드가 그게 뭐임?」.
    _CLI_CLAUDE_PARTS = ("\\claude-code\\", "\\npm\\", "\\node_modules\\", "\\.local\\", "\\.claude\\")

    def _is_desktop_exe(self, exe: str) -> bool:
        low = str(exe or "").replace("/", "\\").lower()
        return low.endswith("\\claude.exe") and not any(part in low for part in self._CLI_CLAUDE_PARTS)

    def desktop_exes(self) -> list[str]:
        """켜져 있는 클로드 데스크톱 앱의 실행 파일들(프로세스마다 하나). 클로드 코드(CLI)는 뺀다."""
        return [exe for exe in self.running_processes() if self._is_desktop_exe(exe)]

    def desktop_running(self) -> bool:
        """클로드 데스크톱 앱이 켜져 있나. 클로드 코드(CLI)의 `claude.exe` 는 앱이 아니다(`_CLI_CLAUDE_PARTS`)."""
        return bool(self.desktop_exes())

    # ---- 찾기 ------------------------------------------------------------
    def scan(self) -> dict[str, Any]:
        entry = self.entry()
        clients = [self._scan_desktop(), self._scan_claude_code(), self._scan_cursor(), self._scan_codex()]
        return {
            "server_name": SERVER_NAME,
            "entry": entry,
            "clients": clients,
            "hooks": self._scan_hooks(),
            "not_supported": [{"name": "Windsurf", "reason": "설정 위치를 설치된 PC 에서 확인하기 전이라 아직 안 넣습니다."}],
        }

    def _desktop_targets(self) -> tuple[list[Path], list[Path]]:
        """(쓸 수 있는 설정 파일, 새로 만들면 Claude 가 못 보는 자리).

        패키지(MSIX)로 돌면 AppData 에 **새로** 만든 파일은 우리 전용 칸으로 간다(실측). 설치형 Claude
        인데 설정 파일이 아직 없으면 거기 쓰는 것은 헛일이다 — 붙여넣기 안내로 보낸다(W1-5).
        """
        candidates = [p for p in self.desktop_paths() if p.exists() or p.parent.exists()]
        hidden = [p for p in candidates if msix.hidden_from_other_apps(
            p, localappdata=self.localappdata, appdata=self.appdata)]
        return [p for p in candidates if p not in hidden], hidden

    def _scan_desktop(self) -> dict[str, Any]:
        paths, hidden = self._desktop_targets()
        registered = []
        for path in paths:
            data = _load_json(path)
            registered.append(bool(data and SERVER_NAME in (data.get("mcpServers") or {})))
        installed = bool(paths or hidden)
        running = self.desktop_running() if installed else False
        reason = "running" if running else ("" if paths else "msix_new_file_hidden" if hidden else "not_installed")
        return {"id": "claude_desktop", "name": "Claude Desktop", "installed": installed,
                "registered": bool(registered) and all(registered),
                "config_paths": [str(p) for p in paths], "running": running,
                # 켜져 있어도 누를 수 있다 — 누르면 닫히는 순간 잇는다(`apply`).
                "can_apply": bool(paths),
                "waiting_for_close": self._desktop_waiting,
                "reason": reason}

    def _claude_cli(self) -> str | None:
        """`claude` 명령. PATH 에 없으면 **Claude Desktop 에 딸린 Claude Code** 를 쓴다.

        ★ 2026-09-17 노트북: Claude Desktop 만 깐 PC 에는 `claude` 가 PATH 에 없어 Claude Code 잇기가 「명령을 찾지 못함 ·
          직접 붙여 넣기」로 빠졌다. 그런데 Desktop 은 `%APPDATA%\Claude\claude-code\<버전>\claude.exe` 를 들고 있고
          (스토어판은 `Packages\Claude_*\LocalCache\Roaming` 아래), 그 exe 가 같은 CLI 다 — 이 PC 에서 `--version`·
          `mcp get` 을 가짜 홈으로 돌려 확인했다. 버전이 여럿이면 가장 새것.
        """
        found = self.which("claude")
        if found:
            return found
        # ★ 2026-10-06 스토어판 첫 설치(노트북): 클로드 코드를 **따로 깐** PC 인데 「명령을 찾지 못함」이 떴다.
        #   따로 깐 것은 사용자 폴더의 `.local/bin/claude.exe` 에 있고(위 `_CLI_CLAUDE_PARTS` 가 이미 아는 자리),
        #   npm 으로 깐 것은 AppData 의 `npm/claude.cmd` 다. PATH 는 앱이 켜진 때의 것이라, 설치 뒤 다시
        #   로그인하지 않았으면 그 자리가 빠져 있다 — PATH 를 믿지 않고 자리를 직접 본다.
        for direct in (self.home / ".local" / "bin" / "claude.exe", self.appdata / "npm" / "claude.cmd"):
            if direct.is_file():
                return str(direct)
        candidates = [Path(p) for p in glob.glob(str(self.appdata / "Claude" / "claude-code" / "*" / "claude.exe"))]
        candidates += [Path(p) for p in glob.glob(str(
            self.localappdata / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude" / "claude-code" / "*" / "claude.exe"))]

        def version(path: Path) -> tuple[int, ...]:
            return tuple(int(part) for part in re.findall(r"\d+", path.parent.name)) or (0,)

        candidates = [path for path in candidates if path.is_file()]
        return str(max(candidates, key=version)) if candidates else None

    def _scan_claude_code(self) -> dict[str, Any]:
        cli = self._claude_cli()
        registered = None
        if cli:
            try:
                registered = _run_cli(self.run, cli, ["mcp", "get", SERVER_NAME]).returncode == 0
            except Exception:
                registered = None
        installed = bool(cli) or (self.home / ".claude").exists()
        return {"id": "claude_code", "name": "Claude Code", "installed": installed, "registered": registered,
                "cli": cli or "", "can_apply": bool(cli),
                "reason": "" if cli else ("cli_missing" if installed else "not_installed")}

    def cursor_path(self) -> Path:
        return self.home / ".cursor" / "mcp.json"

    def _scan_cursor(self) -> dict[str, Any]:
        path = self.cursor_path()
        installed = path.parent.exists() or bool(self.which("cursor"))
        data = _load_json(path)
        return {"id": "cursor", "name": "Cursor", "installed": installed,
                "registered": bool(data and SERVER_NAME in (data.get("mcpServers") or {})),
                "config_paths": [str(path)], "can_apply": installed and data is not None,
                "reason": "" if installed else "not_installed" if data is not None else "config_not_json"}

    def codex_path(self) -> Path:
        return self.home / ".codex" / "config.toml"

    def _scan_codex(self) -> dict[str, Any]:
        path = self.codex_path()
        cli = self.which("codex")
        installed = path.parent.exists() or bool(cli)
        registered = False
        valid = True
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
                registered = SERVER_NAME in (data.get("mcp_servers") or {})
            except (tomllib.TOMLDecodeError, OSError):
                valid = False
        return {"id": "codex", "name": "Codex", "installed": installed, "registered": registered,
                "cli": cli or "", "config_paths": [str(path)], "can_apply": installed and valid,
                "reason": "" if installed and valid else ("config_not_toml" if installed else "not_installed")}

    # ---- 잇기 · 풀기 ------------------------------------------------------
    #
    # ★ 2026-09-16 실측: **설정만 이어 두면 안 부른다.** Codex(GPT-5.6)에게 「사람인에서 공고 찾아 파일로」를
    #   시켰더니 온텔릭 도구를 **0번** 부르고 자기 브라우저·웹 검색으로 했고, 그러고서 「온텔릭으로 했다」고 말했다.
    #   전역 지침 파일(`CLAUDE.md`·`AGENTS.md`)은 스킬과 달리 **매번 읽힌다.** 그래서 잇기 한 번에 둘 다 한다:
    #   설정에 서버 한 줄 + 지침에 「온텔릭 관련이면 이 스킬 파일을 먼저 읽어라」 블록. 풀기도 둘 다 되돌린다.
    def apply(self, client_id: str) -> dict[str, Any]:
        if client_id == "claude_desktop" and self.desktop_running():
            # ★ 2026-09-16 노트북: Claude Desktop 을 쓰면서 온텔릭을 설치하는 사람에게 「앱을 완전히 종료한 뒤 다시
            #   확인을 누르라」는 막다른 길이었다(켜진 채 파일을 바꾸면 앱이 종료하면서 덮어쓴다). 누른 것을 동의로 받고,
            #   **닫히는 순간** 온텔릭이 잇는다.
            paths, _hidden = self._desktop_targets()
            if not paths:
                return self._change(client_id, add=True)
            return self.wait_for_desktop_close()
        result = self._change(client_id, add=True)
        return self._with_note(client_id, result, add=True)

    # ★ 「닫히면 잇기」는 **사람이 누른 동의**다. 예전엔 앱 메모리에만 있어서 재부팅·앱 재시작이면 사라졌다(2026-10-01 베타
    #   테스터: 「잇기」를 누르고 재부팅했더니 연결이 없었다 — 로그인하면 Desktop 이 먼저 떠서 다시 기다릴 기회도 없었다).
    #   표식 파일로 남기고, 앱이 다시 뜨면 이어서 기다린다(`resume_pending`). 이어지거나 풀면 지운다.
    def _pending_path(self) -> Path | None:
        data_dir = getattr(self.config, "data_dir", None)
        return Path(data_dir) / "connect_pending_claude_desktop.json" if data_dir else None

    def _set_pending(self, on: bool) -> None:
        path = self._pending_path()
        if path is None:
            return
        try:
            if on:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"client": "claude_desktop", "since": time.time()}), encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def resume_pending(self) -> dict[str, Any]:
        """앱이 뜰 때 한 번. 지난번에 누른 「잇기」가 아직 안 이어졌으면 다시 기다린다(닫혀 있으면 바로 잇는다)."""
        path = self._pending_path()
        if path is None or not path.exists():
            return {"ok": True, "pending": ""}
        if self._scan_desktop().get("registered"):
            self._set_pending(False)
            return {"ok": True, "pending": "", "already": True}
        return self.wait_for_desktop_close()

    def wait_for_desktop_close(self) -> dict[str, Any]:
        self._set_pending(True)
        if not self._desktop_waiting:
            self._desktop_waiting = True
            self._desktop_wait_result = None
            threading.Thread(target=self._wait_for_desktop_close, name="ontelic-wait-claude-desktop", daemon=True).start()
        return {"ok": True, "pending": "until_claude_desktop_closes"}

    def _wait_for_desktop_close(self) -> None:
        deadline = self.clock() + self.desktop_wait_limit_sec
        try:
            while self.clock() < deadline:
                # ★ 2026-10-12: 다른 길(`restart_desktop`)로 이미 이었으면 끝낸다 — 다시 켠 앱을 보고 「다음 종료」를
                #   세 시간 더 기다리지 않는다.
                if self._scan_desktop().get("registered"):
                    self._desktop_wait_result = {"ok": True, "already": True}
                    self._set_pending(False)
                    return
                if not self.desktop_running():
                    # 앱이 닫히면서 설정 파일을 마지막으로 쓴다 — 그 뒤에 쓴다.
                    time.sleep(min(2.0, self.desktop_poll_sec))
                    if self.desktop_running():
                        continue  # 곧바로 다시 켰다 — 다음 종료를 기다린다
                    self._desktop_wait_result = self._change("claude_desktop", add=True)
                    if self._desktop_wait_result.get("ok"):
                        self._set_pending(False)
                    return
                time.sleep(self.desktop_poll_sec)
            # 시간이 다 돼도 표식은 남긴다 — 다음에 앱이 뜨면 다시 기다린다(사람이 풀기 전까지 동의는 살아 있다).
            self._desktop_wait_result = {"ok": False, "error": "claude_desktop_still_running"}
        finally:
            self._desktop_waiting = False

    # ── 닫고 · 잇고 · 다시 켜기 (2026-10-12) ─────────────────────────────────────
    # 처음 깐 두 사람이 같은 자리에서 헤맸다. 첫 설정의 금색 단추만 따라 누르면 「닫으면 잇습니다」를 지나쳐 끝나고,
    # 「클로드를 껐다 켜라」는 글로만 있었다 — 게다가 창의 X 는 앱을 끄지 않고 작업 표시줄 구석에 남긴다.
    # 글로 시키지 않고 손자리가 한다(사고 R — 안내문은 안 먹는다). 다만 **사람이 「다시 켤까요?」에 누른 뒤에만** 부른다:
    # 그 앱에서 돌던 일(답 쓰는 중 · 코드 작업)이 끊긴다.
    def restart_desktop(self) -> dict[str, Any]:
        paths, hidden = self._desktop_targets()
        # 못 이을 판이면 남의 앱만 꺼 놓지 않는다 — 끄기 **전에** 본다.
        if not paths:
            if hidden:
                return {"ok": False, "error": "msix_new_file_hidden", "manual": self.manual("claude_desktop"),
                        "config_paths": [str(p) for p in hidden]}
            return {"ok": False, "error": "not_installed"}
        for path in paths:
            if _load_json(path) is None:
                return {"ok": False, "error": "config_not_json", "path": str(path)}
        exes = self.desktop_exes()
        if not exes:
            result = self._change("claude_desktop", add=True)
            if result.get("ok"):
                self._set_pending(False)
            return {**result, "desktop": "was_not_running"}
        seen = list(dict.fromkeys(exes))       # 같은 파일이 프로세스마다 한 번씩 온다
        (self._desktop_stop or self._stop_desktop)(seen)
        deadline = time.monotonic() + self.desktop_close_wait_sec
        while self.desktop_running():
            if time.monotonic() >= deadline:
                # 켜진 채 쓰면 앱이 종료하면서 덮어쓴다 — 안 꺼졌으면 설정을 건드리지 않는다.
                return {"ok": False, "error": "claude_desktop_did_not_close"}
            time.sleep(self.desktop_close_poll_sec)
        time.sleep(self.desktop_settle_sec)
        result = self._change("claude_desktop", add=True)
        if result.get("ok"):
            self._set_pending(False)
        # 이었든 못 이었든 다시 켠다 — 우리가 끈 앱이다.
        try:
            reopened = bool((self._desktop_launch or self._launch_desktop)(seen))
        except Exception:  # noqa: BLE001 — 다시 켜기에 실패해도 잇기 결과는 그대로 알린다
            reopened = False
        return {**result, "desktop": "restarted" if reopened else "closed_only"}

    def _desktop_pids(self) -> list[int]:
        """켜져 있는 데스크톱 앱 프로세스의 번호. 클로드 코드(CLI)는 뺀다."""
        try:
            import psutil  # type: ignore

            return [int(p.info["pid"]) for p in psutil.process_iter(["pid", "exe"])
                    if self._is_desktop_exe(str(p.info.get("exe") or ""))]
        except Exception:  # noqa: BLE001 — psutil 이 없으면 윈도우에 묻는다
            pass
        try:
            done = self.run(["powershell", "-NoProfile", "-Command",
                             "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
                             "ForEach-Object { \"$($_.ProcessId)`t$($_.ExecutablePath)\" }"],
                            capture_output=True, text=True, timeout=20)
        except Exception:  # noqa: BLE001
            return []
        pids: list[int] = []
        for line in str(done.stdout or "").splitlines():
            pid, _, exe = line.partition("\t")
            if pid.strip().isdigit() and self._is_desktop_exe(exe.strip()):
                pids.append(int(pid.strip()))
        return pids

    def _stop_desktop(self, exes: list[str]) -> None:
        """데스크톱 앱을 끈다. 창을 닫는 신호로는 안 꺼진다(작업 표시줄 구석으로 숨는다) — 프로세스를 끝낸다.
        그 앱이 띄운 것(코드 탭의 작업)은 같이 끝난다(`/T`). 터미널에서 따로 연 클로드 코드는 그 앱의 자식이 아니다."""
        for pid in self._desktop_pids():
            try:
                self.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            except Exception:  # noqa: BLE001 — 이미 끝난 프로세스
                continue

    def _launch_desktop(self, exes: list[str]) -> bool:
        script = desktop_reopen_script(exes)
        if not script:
            return False
        from .store_update import _spawn_outside

        return _spawn_outside(script) == "0"

    def remove(self, client_id: str) -> dict[str, Any]:
        if client_id == "claude_desktop":
            self._set_pending(False)
        result = self._change(client_id, add=False)
        return self._with_note(client_id, result, add=False)

    def _with_note(self, client_id: str, result: dict[str, Any], *, add: bool) -> dict[str, Any]:
        """지침 블록도 같이. 지침이 실패해도 **연결 자체는 성공으로 둔다** — 둘은 다른 파일이다."""
        if not result.get("ok") or client_id not in ("claude_code", "codex"):
            return result
        try:
            from .guide_skill import GuideSkillService

            service = GuideSkillService(home=self.home, pack_guides=self.pack_guides, lang=self.guide_lang)
            tools = self.exported_tools() if self.exported_tools else []
            note = service.install_note(client_id, tools) if add else service.remove_note(client_id)
        except Exception as exc:  # noqa: BLE001 — 지침 실패가 연결을 되돌리면 안 된다
            result["note_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            return result
        if note.get("ok"):
            result["note_path"] = note.get("path", "")
            if note.get("backup"):
                result.setdefault("backups", []).append(note["backup"])
        else:
            result["note_error"] = str(note.get("error") or "")
        return result

    def _change(self, client_id: str, *, add: bool) -> dict[str, Any]:
        entry = self.entry()
        if client_id == "claude_desktop":
            if self.desktop_running():
                return {"ok": False, "error": "claude_desktop_running"}
            paths, hidden = self._desktop_targets()
            if not paths:
                if hidden:
                    return {"ok": False, "error": "msix_new_file_hidden", "manual": self.manual(client_id),
                            "config_paths": [str(p) for p in hidden]}
                return {"ok": False, "error": "not_installed"}
            with self._desktop_write_lock:
                return self._json_change(paths, entry, add=add)
        if client_id == "cursor":
            return self._json_change([self.cursor_path()], entry, add=add)
        if client_id == "claude_code":
            cli = self._claude_cli()
            if not cli:
                return {"ok": False, "error": "cli_missing", "manual": self.manual(client_id)}
            for name in (SERVER_NAME, *LEGACY_SERVER_NAMES):
                _run_cli(self.run, cli, ["mcp", "remove", name, "--scope", "user"])
            if not add:
                return {"ok": True}
            done = _run_cli(self.run, cli, ["mcp", "add-json", SERVER_NAME,
                                            json.dumps({"type": "stdio", **entry}, ensure_ascii=False),
                                            "--scope", "user"])
            if done.returncode != 0:
                return {"ok": False, "error": "cli_failed", "detail": (done.stderr or done.stdout)[-300:]}
            check = _run_cli(self.run, cli, ["mcp", "get", SERVER_NAME])
            return {"ok": check.returncode == 0, "error": "" if check.returncode == 0 else "not_visible_after_add"}
        if client_id == "codex":
            return self._codex_change(entry, add=add)
        return {"ok": False, "error": "unknown_client"}

    def _json_change(self, paths: list[Path], entry: dict[str, Any], *, add: bool) -> dict[str, Any]:
        backups: list[str] = []
        for path in paths:
            data = _load_json(path)
            if data is None:
                return {"ok": False, "error": "config_not_json", "path": str(path)}
        for path in paths:
            data = _load_json(path) or {}
            if path.exists():
                backups.append(str(_backup(path, self.clock)))
            servers = dict(data.get("mcpServers") or {})
            for legacy in LEGACY_SERVER_NAMES:
                servers.pop(legacy, None)
            if add:
                servers[SERVER_NAME] = entry
            else:
                servers.pop(SERVER_NAME, None)
            data["mcpServers"] = servers
            _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            back = _load_json(path) or {}
            if (SERVER_NAME in (back.get("mcpServers") or {})) != add:
                return {"ok": False, "error": "not_saved", "path": str(path), "backups": backups}
        return {"ok": True, "paths": [str(p) for p in paths], "backups": backups}

    def _codex_change(self, entry: dict[str, Any], *, add: bool) -> dict[str, Any]:
        cli = self.which("codex")
        if cli:
            for name in (SERVER_NAME, *LEGACY_SERVER_NAMES):
                _run_cli(self.run, cli, ["mcp", "remove", name])
            if not add:
                return {"ok": True}
            args = ["mcp", "add", SERVER_NAME]
            for key, value in entry["env"].items():
                args += ["--env", f"{key}={value}"]
            done = _run_cli(self.run, cli, [*args, "--", entry["command"], *entry["args"]])
            return {"ok": done.returncode == 0, "error": "" if done.returncode == 0 else "cli_failed",
                    "detail": "" if done.returncode == 0 else (done.stderr or done.stdout)[-300:]}
        path = self.codex_path()
        if not path.parent.exists():
            return {"ok": False, "error": "not_installed"}
        original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        try:
            tomllib.loads(original)
        except tomllib.TOMLDecodeError:
            return {"ok": False, "error": "config_not_toml"}
        text = toml_without_server(original)
        if add:
            text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + codex_block(entry)
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return {"ok": False, "error": "would_break_toml"}
        if (SERVER_NAME in (parsed.get("mcp_servers") or {})) != add:
            return {"ok": False, "error": "not_saved"}
        backup = str(_backup(path, self.clock)) if path.exists() else ""
        _atomic_write(path, text)
        return {"ok": True, "paths": [str(path)], "backups": [backup] if backup else []}

    def manual(self, client_id: str) -> str:
        entry = self.entry()
        if client_id == "codex":
            return codex_block(entry)
        return json.dumps({"mcpServers": {SERVER_NAME: entry}}, ensure_ascii=False, indent=2)

    # ---- 확인 — 실제로 띄운다 -----------------------------------------------
    def verify(self, *, timeout: float = 45.0) -> dict[str, Any]:
        entry = self.entry()

        async def _probe() -> int:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(command=entry["command"], args=entry["args"],
                                           env={**os.environ, **entry["env"]})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return len((await session.list_tools()).tools)

        try:
            count = asyncio.run(asyncio.wait_for(_probe(), timeout))
        except Exception as exc:  # noqa: BLE001 — 실패 이유가 화면에 가야 한다
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {"ok": count > 0, "tool_count": count}

    # ---- 선택: 클로드 코드가 돌아왔을 때 알려 주는 훅 --------------------------
    def settings_path(self) -> Path:
        return self.home / ".claude" / "settings.json"

    def hook_entry(self) -> dict[str, Any]:
        script = Path(getattr(self.config, "runtime_root", package_src().parent)) / "scripts" / HOOK_MARK
        env = self.entry()["env"]
        return {"type": "command", "command": self.python,
                "args": [str(script), "session-start", "--base-url", env["JARVIS_BASE_URL"],
                         "--token-file", env["JARVIS_TOKEN_FILE"]],
                "timeout": 10}

    @staticmethod
    def _is_ours(hook: Any) -> bool:
        return isinstance(hook, dict) and any(HOOK_MARK in str(a) for a in (hook.get("args") or [hook.get("command")]))

    def _scan_hooks(self) -> dict[str, Any]:
        data = _load_json(self.settings_path())
        groups = ((data or {}).get("hooks") or {}).get("SessionStart") or []
        on = any(self._is_ours(h) for g in groups if isinstance(g, dict) for h in (g.get("hooks") or []))
        return {"claude_code_session_start": on, "settings_path": str(self.settings_path()),
                "can_apply": data is not None}

    def set_hook(self, enabled: bool) -> dict[str, Any]:
        path = self.settings_path()
        data = _load_json(path)
        if data is None:
            return {"ok": False, "error": "config_not_json"}
        hooks = dict(data.get("hooks") or {})
        groups = []
        for group in hooks.get("SessionStart") or []:
            if not isinstance(group, dict):
                groups.append(group)
                continue
            kept = [h for h in (group.get("hooks") or []) if not self._is_ours(h)]
            if kept:
                groups.append({**group, "hooks": kept})
        if enabled:
            groups.append({"matcher": "startup|resume", "hooks": [self.hook_entry()]})
        if groups:
            hooks["SessionStart"] = groups
        else:
            hooks.pop("SessionStart", None)
        if hooks:
            data["hooks"] = hooks
        else:
            data.pop("hooks", None)
        backup = str(_backup(path, self.clock)) if path.exists() else ""
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return {"ok": self._scan_hooks()["claude_code_session_start"] == enabled, "backup": backup}


__all__ = ["ConnectService", "LEGACY_SERVER_NAMES", "SERVER_NAME", "codex_block", "server_entry", "toml_without_server"]
