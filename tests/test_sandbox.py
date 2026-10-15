"""상자가 **정말로 상자인가.**

## 이 파일의 성격

`test_shell_probe.py` 와 같다 — "되는가"가 아니라 **"뚫리는가"** 를 본다.

## 왜 이 검사들이 존재하는가

2026-08-21 에 WSL 을 깔고 바로 재 봤더니 **기본값이 상자가 아니었다**:

    /mnt/c · /mnt/e · /mnt/f 전부 마운트   → 저장소와 .env 가 읽혔다
    자비스 control.token 이 실제로 읽혔다
    powershell.exe · cmd.exe 호출 가능      → ★
    /init 로 interop 직접 호출 가능

세 번째가 치명적이다. 상자 안에서 윈도우 인터프리터를 부를 수 있으면
`shell_probe` 의 "인터프리터는 영원히 안 들어온다"가 통째로 무의미해진다.
막아 놓은 문을, 상자를 연다면서 뒷문으로 열어 주는 꼴이다.

`/etc/wsl.conf` 로 막았고 다시 재서 확인했다. 여기 있는 검사들은 **그 설정이
되돌려졌을 때 알아채기 위한 것**이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.sandbox import SandboxBox, _clip, _wrap
from alture_jarvis.tool_gateway import RiskLevel


def _config(tmp_path: Path) -> JarvisConfig:
    config = JarvisConfig()
    config.sandbox_enabled = True
    config.sandbox_output_dir = tmp_path / "out"
    return config


def test_network_flag_raises_the_risk_level() -> None:
    """★ 등급이 갈리는 자리는 망이다.

    상자는 호스트를 못 건드리므로 계산은 되돌릴 것이 없다(L1). 망은 밖으로
    나가는 유일한 길이고, 나간 것은 되돌릴 수 없다(L2).

    ★ 2026-09-30 대표 결정으로 좁혔다(「상자는 어마무시하게 연다, 최소 헤르메스 수준」): 상자에는 드라이브도
      interop 도 없어 나갈 수 있는 것은 **넣어 준 파일뿐**이다. 파일 없이 켠 망은 L1, **넣은 파일 + 망**만 L2.
      패키지 설치(`packages`)는 파일을 넣기 전에 따로 돌아 등급을 올리지 않는다.
    """
    assert SandboxBox._run_risk({"code": "print(1)"}) is RiskLevel.L1
    assert SandboxBox._run_risk({"code": "print(1)", "allow_network": True}) is RiskLevel.L1
    assert SandboxBox._run_risk({"code": "print(1)", "packages": ["qrcode[pil]"]}) is RiskLevel.L1
    assert SandboxBox._run_risk({"code": "x", "allow_network": True, "files": ["C:/a.xlsx"]}) is RiskLevel.L2


def test_gateway_floor_cannot_be_lowered_by_arguments(tmp_path) -> None:
    """`dynamic_risk` 는 **올리기만** 한다. 인자로 등급을 내릴 수 없다.

    `_approved` 인자가 정확히 그렇게 뚫려 있었던 적이 있다 — 신뢰는 인자가
    아니라 등록에서 온다.
    """
    registered: dict[str, object] = {}

    class _Gateway:
        store = None

        def register(self, spec) -> None:  # noqa: ANN001
            registered[spec.name] = spec

    SandboxBox(_config(tmp_path)).register(_Gateway())

    spec = registered["sandbox_run"]
    assert spec.risk_level is RiskLevel.L1
    # 넣은 파일 + 망이면 올라가고(09-30 부터 망만으로는 안 올라간다),
    assert spec.effective_risk({"allow_network": True, "files": ["C:/a.xlsx"]}) is RiskLevel.L2
    # 아무 인자로도 바닥 아래로는 못 내려간다.
    assert spec.effective_risk({"allow_network": False, "_approved": True}) is RiskLevel.L1


def test_disabled_by_default() -> None:
    """★ 임의 코드를 돌리는 물건이 켜진 채로 태어나면 안 된다."""
    assert JarvisConfig().sandbox_enabled is False


def test_fetch_refuses_paths(tmp_path) -> None:
    """상자가 경로를 정하게 하면 격리가 의미를 잃는다. **이름만 받는다.**"""
    box = SandboxBox(_config(tmp_path))
    for bad in ("../etc/passwd", "a/b.txt", r"a\b.txt", ".."):
        result = box.fetch({"run_id": "abc123", "name": bad})
        assert result["ok"] is False, bad
    assert box.fetch({"run_id": "../x", "name": "a.txt"})["ok"] is False


def test_remote_script_is_base64_wrapped() -> None:
    """따옴표를 겹치지 않는다 — 사고 K 의 표준을 그대로 쓴다."""
    wrapped = _wrap("echo \"it's\" 'mixed'")
    assert "base64 -d" in wrapped
    # 원문의 따옴표가 명령줄에 그대로 나가지 않는다.
    assert "it's" not in wrapped


def test_output_is_clipped_by_line_and_says_how_many() -> None:
    """잘림은 침묵으로 오면 안 된다. 그리고 줄 중간에서 안 끊는다."""
    text = "\n".join(f"line {i}" for i in range(500))
    clipped, dropped = _clip(text, 100)

    assert dropped > 0
    assert clipped.endswith(clipped.splitlines()[-1])  # 반쪽 줄이 없다
    assert len(clipped) <= 100


def test_names_match_the_definitions(tmp_path) -> None:
    box = SandboxBox(_config(tmp_path))
    assert {item["function"]["name"] for item in box.ollama_tools} == box.names


def test_missing_wsl_is_reported_not_raised(tmp_path) -> None:
    """상자가 없어도 자비스는 떠야 한다 — 이 갈래만 없는 편이 낫다."""
    config = _config(tmp_path)
    config.sandbox_distro = "이런배포판은없다"
    result = SandboxBox(config).run({"code": "print(1)"})

    assert result["ok"] is False
    assert result["action"] == "sandbox_run"


def test_rejects_unknown_language(tmp_path) -> None:
    result = SandboxBox(_config(tmp_path)).run({"code": "x", "language": "perl"})

    assert result["ok"] is False
    assert "perl" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# 실기 — 상자가 실제로 있을 때만 돈다
# ═══════════════════════════════════════════════════════════════════════════


def _box_available() -> bool:
    import shutil
    import subprocess

    if not shutil.which("wsl.exe"):
        return False
    try:
        proc = subprocess.run(  # noqa: S603
            ["wsl.exe", "-d", "Ubuntu", "--user", "root", "--", "true"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


_live = pytest.mark.skipif(not _box_available(), reason="상자(WSL Ubuntu)가 없다")


@_live
def test_live_box_runs_python(tmp_path) -> None:
    result = SandboxBox(_config(tmp_path)).run({"code": "print(6*7)"})

    assert result["ok"] is True, result
    assert "42" in result["stdout"]
    assert result["exit_code"] == 0


@_live
def test_live_box_cannot_see_the_host(tmp_path) -> None:
    """★ 이 파일에서 가장 중요한 검사.

    `/etc/wsl.conf` 가 되돌려지면 여기서 걸린다. 실제로 뚫려 있던 넷을 전부 본다.
    """
    code = (
        "import os,shutil\n"
        "print('mnt', os.path.isdir('/mnt/c') or os.path.isdir('/mnt/e'))\n"
        "print('powershell', shutil.which('powershell.exe') is not None)\n"
        "print('cmd', shutil.which('cmd.exe') is not None)\n"
        "print('init', os.path.exists('/init') and os.access('/init', os.X_OK))\n"
    )
    result = SandboxBox(_config(tmp_path)).run({"code": code})

    assert result["ok"] is True, result
    assert "mnt False" in result["stdout"], "★ 윈도우 드라이브가 보인다 — wsl.conf 확인"
    assert "powershell False" in result["stdout"], "★ powershell.exe 를 부를 수 있다"
    assert "cmd False" in result["stdout"], "★ cmd.exe 를 부를 수 있다"


@_live
def test_live_box_has_no_network_by_default(tmp_path) -> None:
    """망은 기본으로 끊겨 있다. 켜려면 L2 승인을 받아야 한다."""
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1',53),timeout=4); print('REACHED')\n"
        "except Exception as e: print('BLOCKED', type(e).__name__)\n"
    )
    result = SandboxBox(_config(tmp_path)).run({"code": code})

    assert result["ok"] is True, result
    assert "BLOCKED" in result["stdout"], "★ 망이 안 끊겼다"


@_live
def test_live_box_makes_a_file_and_hands_it_over(tmp_path) -> None:
    """엑셀 하나를 실제로 만들어 호스트로 꺼내 온다 — 이게 상자를 판 이유다."""
    box = SandboxBox(_config(tmp_path))
    code = (
        "from openpyxl import Workbook\n"
        "wb = Workbook(); ws = wb.active; ws['A1']='이름'; ws['B1']='점수'\n"
        "ws.append(['나래', 92])\n"
        "wb.save('out/성적.xlsx'); print('saved')\n"
    )
    run = box.run({"code": code})
    assert run["ok"] is True, run
    assert [f["name"] for f in run["outputs"]] == ["성적.xlsx"]

    got = box.fetch({"run_id": run["run_id"], "name": "성적.xlsx"})
    assert got["ok"] is True, got
    assert Path(got["path"]).exists()
    assert got["bytes"] > 1000


@_live
def test_live_status_reads_isolation_every_time(tmp_path) -> None:
    """캐시된 플래그는 물어보는 순간 낡는다 — 매번 다시 읽는다."""
    status = SandboxBox(_config(tmp_path)).status()

    assert status["reachable"] is True
    assert status["windows_mounts"] == 0
    assert status["isolated"] is True


@_live
def test_live_korean_filenames_survive_the_boundary(tmp_path) -> None:
    """★ 한글 파일 이름이 경계를 건너 살아남는가.

    2026-08-21 실측: `find -printf '%p'` 로 날것을 받았더니 `성적표.csv` 가
    `'\udcec…\udced….csv'` 로 돌아왔다. 그러면 그 이름으로는 파일을 못 찾는다 —
    **만들어 놓고 못 꺼낸다.** WSL 쪽 출력은 멀쩡했으므로 상자가 아니라
    경계를 건너는 방식을 고칠 일이었다(base64).
    """
    box = SandboxBox(_config(tmp_path))
    code = (
        "rows = ['이름,점수', '나래,92']" + "\n"
        "open('out/성적표 (최종).csv','w',encoding='utf-8-sig')"
        ".write(chr(10).join(rows))" + "\n"
    )

    run = box.run({"code": code})

    assert run["ok"] is True, run
    assert [f["name"] for f in run["outputs"]] == ["성적표 (최종).csv"]


@_live
def test_live_files_come_out_without_being_asked(tmp_path) -> None:
    """★ 만든 파일은 자동으로 나온다.

    처음엔 `sandbox_fetch` 를 따로 부르게 두고 도구 설명에 적어 뒀다. 라이브에서
    자비스는 파일을 만들고 **fetch 를 안 불렀다.** 그러고는 "파일 생성이
    완료되었습니다"라고 답했다 — 파일은 상자 안에만 있었다.

    안내문은 안 먹는다. 결정론으로 박을 수 있으면 코드로.
    """
    box = SandboxBox(_config(tmp_path))
    code = (
        "from openpyxl import Workbook\n"
        "wb=Workbook(); ws=wb.active; ws.append(['이름','점수']); ws.append(['나래',92])\n"
        "wb.save('out/성적표.xlsx')\n"
    )
    run = box.run({"code": code})

    assert run["ok"] is True, run
    # 부르지 않았는데 이미 나와 있다.
    assert len(run["saved_to"]) == 1
    saved = Path(run["saved_to"][0]["path"])
    assert saved.exists() and saved.stat().st_size > 1000


@_live
def test_live_file_written_to_work_root_is_salvaged_and_handed_over(tmp_path) -> None:
    """모델이 ``out/``을 빼도 성공한 판의 새 파일은 잃어버리지 않는다."""
    box = SandboxBox(_config(tmp_path))

    run = box.run({"code": "open('root-result.txt','w').write('closed loop')"})

    assert run["ok"] is True, run
    assert [item["name"] for item in run["outputs"]] == ["root-result.txt"]
    assert len(run["saved_to"]) == 1
    saved = Path(run["saved_to"][0]["path"])
    assert saved.read_text(encoding="utf-8") == "closed loop"


@_live
def test_live_failed_run_hands_over_nothing(tmp_path) -> None:
    """실패한 판은 아무것도 안 꺼낸다 — 반쪽 결과를 손에 쥐여 주지 않는다."""
    box = SandboxBox(_config(tmp_path))

    run = box.run({"code": "open('out/half.txt','w').write('x')\nraise SystemExit(2)"})

    assert run["ok"] is False
    assert run["saved_to"] == []


def test_packages_are_installed_as_the_box_user_wheels_only(tmp_path, monkeypatch) -> None:
    """★ 2026-09-30: 설치는 jarvisbox(sudo 없음)로, 휠만. root 로 설치 스크립트를 돌리면 악성 패키지가
    `/etc/wsl.conf` 를 고쳐 드라이브 마운트를 다시 켤 수 있다 — 상자가 상자가 아니게 된다."""
    box = SandboxBox(_config(tmp_path))
    seen: list[str] = []
    monkeypatch.setattr(box, "_exec", lambda script, timeout: (seen.append(script), (0, "Successfully installed qrcode", ""))[1])

    got = box._install_packages(["qrcode[pil]"])

    assert got["ok"] and "sudo -u jarvisbox" in seen[0] and "--only-binary=:all:" in seen[0]
    assert "'qrcode[pil]'" in seen[0]  # 셸 인용


def test_package_names_are_checked_before_the_shell(tmp_path, monkeypatch) -> None:
    box = SandboxBox(_config(tmp_path))
    monkeypatch.setattr(box, "_exec", lambda *a, **k: (_ for _ in ()).throw(AssertionError("셸까지 가면 안 된다")))

    assert box._install_packages(["qrcode; rm -rf /"])["ok"] is False
    assert box._install_packages([f"p{i}" for i in range(9)])["ok"] is False


def test_a_missing_module_tells_the_model_to_ask_for_the_package(tmp_path, monkeypatch) -> None:
    """★ QR 실측: 없는 모듈에 모델이 포기하고 11걸음 헤맸다. 결과에 다음 걸음을 박는다(헤르메스 방식)."""
    box = SandboxBox(_config(tmp_path))
    monkeypatch.setattr(box, "_exec", lambda script, timeout: (1, "", "ModuleNotFoundError: No module named 'PIL'"))
    monkeypatch.setattr(box, "_list_outputs", lambda work: [])

    got = box.run({"code": "import PIL"})

    assert got["ok"] is False and 'packages=["pillow"]' in got["next"]


def test_the_tool_no_longer_says_nothing_else_can_be_installed(tmp_path) -> None:
    """도구 설명이 「다른 것은 설치돼 있지 않다 · 인터넷도 끊겨 있다」여서 모델이 포기했다."""
    tool = next(t for t in SandboxBox(_config(tmp_path)).ollama_tools if t["function"]["name"] == "sandbox_run")
    text = tool["function"]["description"]

    assert "packages" in text and "설치돼 있지 않다" not in text
    assert "packages" in tool["function"]["parameters"]["properties"]


def test_a_missing_module_is_installed_by_the_tool_and_run_again(tmp_path, monkeypatch) -> None:
    """★ 2026-09-30 대표: 「패키지 설치는 우선적으로 — 헤르메스는 그렇게 하더라」. 안내 한 줄은 모델이 안 따를 수 있다.
    없는 모듈은 오류에 이름이 박혀 오는 구조적 사실이라 도구가 깔고 같은 코드를 한 번 다시 돌린다."""
    box = SandboxBox(_config(tmp_path))
    calls: list[str] = []

    def fake(script, timeout):
        calls.append("install" if "pip" in script else "run")
        if "pip" in script:
            return 0, "Successfully installed pillow", ""
        if calls.count("run") == 1:
            return 1, "", "ModuleNotFoundError: No module named 'PIL'"
        return 0, "done", ""

    monkeypatch.setattr(box, "_exec", fake)
    monkeypatch.setattr(box, "_list_outputs", lambda work: [])

    got = box.run({"code": "import PIL"})

    assert calls == ["run", "install", "run"]
    assert got["ok"] is True and got["auto_installed"] == ["pillow"]


def test_the_tool_installs_only_once_per_run(tmp_path, monkeypatch) -> None:
    """깔았는데도 같은 모듈이 없다고 하면(이름이 다른 패키지 등) 되풀이하지 않고 안내로 끝낸다 — 무한 고리 금지."""
    box = SandboxBox(_config(tmp_path))
    calls: list[str] = []

    def fake(script, timeout):
        calls.append("install" if "pip" in script else "run")
        if "pip" in script:
            return 0, "Successfully installed pillow", ""
        return 1, "", "ModuleNotFoundError: No module named 'PIL'"

    monkeypatch.setattr(box, "_exec", fake)
    monkeypatch.setattr(box, "_list_outputs", lambda work: [])

    got = box.run({"code": "import PIL"})

    assert calls == ["run", "install", "run"]
    assert got["ok"] is False and "next" in got


def test_a_too_long_command_is_not_called_a_missing_wsl(tmp_path, monkeypatch) -> None:
    """★ 13.4MB 글꼴을 넣자 명령줄이 한도를 넘어 WinError 206 — 우리는 「wsl.exe 가 없다」로 옮겨 적었고 모델은 상자를 버렸다."""
    import subprocess as sp

    from alture_jarvis.sandbox import SandboxError

    box = SandboxBox(_config(tmp_path))
    error = FileNotFoundError(2, "The filename or extension is too long")
    error.winerror = 206
    monkeypatch.setattr(sp, "run", lambda *a, **k: (_ for _ in ()).throw(error))

    try:
        box._exec("echo hi", timeout=5)
    except SandboxError as exc:
        assert "wsl.exe" not in str(exc) and "너무 길다" in str(exc)
    else:
        raise AssertionError("SandboxError expected")


def test_the_script_goes_through_stdin_not_the_command_line(tmp_path, monkeypatch) -> None:
    import subprocess as sp

    box = SandboxBox(_config(tmp_path))
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["input"] = cmd, kwargs.get("input")
        return sp.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(sp, "run", fake_run)
    big = "echo " + "A" * 100_000

    box._exec(big, timeout=5)

    assert seen["input"] == big.encode("utf-8")
    assert sum(len(part) for part in seen["cmd"]) < 500 and "--exec" in seen["cmd"]
