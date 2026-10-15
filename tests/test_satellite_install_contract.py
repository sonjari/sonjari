"""위성 설치가 **조용히 반쪽으로 끝나지 않는가.**

## 왜 이 파일이 생겼는가

2026-08-22, 나래님 노트북에서 실제로 두 개가 났다.

### ① 실패를 성공으로 찍었다

    [8] 로그인 시 자동 시작 등록
    ERROR: Access is denied.
        OK  RoboMetaFit-Alture-Jarvis 등록      <- 스크립트는 OK 라고 찍는다

`schtasks /Create` 를 `| Out-Null` 로 삼키고 종료코드를 안 봤다. 그래서 작업이
안 만들어졌는데 다음 단계가 **없는 작업을 실행하려다** 죽었다.
**예외가 없다고 성공이 아니다** — 이 저장소가 여러 번 데인 그 모양이다.

### ② 패키지를 venv 에 등록하지 않았다

    ModuleNotFoundError: No module named 'alture_jarvis'

`src/` 를 복사만 하고 `pip install -e .` 를 안 했다. 설치는 전부 OK 로 끝나는데
띄우면 죽는다. 본체는 `install.ps1` 이 그 줄을 갖고 있다 — **새로 쓰면서 원본이
하던 일을 안 옮긴 것이다.**

### ③ 같은 일을 두 곳에서 해야 했는데 한 곳을 잊었다

젬마는 `OLLAMA_HOST=0.0.0.0` 으로 열었는데 음성 합성(:7788)은 안 열었다.
그래서 위성이 "음성 합성에 못 닿습니다"를 띄웠다. 게다가 스크립트 기본값을
고쳐도 안 됐다 — **작업 스케줄러가 `--host 127.0.0.1` 을 인자로 박아** 두고
스크립트를 아예 안 거치고 있었기 때문이다.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _read(name: str) -> str:
    return io.open(_SCRIPTS / name, encoding="utf-8-sig", errors="replace").read()


def test_installer_checks_whether_schtasks_actually_worked() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    `schtasks` 가 막혀도(회사 정책) 스크립트가 OK 를 찍으면, 사람은 설치가 된
    줄 알고 다음 단계로 간다. 그리고 거기서 처음 실패한다 — 원인에서 두 단계
    떨어진 곳에서.
    """
    body = _read("install_satellite.ps1")

    assert "schtasks /Create" in body
    assert "$LASTEXITCODE" in body, "schtasks 결과를 안 본다 — 실패를 성공으로 찍게 된다"


def test_installer_has_a_fallback_when_schtasks_is_blocked() -> None:
    """막혔을 때 **다른 길**이 있어야 한다. 시작프로그램 폴더는 관리자가 필요 없다."""
    body = _read("install_satellite.ps1")

    assert "GetFolderPath(\"Startup\")" in body or "GetFolderPath('Startup')" in body
    assert "JARVIS.lnk" in body


def test_voice_server_binds_where_satellites_can_reach_it() -> None:
    """젬마만 열고 음성 합성을 안 열면 위성이 벙어리가 된다.

    같은 일을 두 곳에서 해야 하면 한 곳은 잊는다 — 그 자리다.
    """
    body = _read("start_supertonic.ps1")
    match = re.search(r"\$HostAddress\s*=\s*(.+)", body)

    assert match, "HostAddress 기본값을 못 찾았다"
    default = match.group(1)
    assert "0.0.0.0" in default, "loopback 에만 묶이면 위성이 못 닿는다"
    # 되돌릴 손잡이가 있어야 한다.
    assert "JARVIS_SUPERTONIC_HOST" in default


@pytest.mark.parametrize(
    "phrase",
    [
        "본체에 닿는가",        # 1단계: 닿는지부터 본다
        "-WithVoice",           # 음성은 선택
        "ctranslate2",          # 깔았다고 도는 게 아니라 GPU 를 실제로 확인한다
    ],
)
def test_installer_keeps_its_discipline(phrase: str) -> None:
    assert phrase in _read("install_satellite.ps1"), f"'{phrase}' 가 사라졌다"


def test_installer_registers_the_package_in_the_venv() -> None:
    """★ 복사만으로는 안 돈다.

    `src/` 를 옮겨 놔도 venv 가 `alture_jarvis` 를 모르면 띄우는 순간 죽는다.
    그리고 설치 로그는 **전부 OK 로 끝난다** — 실패가 두 단계 뒤에서 나타난다.
    """
    body = _read("install_satellite.ps1")

    assert "pip install --quiet -e" in body or "pip install -e" in body, (
        "패키지를 venv 에 등록하지 않는다 — ModuleNotFoundError 가 난다"
    )


def test_installer_verifies_the_import_actually_works() -> None:
    """깔았다고 도는 게 아니다. **실제로 import 해 본다.**

    이 저장소의 규율이다 — 생존 검사는 실제 왕복으로.
    """
    body = _read("install_satellite.ps1")

    assert "import alture_jarvis" in body, "등록만 하고 확인을 안 한다"


def test_installer_ships_the_screen_too() -> None:
    """★ 백엔드만 깔면 `/health` 는 ok:true 인데 **볼 창이 없다.**

    2026-08-22 나래님 노트북에서 실제로 그랬다. 설치는 다 됐다고 나오고 자비스도
    돌고 있는데, 바탕화면 아이콘을 눌러도 아무 일이 없었다 — 그 아이콘이
    **백엔드**를 가리키고 있었기 때문이다(이미 떠 있는 그것).

    도는 것과 쓸 수 있는 것은 다르다.
    """
    body = _read("install_satellite.ps1")

    assert '"ui"' in body, "ui 를 안 옮긴다 — 화면 없이 백엔드만 깔린다"
    assert "alture-jarvis-hud.exe" in body, "화면 실행파일을 모른다"


def test_desktop_shortcut_points_at_the_screen_not_the_backend() -> None:
    """바탕화면은 **화면**, 시작프로그램은 **백엔드**. 둘을 바꾸면 아무 일도 안 난다."""
    body = _read("install_satellite.ps1")
    desktop = body[body.index('GetFolderPath("Desktop")'):]

    # 바탕화면 바로가기의 TargetPath 가 exe 여야 한다.
    target = desktop[: desktop.index("Save()")]
    assert "hud" in target.lower(), "바탕화면 바로가기가 화면을 안 가리킨다"
    assert "task_entry" not in target, "바탕화면이 백엔드를 가리킨다 - 눌러도 아무 일이 없다"


def test_installer_says_what_each_person_must_do_themselves() -> None:
    """★ 설치로 안 되는 것을 말 안 하면, 안 되는 것을 고장으로 여긴다.

    구글은 사람마다 자기 계정으로 연결해야 하고, 네이버 로그인도 각자다.
    """
    body = _read("install_satellite.ps1")

    assert "구글" in body and "연결" in body
    assert "InhouseApiKey" in body, "우리 DB 키를 넘길 자리가 없다"


def test_installer_is_bom_encoded() -> None:
    """한글 리터럴이 든 .ps1 은 BOM 이 없으면 PowerShell 5.1 이 cp949 로 읽어 깨진다.

    사고 J 그것이다.
    """
    raw = io.open(_SCRIPTS / "install_satellite.ps1", "rb").read(3)

    assert raw == b"\xef\xbb\xbf", "BOM 이 없다 — 한글이 깨진다"

def test_the_satellite_uses_the_same_model_tag_as_the_brain() -> None:
    """★ 태그가 갈리면 **위성이 본체 모델을 축출한다.**

    위성은 본체의 올라마(:11434)를 빌려 쓴다. 그런데 설치기가
    `JARVIS_OLLAMA_MODEL` 을 안 써 주면 설정 기본값(`plopfit-gemma4:latest`)으로
    떨어지고, 본체 자비스는 `plopfit-gemma4-qat` 를 쓴다.
    `OLLAMA_MAX_LOADED_MODELS=1` 이라 **위성이 한 번 말을 걸 때마다 본체 모델이
    GPU 에서 밀려난다.**

    실측(2026-08-23): 나래님 노트북에서 위성을 쓰는 동안 본체 벤치가 판마다
    19GB 재적재에 걸려 과제 하나가 244초씩 걸렸다. 본체에선 "자비스가 갑자기
    느려졌다"로 보이고 위성 쪽엔 아무 표시도 안 난다 — 사고 P 의 새 경로다.

    이름을 짐작하지 않고 **본체에 물어본다**(`/api/ps` → `/api/tags` → 폴백).
    두 벌을 두면 갈리고, 갈린 쪽은 조용히 틀린다.
    """
    body = _read("install_satellite.ps1")

    assert "JARVIS_OLLAMA_MODEL=" in body, (
        "위성이 모델 태그를 안 정한다 — 기본값으로 떨어져 본체 모델을 축출한다"
    )
    assert "/api/ps" in body, "본체가 지금 올려 둔 모델을 물어보지 않는다"
    assert "$BrainModel" in body, "물어본 값을 .env 에 안 넘긴다"


def test_no_stray_control_bytes_in_powershell_scripts() -> None:
    """★ 2026-09-06. `ui\alture-jarvis-hud.exe` 가 파일 안에서
    `ui<0x07>lture-jarvis-hud.exe` 로 굳어 있었다.

    누군가 이 파일을 `\a` 를 해석하는 도구로 쓰면서 백슬래시-a 가 **벨 문자**가
    된 것이다. `Test-Path` 가 늘 거짓이 되므로 9단계(바탕화면 아이콘)가 조용히
    건너뛰어졌고, 화면 없이 백엔드만 깔린다 — 이미 한 번 겪은 그 증상이다
    (`c02ad04d` "화면 없이 백엔드만 깔렸다").

    위의 바로가기 검사들은 이걸 **못 잡았다.** `hud` 라는 글자는 그대로 있었기
    때문이다. 그래서 글자가 아니라 **바이트**를 본다.
    """
    bad: list[str] = []
    for path in sorted(_SCRIPTS.glob("*.ps1")):
        raw = path.read_bytes()
        for offset, byte in enumerate(raw):
            # \t(0x09) \r(0x0d) \n(0x0a) 만 정상. 나머지 제어문자는 사고다.
            if byte < 0x20 and byte not in (0x09, 0x0A, 0x0D):
                bad.append(f"{path.name}:{offset} 0x{byte:02x}")
                break
    assert not bad, "제어문자가 섞였다(경로가 조용히 깨진다): " + ", ".join(bad)


def test_repair_script_exists_and_does_not_assume_a_living_backend() -> None:
    """★ 「지금 받기」는 **백엔드가 살아 있어야** 눌린다 — 정작 필요할 때 없다.

    2026-09-06, 나래님 노트북에서 자비스가 통째로 죽었다. 화면은 FAIL 만 띄우고
    갱신 버튼도 같이 죽어 있었다. 본체에서 들여다볼 수도 없다 — 위성은 설계상
    `127.0.0.1` 에만 귀를 연다.

    그래서 복구본은 **아무것도 가정하지 않아야** 한다: 백엔드가 죽어 있어도 돌고,
    설치본의 스크립트가 낡았어도 본체에서 새로 받아 쓰고, 끝나면 결과를 사람이
    옮겨 적지 않아도 본체가 볼 수 있어야 한다.
    """
    body = _read("repair_satellite.ps1")

    # 백엔드에 부탁하지 않는다 — 본체에서 직접 받는다.
    assert "/v1/update/payload" in body, "본체에서 직접 안 받는다 — 백엔드가 죽으면 무력하다"
    # 설치본의 낡은 스크립트를 쓰지 않는다 (그 버그는 자기 자신을 못 고친다).
    assert "repair-staging" in body, "받은 것 안의 스크립트를 안 쓴다"
    # 백엔드가 못 뜨는 첫째 원인을 갱신보다 **먼저** 잡는다.
    assert "pip" in body and "install" in body, "패키지 미설치를 안 잡는다"
    # 껐다 켜도 뜨게 — 이 노트북은 schtasks 가 막혀 있다.
    assert 'GetFolderPath("Startup")' in body, "자동 시작을 안 건다"
    # 결과를 사람 입이 아니라 파일로 본체에 보낸다.
    assert "file" in body and "cp" in body and "tailscale" in body.lower(), "결과를 본체로 안 보낸다"


def test_repair_script_is_utf8_bom() -> None:
    """PS 5.1 은 BOM 없는 UTF-8 .ps1 을 cp949 로 읽는다. 한글 리터럴의 따옴표
    짝이 어긋나면서 **파일 전체가 파싱 에러**가 된다 — 실제로 첫 실행이 그렇게
    죽었다(2026-09-06). 사고 J 와 같은 병이다."""
    raw = (_SCRIPTS / "repair_satellite.ps1").read_bytes()[:3]
    assert raw == b"\xef\xbb\xbf", "BOM 이 없다 — 스크립트가 통째로 파싱 에러가 된다"


def test_autostart_registers_the_voice_server_where_satellites_can_reach_it() -> None:
    """★ 같은 값이 두 곳에 있었고, 실제로 도는 쪽을 3주 동안 안 고쳤다.

    2026-08-22 에 `start_supertonic.ps1` 의 기본값을 `0.0.0.0` 으로 고치고 그
    스크립트에만 검사를 걸었다. 그런데 **실제로 도는 것은 그 스크립트가 아니다** —
    예약 작업이 `supertonic.exe` 를 직접 부르면서 `--host 127.0.0.1` 을 인자로
    박아 둔다. 스크립트를 아예 안 거친다.

    2026-09-06 실측: 본체의 :7788 이 여전히 `127.0.0.1` 에만 묶여 있었다. 나래님
    노트북의 자비스를 되살려도 **벙어리로 살아났을 것이다.**

    검사가 하나뿐이면 안 되는 이유가 이것이다 — 고친 자리에만 걸면, 안 고친
    자리는 계속 초록불 밑에서 산다.
    """
    body = _read("install_autostart.ps1")
    match = re.search(r"Alture-Jarvis-Supertonic.*?--host\s+(\S+)", body, re.S)

    assert match, "Supertonic 예약 작업 등록 줄을 못 찾았다"
    assert match.group(1) == "127.0.0.1", (
        f"공개 설치의 음성 합성 서비스가 로컬 장치 밖에 노출됐다: {match.group(1)}"
    )
