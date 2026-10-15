"""위성 갱신 — 무엇을 보내고, 무엇을 **절대 안 보내는가** (2026-08-24).

## 이 검사가 지키는 것

가장 무서운 실수는 갱신이 안 되는 게 아니라 **남의 것이 실려 가는 것**이다:

    data/          나래님 노트북의 대화가 본체 것으로 덮인다
    .env           본체의 토큰·API 키가 통째로 간다
    browser-profile 본체의 로그인 쿠키가 간다

셋 다 조용히 일어나고, 셋 다 되돌릴 수 없다. 그래서 「보낼 것」 목록과
「안 보낼 것」 목록을 **둘 다** 두고, 여기서 양쪽을 다 시험한다.

## 그리고 결정론

zip 이 만들 때마다 다른 해시를 내면 위성은 「받을 게 있다」를 영원히 참으로
본다. 압축 시각을 고정한 이유이고, 그게 진짜 그런지는 재 봐야 안다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from alture_jarvis import updater


@pytest.fixture()
def fake_install(tmp_path: Path) -> Path:
    """위성 설치본을 흉내 낸다. 보낼 것과 안 보낼 것을 섞어 둔다."""
    root = tmp_path / "alture-jarvis"
    (root / "src" / "alture_jarvis").mkdir(parents=True)
    (root / "src" / "alture_jarvis" / "agent.py").write_text("A = 1\n", encoding="utf-8")
    (root / "src" / "alture_jarvis" / "runtime.py").write_text("B = 2\n", encoding="utf-8")
    (root / "recipes").mkdir()
    (root / "recipes" / "saramin.json").write_text("{}", encoding="utf-8")
    (root / "ui").mkdir()
    (root / "ui" / "alture-jarvis-hud.exe").write_bytes(b"MZ fake")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    # ── 절대 안 나가야 하는 것들 ──
    (root / "data").mkdir()
    (root / "data" / "jarvis.db").write_bytes(b"secret conversations")
    (root / "data" / "control.token").write_text("SECRET", encoding="utf-8")
    (root / "data" / "browser-profile").mkdir()
    (root / "data" / "browser-profile" / "Cookies").write_bytes(b"login")
    (root / ".env").write_text("JARVIS_CONTROL_TOKEN=SECRET\n", encoding="utf-8")
    (root / "outputs").mkdir()
    (root / "outputs" / "report.pdf").write_bytes(b"pdf")
    (root / "src" / "alture_jarvis" / "__pycache__").mkdir()
    (root / "src" / "alture_jarvis" / "__pycache__" / "agent.pyc").write_bytes(b"pyc")
    (root / "ui" / "alture-jarvis-hud.exe.bak-20260819").write_bytes(b"old exe")
    return root


def test_it_sends_the_things_a_satellite_needs(fake_install: Path) -> None:
    names = {rel for rel, _path in updater.payload_files(fake_install)}
    assert "src/alture_jarvis/agent.py" in names
    assert "src/alture_jarvis/runtime.py" in names
    assert "recipes/saramin.json" in names
    assert "ui/alture-jarvis-hud.exe" in names
    assert "pyproject.toml" in names


@pytest.mark.parametrize(
    "forbidden",
    [
        "data/jarvis.db",            # 나래님 대화가 덮인다
        "data/control.token",        # 본체 토큰
        "data/browser-profile/Cookies",  # 본체 로그인 쿠키
        ".env",                      # 토큰·API 키 전부
        "outputs/report.pdf",        # 남의 산출물
        "src/alture_jarvis/__pycache__/agent.pyc",
        "ui/alture-jarvis-hud.exe.bak-20260819",
    ],
)
def test_it_never_sends_someone_elses_things(fake_install: Path, forbidden: str) -> None:
    """★ 이 검사가 빨개지면 **배포하지 마라.** 되돌릴 수 없는 종류의 사고다."""
    names = {rel for rel, _path in updater.payload_files(fake_install)}
    assert forbidden not in names, f"보내면 안 되는 것이 실렸다: {forbidden}"


def test_the_zip_is_the_same_every_time(fake_install: Path, tmp_path: Path) -> None:
    """같은 내용이면 같은 해시. 아니면 위성이 영원히 「받을 게 있다」로 본다."""
    one = updater.write_payload(fake_install, tmp_path / "a.zip")
    two = updater.write_payload(fake_install, tmp_path / "b.zip")
    assert one["sha256"] == two["sha256"]
    assert one["file_count"] == two["file_count"]


def test_changing_a_file_changes_the_hash(fake_install: Path, tmp_path: Path) -> None:
    before = updater.write_payload(fake_install, tmp_path / "a.zip")["sha256"]
    (fake_install / "src" / "alture_jarvis" / "agent.py").write_text("A = 99\n", encoding="utf-8")
    after = updater.write_payload(fake_install, tmp_path / "b.zip")["sha256"]
    assert before != after


def test_not_knowing_is_not_the_same_as_being_up_to_date() -> None:
    """빈 값이 「같다」와 「모른다」 둘 다를 뜻하면 조용히 고장 난다."""
    assert updater.needs_update("aaa", "bbb")
    assert not updater.needs_update("aaa", "aaa")
    assert not updater.needs_update("", "bbb"), "내 판을 모르는데 받으면 안 된다"
    assert not updater.needs_update("aaa", ""), "본체 판을 모르는데 받으면 안 된다"


def test_a_broken_download_is_refused(fake_install: Path, tmp_path: Path) -> None:
    made = updater.write_payload(fake_install, tmp_path / "p.zip")
    path = Path(made["path"])
    ok, why = updater.verify_download(path, made["sha256"])
    assert ok and not why

    ok, why = updater.verify_download(path, "0" * 64)
    assert not ok and "해시가 다릅니다" in why

    ok, why = updater.verify_download(path, "")
    assert not ok, "해시 없이 갈아치우면 안 된다"

    ok, why = updater.verify_download(tmp_path / "없는파일.zip", made["sha256"])
    assert not ok


def test_a_zip_cannot_escape_the_staging_folder(tmp_path: Path) -> None:
    """본체를 믿더라도 푸는 코드는 안 믿는다. 값이 싼 방어다."""
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as bundle:
        bundle.writestr("../../gotcha.txt", "pwned")
    with pytest.raises(ValueError, match="staging 밖"):
        updater.unpack(evil, tmp_path / "staged")


def test_the_staged_build_is_read_the_same_way_as_the_running_one(fake_install: Path, tmp_path: Path) -> None:
    """규칙이 갈리면 늘 「다르다」가 되고, 그러면 되돌리기가 매번 돈다."""
    made = updater.write_payload(fake_install, tmp_path / "p.zip")
    staging = tmp_path / "staged"
    updater.unpack(Path(made["path"]), staging)

    import hashlib
    expect = hashlib.sha256()
    package = fake_install / "src" / "alture_jarvis"
    for path in sorted(package.glob("*.py")):
        expect.update(path.name.encode())
        expect.update(path.read_bytes())
    assert updater.staged_build(staging) == expect.hexdigest()[:12]


def test_the_plan_tells_the_script_everything_it_needs(fake_install: Path, tmp_path: Path) -> None:
    """두 곳이 판단하면 갈린다. 스크립트는 시키는 것만 해야 한다."""
    data = updater.plan(fake_install, tmp_path / "staged", "abc123")
    for key in ("root", "staging", "expected_build", "dirs", "files", "hud", "health_url"):
        assert key in data, key
    assert data["expected_build"] == "abc123"


def test_the_swap_script_exists_and_carries_a_bom() -> None:
    """한글이 하드코딩된 .ps1 은 BOM 이 없으면 PowerShell 5.1 이 깨뜨린다(사고 J).

    깨지면 「Missing local DB」 같은 엉뚱한 에러로 나타나 진단이 오래 걸린다.
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "apply_update.ps1"
    assert script.is_file(), "교체 스크립트가 없으면 갱신은 시작조차 못 한다"
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf", "UTF-8 BOM 이 없다"


def test_the_script_leaves_the_voice_server_alone() -> None:
    """TTS 서버도 python.exe 이고 명령줄에 alture-jarvis 가 있다.

    안 빼면 갱신할 때마다 음성이 죽고, **아무 데도 안 찍힌다.**
    이 저장소는 그렇게 다섯 번 죽였다.
    """
    script = (Path(__file__).resolve().parents[1] / "scripts" / "apply_update.ps1")
    assert "supertonic" in script.read_text(encoding="utf-8-sig")


def test_the_bootstrap_script_exists_with_a_bom() -> None:
    """이미 깔린 위성(나래님 노트북)에는 갱신 코드가 **없다.**

    스스로 갱신하려면 갱신하는 코드가 먼저 거기 있어야 하는데 없다 — 닭과 달걀이다.
    `bootstrap_update.ps1` 이 그 한 번을 처리한다. 이게 없으면 그 노트북은
    영원히 손으로 재설치해야 한다.
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_update.ps1"
    assert script.is_file()
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf", "한글 .ps1 은 BOM 이 필요하다(사고 J)"


def test_the_two_languages_read_the_build_the_same_way() -> None:
    """★ PowerShell 과 파이썬이 판 지문을 **각자** 센다.

    두 벌이 갈리면 bootstrap 이 **항상** "받은 것의 판이 다릅니다"로 끝난다.
    실측으로 한 번 맞춰 봤지만(2026-08-24, 둘 다 c6ab640ee736), 사람이 한쪽만
    고치면 조용히 갈라진다. 그래서 규칙을 글자로 대조해 둔다.

    (진짜로 돌려서 비교하려면 PowerShell 을 띄워야 하는데, 그건 검사가 느려지고
     CI 에서 못 돈다. 여기서는 **같은 규칙을 쓰고 있다는 것**을 지킨다.)
    """
    script = (Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_update.ps1").read_text(
        encoding="utf-8-sig"
    )
    # 파이썬 쪽 규칙: 이름(UTF-8) + 내용, `*.py` 를 이름순, sha256 앞 12자
    assert "Filter *.py" in script, "확장자 규칙이 갈렸다"
    assert "Sort-Object Name" in script, "정렬 규칙이 갈렸다 — 순서가 다르면 해시가 다르다"
    assert "UTF8.GetBytes($f.Name)" in script, "이름을 같이 해시하는 규칙이 빠졌다"
    assert "Substring(0, 12)" in script, "자르는 길이가 갈렸다"
    assert "SHA256" in script


def test_the_bootstrap_hands_the_swap_to_the_one_script_that_can_roll_back() -> None:
    """두 벌이 되면 반드시 갈린다. 되돌리기는 `apply_update.ps1` 에만 있다."""
    script = (Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_update.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "apply_update.ps1" in script, "bootstrap 이 스스로 교체하면 되돌리기가 없다"

# ── 2026-08-24, 위성 첫 실전에서 난 것 ───────────────────────────────────────
#
# 나래님 노트북의 첫 갱신이 이렇게 끝났다: 파일은 새 판으로 바뀌었고, 자비스는
# **꺼진 채로** 남았고, 화면엔 "되돌렸습니다"가 찍혔는데 **되돌린 적이 없었다.**
# 아래 넷이 그 넷을 각각 잡는다.

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _ps(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8-sig")


def _code_lines(text: str) -> list[str]:
    """주석과 문서 블록을 뺀 줄만. 주석 속 예시를 고장으로 세지 않기 위해."""
    out, in_doc = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<#"):
            in_doc = True
        if in_doc:
            if "#>" in stripped:
                in_doc = False
            continue
        if stripped.startswith("#"):
            continue
        out.append(line)
    return out


def test_no_native_command_is_merged_with_2to1_outside_the_guard() -> None:
    """★ PowerShell 5.1 은 `exe ... 2>&1` 의 stderr 한 줄을 NativeCommandError 로
    감싸고, `$ErrorActionPreference = "Stop"` 아래서 그것은 **터미네이팅**이다.
    종료코드가 0 이어도 죽는다.

    이 한 줄이 갱신 5단계에서 스크립트를 죽여 6단계(확인)와 7단계(되돌림)가
    통째로 안 돌았다. 그래서 이 저장소의 위성 경로에서는 네이티브 명령의
    stderr 를 **`Invoke-Native` 안에서만** 합친다(거기서만 잠깐 Continue 로 낮춘다).

    실측(2026-08-24): 없는 작업에 `schtasks /Run ... 2>&1 | Out-Null` →
    RemoteException 으로 죽음. 같은 호출을 `Invoke-Native` 로 → 코드 1 로 살아남음.
    """
    text = _ps("apply_update.ps1")
    offenders = [
        line.strip()
        for line in _code_lines(text)
        if "2>&1" in line and "$Exe @Arguments" not in line
    ]
    assert not offenders, f"보호 없이 stderr 를 합치는 줄이 있다: {offenders}"

    # 그리고 그 유일한 자리는 반드시 낮춰 놓고 써야 한다.
    guard = text[text.find("function Invoke-Native") :][:600]
    assert '$ErrorActionPreference = "Continue"' in guard, "Invoke-Native 가 안 낮추면 의미가 없다"
    assert "finally" in guard, "되돌려 놓지 않으면 그 뒤 전체가 Continue 로 돈다"


def test_it_can_start_jarvis_without_the_task_scheduler() -> None:
    """★ 예약 작업이 **없는 PC 가 실재한다.**

    나래님 노트북은 회사 정책으로 schtasks 가 막혀 설치 때 작업이 안 만들어졌다.
    스케줄러만 부르면 이 스크립트는 "명령을 넣었습니다"라고 찍고 아무 일도 안
    일어나고, 6단계가 실패해 되돌리는데, 되돌린 뒤에도 못 올려 **꺼진 채로** 끝난다.
    """
    text = _ps("apply_update.ps1")
    assert "Test-Task" in text, "작업이 있는지 보지도 않고 부르면 없는 PC 에서 조용히 실패한다"
    assert "pythonw.exe" in text, "직접 띄우는 길이 없다"
    assert "task_entry.py" in text, "무엇을 띄울지가 없다"


def test_any_failure_after_the_swap_reaches_the_rollback() -> None:
    """전에는 `try` 가 없어서 5단계에서 죽으면 6·7 이 통째로 안 돌았다.

    그 결과가 「새 파일 + 꺼진 자비스 + 되돌렸다는 거짓말」이다.
    """
    text = _ps("apply_update.ps1")
    swap = text.find("# ── 3. 바꾼다")
    rollback = text.find("# ── 7. 되돌린다")
    assert swap != -1 and rollback != -1
    body = text[swap:rollback]
    # ★ 인라인 (확인 고리 안의 것) 로는 안 된다. 그건 옛
    #   코드에도 있었고, 그래서 이 검사가 처음엔 **헛통과**했다. 덩어리를 감싸는
    #   catch 는 자기 줄에 혼자 선다.
    assert any(line.strip() == "} catch {" for line in body.splitlines()), (
        "교체~확인 전체를 감싸는 catch 가 없다 — 5단계에서 죽으면 되돌림에 못 간다"
    )
    assert "$applied" in body, "무엇을 되돌릴지(이미 바꿨는지)를 안 들고 간다"


def test_the_outcome_is_recorded_not_guessed() -> None:
    """★ 이 저장소에서 제일 나쁜 종류의 거짓: 하지 않은 일을 했다고 말하는 것.

    부르는 쪽이 종료코드만 보고 "되돌렸습니다"를 찍었고, 그때 되돌리기는 한 번도
    돈 적이 없었다. 이제 교체 스크립트가 `result.json` 에 적고 부르는 쪽은 읽는다.
    시작할 때 `started` 로 적어 두므로, 중간에 죽으면 「모른다」고 말할 수 있다.
    """
    swap = _ps("apply_update.ps1")
    assert "result.json" in swap
    for state in ("started", "success", "rolled_back", "half_applied", "stopped_no_change"):
        assert f'"{state}"' in swap, f"결과 '{state}' 를 적는 자리가 없다"

    # 주석은 뺀다 — 왜 이렇게 됐는지를 적은 글이 고장으로 세지 않게.
    boot = chr(10).join(_code_lines(_ps("bootstrap_update.ps1")))
    assert "result.json" in boot, "부르는 쪽이 여전히 짐작한다"
    said = boot.find("되돌렸")
    assert said != -1, "되돌렸을 때 그렇게 말하는 자리가 아예 없다"
    # 「되돌렸다」는 말은 result 를 읽은 **뒤**에만 나올 수 있어야 한다.
    assert boot.find("$result = ") < said, "결과를 읽기 전에 되돌렸다고 말한다"


def test_the_installer_fallback_is_actually_reachable() -> None:
    """schtasks 가 막힌 PC 를 위해 쓴 시작프로그램 폴백이 **그 PC 에서만** 안 돌았다.

    `2>&1` 이 `$LASTEXITCODE` 를 볼 기회조차 주지 않고 스크립트를 죽였기 때문이다.
    폴백은 안 도는 동안에도 코드에 있었고, 그래서 아무도 몰랐다.
    """
    text = _ps("install_satellite.ps1")
    assert "Startup" in text, "폴백 자체가 없다"
    head = text[: text.find("schtasks /Create")]
    assert '$ErrorActionPreference = "Continue"' in head[-800:], (
        "schtasks 를 부르기 전에 낮추지 않으면 폴백에 닿지 못한다"
    )

def test_a_script_only_fix_still_counts_as_an_update(fake_install) -> None:
    """★ 2026-08-24 에 이것 때문에 고친 것이 위성에 안 닿을 뻔했다.

    `build_id()` 는 `src/alture_jarvis/*.py` 만 센다. 그 값으로 「받을 게 있나」를
    물으면, `.ps1` 만 고친 날 위성은 **「이미 같은 판입니다」**라고 답한다.
    하필 그날 고친 것이 교체 스크립트의 치명적인 버그였다 — 그 버그를 고쳤는데
    그 버그 때문에 고친 것이 안 가는 모양이 될 뻔했다.

    화면(exe)만 바꾼 날도 똑같다.
    """
    (fake_install / "scripts").mkdir(exist_ok=True)
    script = fake_install / "scripts" / "apply_update.ps1"
    script.write_text("Write-Host 'v1'\n", encoding="utf-8")
    before = updater.payload_id(fake_install)

    script.write_text("Write-Host 'v2 - 버그 고침'\n", encoding="utf-8")
    after = updater.payload_id(fake_install)
    assert before != after, "스크립트를 고쳤는데 지문이 그대로다 — 위성은 영원히 못 받는다"

    exe = fake_install / "ui" / "alture-jarvis-hud.exe"
    exe.write_bytes(b"MZ fake but newer")
    assert updater.payload_id(fake_install) != after, "화면을 바꿔도 지문이 그대로다"


def test_the_payload_id_is_the_same_when_nothing_changed(fake_install: Path) -> None:
    """매번 달라지면 「받을 게 있다」가 영원히 참이 되어 사람이 무시하는 법을 배운다."""
    assert updater.payload_id(fake_install) == updater.payload_id(fake_install)


def test_the_manifest_carries_the_payload_id(fake_install: Path) -> None:
    """본체가 안 보내면 위성은 옛 규칙(build)으로 떨어진다 — 그건 구멍이 열린 상태다."""
    assert updater.manifest(fake_install).get("payload_id")


def test_the_satellite_runs_the_script_it_just_received() -> None:
    """★ 설치본 것을 쓰면 위성은 언제나 **한 판 낡은** 교체 스크립트로 갈아친다.

    그래서 교체 스크립트의 버그는 자기 자신을 영원히 못 고친다.
    `bootstrap_update.ps1` 은 처음부터 「받은 것 안의 스크립트」였고, 여기만 달랐다.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py").read_text(
        encoding="utf-8"
    )
    where = source.find('"scripts" / "apply_update.ps1"')
    assert where != -1
    head = source[:where]
    assert head.rstrip().endswith("script = staging /"), (
        "받은 것(staging)이 아니라 설치본 것을 먼저 본다"
    )


def test_check_and_apply_ask_the_same_question() -> None:
    """규칙이 갈리면 화면엔 「받을 게 있다」가 뜨는데 누르면 「이미 같은 판」이 나온다.

    사람은 버튼이 고장 났다고 생각하고, 그건 고칠 수 없는 종류의 불신이다.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py").read_text(
        encoding="utf-8"
    )
    check = source[source.find("def update_check") : source.find("def update_apply")]
    apply = source[source.find("def update_apply") :][:4000]
    for body, name in ((check, "update_check"), (apply, "update_apply")):
        assert "payload_id" in body, f"{name} 이 payload_id 를 안 본다"
