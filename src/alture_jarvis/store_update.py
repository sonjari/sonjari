"""스토어 설치(MSIX)에 **새 버전이 있다고 알려 주는 것** (2026-09-18 사용자 요청).

## 왜 필요한가

윈도우가 알아서 갱신해 주긴 한다(App Installer, `OnLaunch`). 그런데 **사람에게는 아무 말도 안 한다.**
그래서 켤 때마다 「바뀐 게 있나」를 알 수 없고, 갱신이 실패해도 조용하다. 첫 실행 마법사는 한 번만 도니
거기 붙일 수도 없다. 제품 화면에 이미 있는 업데이트 줄(`UpdateBar`)은 위성 전용이라 스토어 설치에는 안 떴다.

## 규율

- **주소를 코드에 박지 않는다.** 설치할 때 쓴 `.appinstaller` 주소는 윈도우가 기억하고 있다
  (`Get-AppxPackage … .GetAppInstallerInfo().Uri`). 사람마다 채널이 다를 수 있으니 거기서 읽는다.
- **아무것도 바꾸지 않는다.** 물어보고 견주기만 한다. 적용은 윈도우가 앱을 켤 때 한다.
- 패키지 밖(개발기·위성)에서는 아무 일도 안 한다 — 그쪽은 기존 경로(`update_check`)가 맡는다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from .msix import package_full_name

CREATE_NO_WINDOW = 0x08000000
#: 버전 네 칸(`0.4.26261.350`). 스토어 패키지 버전 규칙 그대로다.
_VERSION = re.compile(r"^\d+(\.\d+){1,3}$")

_PS_APPINSTALLER = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$p = Get-AppxPackage -Name '{name}'; "
    # ★ 2026-09-20 노트북 실측: 파워셸 5.1 의 `Get-AppxPackage` 결과에는 `GetAppInstallerInfo()` 가 **없다**
    #   (「이름이 GetAppInstallerInfo 인 메서드가 없으므로」). 그래서 이 확인은 모든 PC 에서 늘 「채널 없음」이었고
    #   「지금 업데이트」 버튼은 한 번도 뜰 수 없었다 — 9/18 시험은 가짜 응답만 봤다. 그 메서드는 WinRT
    #   `PackageManager` 가 주는 `Package` 에 있다(노트북에서 채널 주소가 실제로 나왔다).
    "if ($p) {{ $uri = ''; try {{ "
    "$null = [Windows.Management.Deployment.PackageManager, Windows.Management.Deployment, ContentType = WindowsRuntime]; "
    "$info = (New-Object Windows.Management.Deployment.PackageManager).FindPackageForUser('', $p.PackageFullName)"
    ".GetAppInstallerInfo(); "
    "if ($info -and $info.Uri) {{ $uri = $info.Uri.AbsoluteUri }} }} catch {{ }}; "
    "ConvertTo-Json -Compress @{{ version = $p.Version.ToString(); uri = $uri }} }}"
)


def _run_powershell(script: str, timeout: float = 20.0) -> str:
    done = subprocess.run(  # noqa: S603 - 고정된 스크립트
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return done.stdout or ""


#: 빌드가 적어 둔 채널 주소(`build_app_package.ps1 -UpdateChannel`). 윈도우가 주소를 모를 때만 쓴다.
_BAKED_CHANNEL = Path(__file__).with_name("update_channel.txt")


def baked_channel() -> str:
    """이 판이 올라간 채널의 `.appinstaller` 주소. 없거나 https 가 아니면 빈 문자열.

    ★ 2026-09-20 노트북: `.msix` 를 받아 직접 깐 설치는 윈도우가 채널 주소를 모른다 — 업데이트 버튼이
      영영 안 떴다(「이 설치에는 업데이트 채널이 없습니다」). 주소를 코드에 박는 대신 **빌드가 그 판이
      올라간 채널을 적어 둔다.** 그 채널로 한 번 깔고 나면 윈도우도 주소를 기억한다(도우미가
      `-AppInstallerFile` 로 깐다).
    """
    try:
        value = _BAKED_CHANNEL.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return ""
    return value if value.lower().startswith("https://") and value.lower().endswith(".appinstaller") else ""


def installed(full_name: str = "", *, run: Callable[[str], str] | None = None) -> dict[str, str]:
    """지금 깔려 있는 버전과, 설치할 때 쓴 `.appinstaller` 주소. 못 알아내면 빈 값.

    윈도우가 기억하는 주소가 먼저다. 없으면 빌드가 적어 둔 주소(`baked_channel`)."""
    name = (full_name or package_full_name()).split("_", 1)[0]
    if not name:
        return {"version": "", "uri": ""}
    try:
        raw = (run or _run_powershell)(_PS_APPINSTALLER.format(name=name))
        data = json.loads(raw.strip() or "{}")
    except Exception:  # noqa: BLE001 - 못 물어보면 「모른다」로 둔다
        return {"version": "", "uri": ""}
    return {"version": str(data.get("version") or ""), "uri": str(data.get("uri") or "") or baked_channel()}


def channel_version(uri: str, *, fetch: Callable[[str], bytes] | None = None) -> str:
    """채널의 `.appinstaller` 가 말하는 **가장 새 버전**. 못 읽으면 빈 문자열."""
    if not uri.lower().startswith("https://"):
        return ""  # http 로 받은 갱신 정보는 믿지 않는다
    try:
        raw = (fetch or _fetch)(uri)
        root = ElementTree.fromstring(raw)
    except Exception:  # noqa: BLE001 - 밖에 못 나가는 것은 흔한 일이다
        return ""
    found = str(root.get("Version") or "")
    if not found:
        for child in root:
            if child.tag.endswith("MainPackage"):
                found = str(child.get("Version") or "")
                break
    return found if _VERSION.fullmatch(found) else ""


def _fetch(url: str, timeout: float = 15.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Ontelic-UpdateCheck/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https 만 온다
        return response.read(2_000_000)


def is_newer(theirs: str, mine: str) -> bool:
    """`0.4.26261.350` > `0.4.26261.206`. 칸 수가 달라도 숫자로 견준다."""
    def parts(value: str) -> tuple[int, ...]:
        return tuple(int(one) for one in value.split(".") if one.isdigit())

    left, right = parts(theirs), parts(mine)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def check(*, run: Callable[[str], str] | None = None, fetch: Callable[[str], bytes] | None = None,
          full_name: str = "") -> dict[str, Any]:
    """스토어 설치에 새 버전이 있나. 패키지 밖이면 `{"kind": "none"}`.

    돌려주는 것: `kind`(store/none) · `mine` · `theirs` · `available` · `reason`.
    적용 방법은 하나뿐이라 말로 적어 보낸다 — **앱을 껐다 켜면** 윈도우가 바꾼다.
    """
    name = full_name or package_full_name()
    if not name:
        return {"kind": "none", "available": False}
    here = installed(name, run=run)
    if not here["uri"]:
        # 스토어에서 받은 설치는 스토어가 갱신한다. USB·직접 설치는 채널 자체가 없다.
        return {"kind": "store", "available": False, "mine": here["version"],
                "reason": "이 설치에는 업데이트 채널이 없습니다"}
    theirs = channel_version(here["uri"], fetch=fetch)
    if not theirs:
        return {"kind": "store", "available": False, "mine": here["version"],
                "reason": "업데이트 서버에 못 닿았습니다"}
    return {
        "kind": "store",
        "mine": here["version"],
        "theirs": theirs,
        "available": is_newer(theirs, here["version"]),
        "how": "restart",  # 사람이 할 일: 온텔릭을 껐다 켜면 윈도우가 바꾼다
    }


# ── 「지금 업데이트」 (2026-09-18 밤 사용자 요청) ─────────────────────────────────
#
# 윈도우는 앱을 켤 때 몰래 받아 두고 **다음에 켤 때** 바꾼다 — 그래서 「두 번 켜야 할 때가 있다」.
# 사람에게는 무엇이 언제 끝나는지 안 보인다. 그래서 버튼을 두고, 누르면 우리가 **지금** 바꾼다.
#
# 스토어판은 실행 중인 자기를 못 바꾼다 — 설치하려면 윈도우가 앱을 끈다. 그래서 설치와 다시 열기는
# **앱 밖의 도우미**가 한다. 실측(2026-09-18, 개발용 등록한 실제 포장 앱):
#
#     앱 안에서 띄운 도우미 셋(자식·WMI·작업 스케줄러)   앱을 강제로 끈 뒤에도 셋 다 살아 있었다
#     바깥에서 shell:AppsFolder 로 다시 열기            1초 만에 백엔드가 떴다
#
# 그중 WMI(`Win32_Process.Create`)를 쓴다 — 부모가 윈도우 서비스라 앱과 가장 확실히 끊긴다.
# 스크립트는 파일 경로 대신 `-EncodedCommand` 로 넘긴다: 한글 경로가 자식 인자로 깨지는 사고(J-2)가 원천적으로 없다.
#
# ★ 윈도우 명령의 스위치 이름은 **재 보고** 썼다 — `-Path <채널> -AppInstallerFile -ForceTargetApplicationShutdown`
#   (`Get-Command Add-AppxPackage -Syntax`). 짐작한 `-ForceApplicationShutdown` 은 이 매개변수 묶음에 없다.
#   `-Path <msix>` 로 바로 깔면 채널 연결이 끊겨 다음부터 자동 갱신이 안 될 수 있어 채널 방식을 쓴다.

import base64

RESULT_NAME = "last_update.json"


def family_of(full_name: str) -> str:
    """`Name_Version_Arch_Resource_Publisher` → `Name_Publisher`(다시 열 때 쓰는 이름)."""
    parts = str(full_name or "").split("_")
    if len(parts) < 5:
        return ""
    return f"{parts[0]}_{parts[-1]}"


def _quote(value: str) -> str:
    """PowerShell 작은따옴표 문자열 안에 넣을 값."""
    return str(value).replace("'", "''")


def helper_script(*, uri: str, name: str, family: str, mine: str, theirs: str, result_dir: str) -> str:
    """앱 밖에서 돌 도우미. **결과를 먼저 적고**, 성공하든 실패하든 앱을 다시 연다."""
    return f"""$ErrorActionPreference = 'Stop'
$dir = '{_quote(result_dir)}'
New-Item -ItemType Directory -Force $dir | Out-Null
$status = Join-Path $dir '{RESULT_NAME}'
function Save($o) {{ ($o | ConvertTo-Json -Compress) | Set-Content -Path $status -Encoding UTF8 }}
Save @{{ phase = 'installing'; from = '{_quote(mine)}'; to = '{_quote(theirs)}'; started = (Get-Date).ToString('o') }}
Start-Sleep -Seconds 2
$ok = $true; $err = ''
try {{
  Add-AppxPackage -Path '{_quote(uri)}' -AppInstallerFile -ForceTargetApplicationShutdown
}} catch {{ $ok = $false; $err = $_.Exception.Message }}
$now = ''
try {{ $now = (Get-AppxPackage -Name '{_quote(name)}').Version.ToString() }} catch {{}}
Save @{{ phase = 'done'; ok = $ok; from = '{_quote(mine)}'; to = '{_quote(theirs)}'; installed = $now; error = $err; finished = (Get-Date).ToString('o'); shown = $false }}
Start-Sleep -Seconds 1
Start-Process explorer.exe 'shell:AppsFolder\{_quote(family)}!App'
"""


def _spawn_outside(script: str, *, run: Callable[[str], str] | None = None) -> str:
    """WMI 로 **앱과 끊긴** 프로세스를 띄운다. 돌려주는 것은 WMI 의 답(ReturnValue 0 이 성공)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = f"powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {encoded}"
    launcher = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{ CommandLine = '{_quote(command)}' }}; $r.ReturnValue"
    )
    return (run or _run_powershell)(launcher).strip()


def apply(result_dir: str, *, run: Callable[[str], str] | None = None,
          fetch: Callable[[str], bytes] | None = None, full_name: str = "") -> dict[str, Any]:
    """새 버전을 **지금** 깔고 다시 연다. 돌려주는 값은 「시작했다」이지 「됐다」가 아니다 — 이 앱은 곧 꺼진다."""
    name_full = full_name or package_full_name()
    if not name_full:
        return {"ok": False, "applied": False, "reason": "스토어 설치가 아닙니다"}
    state = check(run=run, fetch=fetch, full_name=name_full)
    if not state.get("available"):
        return {"ok": True, "applied": False, "reason": state.get("reason") or "이미 최신입니다", **state}
    here = installed(name_full, run=run)
    family = family_of(name_full)
    if not (here["uri"] and family):
        return {"ok": False, "applied": False, "reason": "업데이트 채널을 못 찾았습니다"}
    script = helper_script(uri=here["uri"], name=name_full.split("_", 1)[0], family=family,
                           mine=str(state.get("mine") or ""), theirs=str(state.get("theirs") or ""),
                           result_dir=str(result_dir))
    answer = _spawn_outside(script, run=run)
    if answer != "0":
        return {"ok": False, "applied": False, "reason": f"도우미를 못 띄웠습니다(WMI {answer or '응답 없음'})"}
    return {"ok": True, "applied": True, "kind": "store", "mine": state.get("mine"), "theirs": state.get("theirs")}


def last_result(result_dir: str) -> dict[str, Any]:
    """도우미가 남긴 결과. 없거나 이미 보여 줬으면 빈 값."""
    path = Path(result_dir) / RESULT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("phase") != "done" or data.get("shown"):
        return {}
    return data


def mark_shown(result_dir: str) -> None:
    """사람에게 한 번 보여 줬다 — 다시 안 띄운다."""
    path = Path(result_dir) / RESULT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        data["shown"] = True
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        return


__all__ = ["apply", "channel_version", "check", "family_of", "helper_script", "installed", "is_newer",
           "last_result", "mark_shown"]
