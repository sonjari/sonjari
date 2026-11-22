"""맥 자동 업데이트 — 가짜는 안 깔리고, 옛 판으로 안 돌아가고, 윈도우는 그대로 (2026-11-16).

설계 `docs/설계_맥업데이트_2026-11-16.ko.md`. 이 파일이 지키는 것:

    §6 위협 1·2  가짜 서명 · 바뀐 목록 · 바뀐 묶음 → 아무것도 안 바뀐다(교체 스크립트가 안 불린다)
    §6 위협 3    옛 진짜 목록 되먹임(seq 내려감) → 거절
    §5           파이썬 ↔ 앱 판 꼬임 → 갈아치우지 않고 까닭을 말한다
    §7           순서: 서명 → seq → sha256 → 풀기 → 푼 판 == 목록 판 → 교체 스크립트(받은 묶음 안의 것)
    윈도우       update_check · update_apply · /health 가 맥 갈래를 안 탄다
    교체 스크립트  실제 sh 로 돌려 성공 · 되돌림 둘 다(가짜 plutil · curl · launchctl)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

from alture_jarvis import mac_update, runtime, update_sign, updater

_minisign = pytest.importorskip("_minisign")
ROOT = Path(__file__).resolve().parents[1]


# ── 목록 만들기 도우미 ─────────────────────────────────────────────────────────────────────


def _manifest(seq: int = 202611161530, **python: object) -> dict:
    body = {"build": "newbuild0001", "payload_id": "p", "url": "python.zip", "sha256": "a" * 64, "bytes": 10,
            "min_app_version": "0.4.0"}
    body.update(python)
    return {"schema": 1, "channel": "mac-stable", "seq": seq, "issued_at": 1, "python": body}


def _signed(key, manifest: dict) -> tuple[bytes, str]:
    raw = json.dumps(manifest).encode()
    return raw, key.sign(raw)


# ── 서명 · 모양 ────────────────────────────────────────────────────────────────────────────


def test_a_signed_manifest_is_accepted() -> None:
    key = _minisign.SigningKey.new()
    raw, sig = _signed(key, _manifest())
    manifest, verified = mac_update.verify_manifest(raw, sig, key.pub_text())
    assert manifest["seq"] == 202611161530 and verified.key_id_hex


def test_a_manifest_signed_by_someone_else_is_refused() -> None:
    ours, attacker = _minisign.SigningKey.new(), _minisign.SigningKey.new()
    raw, sig = _signed(attacker, _manifest())
    with pytest.raises(mac_update.UpdateRefused, match="서명"):
        mac_update.verify_manifest(raw, sig, ours.pub_text())


def test_a_changed_manifest_is_refused() -> None:
    """배포처가 털려 sha256 만 바꿔치기 — 서명이 목록 전체를 덮으니 한 글자도 못 바꾼다."""
    key = _minisign.SigningKey.new()
    raw, sig = _signed(key, _manifest())
    forged = raw.replace(b"a" * 64, b"b" * 64)
    with pytest.raises(mac_update.UpdateRefused, match="서명"):
        mac_update.verify_manifest(forged, sig, key.pub_text())


@pytest.mark.parametrize("change,match", [
    ({"schema": 2}, "형식"), ({"channel": "beta"}, "채널"), ({"seq": 0}, "seq"), ({"seq": "1"}, "seq"),
])
def test_a_signed_but_wrong_shape_is_refused(change: dict, match: str) -> None:
    key = _minisign.SigningKey.new()
    raw, sig = _signed(key, {**_manifest(), **change})
    with pytest.raises(mac_update.UpdateRefused, match=match):
        mac_update.verify_manifest(raw, sig, key.pub_text())


def test_no_key_means_no_update() -> None:
    raw, sig = _signed(_minisign.SigningKey.new(), _manifest())
    with pytest.raises(mac_update.UpdateRefused):
        mac_update.verify_manifest(raw, sig, "")


def test_an_oversized_manifest_is_refused_before_verification() -> None:
    with pytest.raises(mac_update.UpdateRefused, match="너무 큽니다"):
        mac_update.verify_manifest(b"x" * (mac_update.MAX_MANIFEST_BYTES + 1), "", "")


# ── 되먹임(seq) ────────────────────────────────────────────────────────────────────────────


def _eval(manifest: dict, *, mine_build: str = "oldbuild0001", mine_seq: int = 0, seen_seq: int = 0,
          app_version: str = "0.4.0", app_enabled: bool = True) -> dict:
    return mac_update.evaluate(manifest, mine_build=mine_build, mine_seq=mine_seq, seen_seq=seen_seq,
                               app_version=app_version, app_enabled=app_enabled)


@pytest.mark.parametrize("mine_seq,seen_seq", [(202611170000, 0), (0, 202611170000), (5, 202611170000)])
def test_an_older_manifest_is_refused(mine_seq: int, seen_seq: int) -> None:
    """위협 3: 알려진 버그가 있는 옛 진짜 판의 목록(서명은 진짜)을 다시 준다."""
    with pytest.raises(mac_update.UpdateRefused, match="옛 목록"):
        _eval(_manifest(seq=202611161530), mine_seq=mine_seq, seen_seq=seen_seq)


def test_the_same_seq_is_the_same_manifest_not_a_downgrade() -> None:
    out = _eval(_manifest(seq=202611161530), mine_seq=202611161530, seen_seq=202611161530)
    assert out["seq"] == 202611161530


def test_the_seen_seq_never_goes_down(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    mac_update.write_seen(path, 10)
    mac_update.write_seen(path, 3)
    assert mac_update.read_seen(path) == 10
    mac_update.write_seen(path, 11)
    assert mac_update.read_seen(path) == 11


def test_a_broken_seen_file_reads_as_zero_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    assert mac_update.read_seen(path) == 0


# ── 받을 것 · 판 꼬임 ─────────────────────────────────────────────────────────────────────


def test_a_new_build_is_available_and_ready() -> None:
    out = _eval(_manifest())
    assert out["available"] and out["python"]["available"] and out["python"]["ready"]


def test_the_same_build_is_not_available() -> None:
    out = _eval(_manifest(), mine_build="newbuild0001")
    assert not out["python"]["available"] and "같은 판" in out["python"]["reason"]


def test_not_knowing_my_build_is_not_an_update() -> None:
    assert not _eval(_manifest(), mine_build="")["python"]["available"]


def test_no_sha256_is_never_ready() -> None:
    out = _eval(_manifest(sha256=""))
    assert out["python"]["available"] and not out["python"]["ready"]


@pytest.mark.parametrize("have", ["0.3.9", "", "모름"])
def test_python_waits_for_a_newer_app(have: str) -> None:
    out = _eval(_manifest(min_app_version="0.4.0"), app_version=have)
    assert out["python"]["available"] and not out["python"]["ready"]
    assert "화면 앱을 먼저" in out["python"]["reason"]


def test_python_goes_when_the_app_is_new_enough() -> None:
    assert _eval(_manifest(min_app_version="0.4.0"), app_version="0.4.10")["python"]["ready"]


def _with_app(version: str = "0.4.1", min_python_seq: int = 0, **extra: object) -> dict:
    m = _manifest()
    m["app"] = {"version": version, "latest_json": "latest.json", "signature": "SIG", "min_python_seq": min_python_seq,
                **extra}
    return m


def test_a_newer_app_is_ready() -> None:
    out = _eval(_with_app("0.4.1"), app_version="0.4.0")
    assert out["app"]["available"] and out["app"]["ready"] and out["app"]["signature"] == "SIG"


def test_the_app_road_is_off_by_default() -> None:
    """대표 결정(11-16): 앱 꾸러미 갈래는 Developer ID 서명 · 공증 뒤에 켠다 — 그전엔 있다는 것만 알리고 안 받는다."""
    out = mac_update.evaluate(_with_app("0.4.1"), mine_build="oldbuild0001", mine_seq=0, seen_seq=0, app_version="0.4.0")
    assert out["app"]["available"] and not out["app"]["ready"] and "공증 뒤" in out["app"]["reason"]
    # 11-22: 설정 기본값은 켬으로 바뀌었다(공증 dmg 공개 · 설계_맥앱안업데이트). evaluate 의 기본 인자는 여전히 꺼짐 —
    # 설정을 거치지 않고 부르는 자리가 실수로 받지 않게.
    from alture_jarvis.config import JarvisConfig

    assert JarvisConfig().mac_app_update_enabled is True


@pytest.mark.parametrize("version", ["0.4.0", "0.3.9"])
def test_an_older_or_same_app_is_not_offered(version: str) -> None:
    assert not _eval(_with_app(version), app_version="0.4.0")["app"]["available"]


def test_an_unknown_installed_app_is_not_overwritten() -> None:
    out = _eval(_with_app("0.4.1"), app_version="")
    assert not out["app"]["available"] and "읽지 못했습니다" in out["app"]["reason"]


def test_the_app_waits_for_python_first() -> None:
    out = _eval(_with_app("0.4.1", min_python_seq=202611170000), app_version="0.4.0", mine_seq=202611161000)
    assert out["app"]["available"] and not out["app"]["ready"] and "파이썬 묶음을 먼저" in out["app"]["reason"]


def test_an_app_without_a_signature_is_not_ready() -> None:
    out = _eval(_with_app("0.4.1", signature=""), app_version="0.4.0")
    assert not out["app"]["ready"]


@pytest.mark.parametrize("have,need,expect", [
    ("0.4.10", "0.4.9", True), ("0.4", "0.4.0", True), ("0.4.0", "0.4.1", False), ("x", "0.4.0", None),
])
def test_versions_compare_as_numbers(have: str, need: str, expect: bool | None) -> None:
    assert mac_update.version_at_least(have, need) is expect


def test_urls_must_be_https_unless_testing() -> None:
    assert mac_update.resolve_url("https://h/m/sonjari-mac.json", "python.zip") == "https://h/m/python.zip"
    with pytest.raises(mac_update.UpdateRefused):
        mac_update.resolve_url("https://h/m/sonjari-mac.json", "http://evil/python.zip")
    with pytest.raises(mac_update.UpdateRefused):
        mac_update.resolve_url("https://h/m/sonjari-mac.json", "file:///etc/passwd")
    assert mac_update.resolve_url("http://127.0.0.1:9/m.json", "p.zip", allow_http=True).startswith("http://")


def test_the_installed_app_version_is_read_from_the_bundle(tmp_path: Path) -> None:
    import plistlib

    app = tmp_path / "Sonjari.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.4.0"}))
    assert mac_update.installed_app_version(tmp_path / "Sonjari.app") == "0.4.0"
    assert mac_update.installed_app_version(tmp_path / "없음.app") == ""


# ── 묶음 ─────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    pkg = repo / "src" / "alture_jarvis"
    pkg.mkdir(parents=True)
    (pkg / "agent.py").write_text("A = 1\n", encoding="utf-8")
    (pkg / "update_seq.txt").write_text("1\n", encoding="utf-8")  # 저장소에 남은 낡은 값 — 실리면 안 된다
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "agent.pyc").write_bytes(b"pyc")
    (repo / "skills" / "drafts").mkdir(parents=True)
    (repo / "skills" / "drafts" / "mine.md").write_text("x", encoding="utf-8")
    (repo / "skills" / "a.md").write_text("skill", encoding="utf-8")
    (repo / "recipes").mkdir()
    (repo / "recipes" / "r.json").write_text("{}", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "jarvis.db").write_bytes(b"secret")
    (repo / ".env").write_text("TOKEN=SECRET", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repo / "README.ko.md").write_text("읽어", encoding="utf-8")
    (repo / "scripts" / "mac").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "mac" / "apply_update_mac.sh", repo / "scripts" / "mac" / "apply_update_mac.sh")
    (repo / "scripts" / "mac" / "install_mac.sh").write_text("echo", encoding="utf-8")
    return repo


def test_the_bundle_carries_what_the_mac_needs_and_nothing_else(fake_repo: Path, tmp_path: Path) -> None:
    made = mac_update.write_bundle(fake_repo, tmp_path / "b.zip", seq=202611161530)
    names = set(zipfile.ZipFile(made["path"]).namelist())
    assert {"src/alture_jarvis/agent.py", "skills/a.md", "recipes/r.json", "pyproject.toml", "README.ko.md",
            "scripts/mac/apply_update_mac.sh", "src/alture_jarvis/update_seq.txt"} <= names
    for forbidden in ("data/jarvis.db", ".env", "skills/drafts/mine.md", "src/alture_jarvis/__pycache__/agent.pyc",
                      "scripts/mac/install_mac.sh"):
        assert forbidden not in names, f"실리면 안 되는 것이 실렸다: {forbidden}"
    seq = zipfile.ZipFile(made["path"]).read("src/alture_jarvis/update_seq.txt").decode().strip()
    assert seq == "202611161530", "저장소에 남은 낡은 seq 가 실렸다"


def test_the_bundle_is_deterministic(fake_repo: Path, tmp_path: Path) -> None:
    one = mac_update.write_bundle(fake_repo, tmp_path / "a.zip", seq=7)
    two = mac_update.write_bundle(fake_repo, tmp_path / "b.zip", seq=7)
    assert one["sha256"] == two["sha256"]


def test_the_build_script_and_the_receiver_count_the_same_build(fake_repo: Path, tmp_path: Path) -> None:
    """규칙이 갈리면 받는 쪽은 늘 「판이 다르다」로 거절한다."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_mac_update", ROOT / "scripts" / "mac" / "build_mac_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    made = mac_update.write_bundle(fake_repo, tmp_path / "b.zip", seq=7)
    updater.unpack(Path(made["path"]), tmp_path / "staged")
    assert updater.staged_build(tmp_path / "staged") == module.source_build(fake_repo)


def test_the_build_script_refuses_an_app_that_needs_a_future_python(tmp_path: Path) -> None:
    sig = tmp_path / "app.sig"
    sig.write_text("SIG", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mac" / "build_mac_update.py"), "--out", str(tmp_path / "out"),
         "--seq", "100", "--app-version", "0.4.1", "--app-sig", str(sig), "--min-python-seq", "200",
         "--app-tarball", "Sonjari-0.4.1-mac-arm64.app.tar.gz", "--release-tag", "v0.4.1-mac"],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert done.returncode != 0 and "순서가 꼬입니다" in done.stderr


# ── 런타임 흐름(받기 → 확인 → 교체 스크립트) ───────────────────────────────────────────────


class _Stub:
    """`JarvisRuntime` 의 맥 갈래만 돌리는 대역. 네트워크는 `served` 사전에서 준다."""

    def __init__(self, tmp_path: Path, key, served: dict[str, bytes], url: str = "https://u.example/m/sonjari-mac.json"):
        self.config = types.SimpleNamespace(data_dir=str(tmp_path / "data"), mac_update_url=url,
                                            mac_update_allow_http=False, mac_app_path=str(tmp_path / "Sonjari.app"))
        self.events = types.SimpleNamespace(published=[], publish=lambda name, payload: self.events.published.append(name))
        self.served = served
        self.fetched: list[str] = []
        for name in ("_mac_update_paths", "_mac_update_status", "_mac_manifest", "_mac_update_check",
                     "_mac_update_apply"):
            setattr(self, name, types.MethodType(getattr(runtime.JarvisRuntime, name), self))

    def _mac_fetch(self, url: str, limit: int, timeout: float = 20.0) -> bytes:
        self.fetched.append(url)
        if url not in self.served:
            raise OSError(f"없음 {url}")
        return self.served[url]


@pytest.fixture()
def mac_world(tmp_path: Path, fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """서명된 목록 · 묶음이 놓인 배포처 + 공개 열쇠가 박힌 맥."""
    import plistlib

    key = _minisign.SigningKey.new()
    pub = tmp_path / "update_pubkey.txt"
    pub.write_text("# 시험 열쇠\n" + key.pub_text(wrap=False), encoding="utf-8")
    monkeypatch.setattr(mac_update, "PUBKEY_FILE", pub)
    monkeypatch.setattr(mac_update, "SEQ_FILE", tmp_path / "no_seq.txt")
    monkeypatch.setattr(mac_update.pubkey_text, "__defaults__", (pub,))
    monkeypatch.setattr(mac_update.baked_seq, "__defaults__", (tmp_path / "no_seq.txt",))
    monkeypatch.setattr(runtime, "build_id", lambda: "oldbuild0001")
    app = tmp_path / "Sonjari.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.4.0"}))

    import importlib.util

    spec = importlib.util.spec_from_file_location("build_mac_update", ROOT / "scripts" / "mac" / "build_mac_update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    made = mac_update.write_bundle(fake_repo, tmp_path / "python.zip", seq=202611161530)
    manifest = _manifest(build=module.source_build(fake_repo), sha256=made["sha256"], bytes=made["bytes"])
    raw, sig = _signed(key, manifest)
    base = "https://u.example/m/"
    served = {base + "sonjari-mac.json": raw, base + "sonjari-mac.json.sig": sig.encode(),
              base + "python.zip": Path(made["path"]).read_bytes()}
    popen: list[list[str]] = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args, **kw: popen.append(list(args)))
    return types.SimpleNamespace(key=key, served=served, base=base, manifest=manifest, popen=popen, tmp=tmp_path)


def test_a_good_update_hands_over_to_the_staged_script(mac_world) -> None:
    stub = _Stub(mac_world.tmp, mac_world.key, mac_world.served)
    out = stub._mac_update_apply()
    assert out["applied"], out
    assert len(mac_world.popen) == 1
    script = Path(mac_world.popen[0][1])
    assert script.parts[-3:] == ("scripts", "mac", "apply_update_mac.sh")
    assert "staged_mac" in script.parts, "받은 묶음 안의 스크립트가 아니라 깔린 것을 불렀다"
    plan = json.loads(Path(mac_world.popen[0][2]).read_text(encoding="utf-8"))
    assert plan["expected_build"] == mac_world.manifest["python"]["build"] and plan["seq"] == 202611161530


def test_a_fake_signature_changes_nothing(mac_world) -> None:
    attacker = _minisign.SigningKey.new()
    served = dict(mac_world.served)
    served[mac_world.base + "sonjari-mac.json.sig"] = attacker.sign(served[mac_world.base + "sonjari-mac.json"]).encode()
    stub = _Stub(mac_world.tmp, mac_world.key, served)
    out = stub._mac_update_apply()
    assert not out["applied"] and "서명" in out["reason"]
    assert mac_world.popen == []
    assert mac_world.base + "python.zip" not in stub.fetched, "서명이 틀렸는데 묶음까지 받았다"


def test_a_swapped_bundle_changes_nothing(mac_world) -> None:
    """배포처가 털려 zip 만 바꿔 놓았다 — 목록(서명됨)의 sha256 과 안 맞는다."""
    served = dict(mac_world.served)
    served[mac_world.base + "python.zip"] = served[mac_world.base + "python.zip"] + b"evil"
    out = _Stub(mac_world.tmp, mac_world.key, served)._mac_update_apply()
    assert not out["applied"] and "목록과 다릅니다" in out["reason"]
    assert mac_world.popen == []


def test_an_old_manifest_after_a_newer_one_changes_nothing(mac_world) -> None:
    """위협 3: 새 목록을 한 번 본 뒤, 배포처가 옛 진짜 목록(서명 진짜)을 다시 준다."""
    stub = _Stub(mac_world.tmp, mac_world.key, mac_world.served)
    newer = {**mac_world.manifest, "seq": 202612010000}
    raw, sig = _signed(mac_world.key, newer)
    stub.served = {**mac_world.served, mac_world.base + "sonjari-mac.json": raw,
                   mac_world.base + "sonjari-mac.json.sig": sig.encode()}
    assert stub._mac_update_check()["ok"]
    stub.served = mac_world.served  # 옛 목록으로 되돌림
    out = stub._mac_update_apply()
    assert not out["applied"] and "옛 목록" in out["reason"]
    assert mac_world.popen == []


def test_a_bundle_whose_code_differs_from_the_manifest_changes_nothing(mac_world, monkeypatch) -> None:
    """서명된 목록이 말한 판과 푼 것의 판이 다르면(빌드 실수) 갈아치우지 않는다."""
    manifest = {**mac_world.manifest, "python": {**mac_world.manifest["python"], "build": "otherbuild99"}}
    raw, sig = _signed(mac_world.key, manifest)
    served = {**mac_world.served, mac_world.base + "sonjari-mac.json": raw,
              mac_world.base + "sonjari-mac.json.sig": sig.encode()}
    out = _Stub(mac_world.tmp, mac_world.key, served)._mac_update_apply()
    assert not out["applied"] and "판이 다릅니다" in out["reason"]
    assert mac_world.popen == []


def test_no_key_or_no_url_means_off_with_a_reason(mac_world, monkeypatch) -> None:
    stub = _Stub(mac_world.tmp, mac_world.key, mac_world.served, url="")
    out = stub._mac_update_check()
    assert out["enabled"] is False and "배포 주소" in out["reason"] and stub.fetched == []
    empty = mac_world.tmp / "empty.txt"
    empty.write_text("# 비어 있음\n", encoding="utf-8")
    monkeypatch.setattr(mac_update.pubkey_text, "__defaults__", (empty,))
    out = _Stub(mac_world.tmp, mac_world.key, mac_world.served)._mac_update_check()
    assert out["enabled"] is False and "서명 열쇠" in out["reason"]


def test_an_unreachable_server_is_not_no_update(mac_world) -> None:
    out = _Stub(mac_world.tmp, mac_world.key, {})._mac_update_check()
    assert out["ok"] is False and "못 닿았습니다" in out["reason"]


#: 대표가 만든 진짜 열쇠(11-16 16:2x · `C:\keys\sonjari-mac-update.key.pub`). 열쇠를 갈면 이 값도 같이 바꾼다.
REAL_KEY_ID = "601B24A83ED65B82"


def test_the_shipped_pubkey_is_the_real_one_not_a_test_key() -> None:
    """박힌 공개 열쇠가 대표가 만든 그 열쇠인가 — 시험용 열쇠(fixtures)가 운영 자리에 들어가면 여기서 떨어진다."""
    key = update_sign.load_public_key(mac_update.pubkey_text(ROOT / "src" / "alture_jarvis" / "update_pubkey.txt"))
    assert key.key_id_hex == REAL_KEY_ID
    fixture = update_sign.load_public_key((ROOT / "tests" / "fixtures" / "mac_update" / "tauri_test.pub").read_text())
    assert key.key_id_hex != fixture.key_id_hex and key.key != fixture.key


def test_the_real_key_refuses_a_test_key_signature() -> None:
    """시험용 열쇠로 만든 서명(실제 타우리 서명)은 진짜 열쇠 앞에서 거절된다."""
    data = (ROOT / "tests" / "fixtures" / "mac_update" / "tauri_data.bin").read_bytes()
    sig = (ROOT / "tests" / "fixtures" / "mac_update" / "tauri_data.bin.sig").read_text()
    with pytest.raises(update_sign.SignatureError, match="다른 열쇠"):
        update_sign.verify(data, sig, mac_update.pubkey_text())


def test_the_pubkey_lives_in_one_place() -> None:
    """두 벌로 두면 한쪽만 바뀐다 — 화면 앱도 파이썬과 같은 파일을 빌드 때 굽는다."""
    assert not (ROOT / "ui" / "src-tauri" / "update_pubkey.txt").exists(), "화면 앱 쪽 사본이 다시 생겼다"
    rust = (ROOT / "ui" / "src-tauri" / "src" / "mac_update.rs").read_text(encoding="utf-8")
    include = re.search(r'include_str!\("([^"]+)"\)', rust).group(1)
    assert (ROOT / "ui" / "src-tauri" / "src" / include).resolve() == (ROOT / "src" / "alture_jarvis" / "update_pubkey.txt").resolve()
    assert mac_update.PUBKEY_FILE.resolve() == (ROOT / "src" / "alture_jarvis" / "update_pubkey.txt").resolve()


def test_the_default_address_is_the_github_release(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis.config import JarvisConfig

    monkeypatch.delenv("JARVIS_MAC_UPDATE_URL", raising=False)
    monkeypatch.delenv("JARVIS_MAC_APP_UPDATE_ENABLED", raising=False)
    assert JarvisConfig().mac_update_url == mac_update.DEFAULT_MANIFEST_URL
    loaded = JarvisConfig.from_env()
    assert loaded.mac_update_url == mac_update.DEFAULT_MANIFEST_URL and loaded.mac_app_update_enabled is True
    monkeypatch.setenv("JARVIS_MAC_APP_UPDATE_ENABLED", "0")
    assert JarvisConfig.from_env().mac_app_update_enabled is False  # 끄는 스위치는 남는다
    assert mac_update.DEFAULT_MANIFEST_URL == "https://github.com/sonjari/sonjari/releases/latest/download/sonjari-mac.json"
    assert mac_update.release_asset_url("mac-1", "python-a.zip") ==         "https://github.com/sonjari/sonjari/releases/download/mac-1/python-a.zip"


def test_a_tagged_build_pins_its_files_to_that_release(tmp_path: Path) -> None:
    """「최근 릴리스」는 목록과 묶음을 받는 사이에 바뀔 수 있다 — 묶음 주소는 태그로 못 박는다."""
    sig = tmp_path / "app.sig"
    sig.write_text("SIG", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mac" / "build_mac_update.py"), "--out", str(tmp_path / "out"),
         "--seq", "100", "--release-tag", "mac-100", "--app-version", "0.4.1", "--app-sig", str(sig),
         "--app-tarball", "Sonjari-0.4.1-mac-arm64.app.tar.gz"],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert done.returncode == 0, done.stderr
    manifest = json.loads((tmp_path / "out" / "sonjari-mac.json").read_text(encoding="utf-8"))
    assert manifest["python"]["url"].startswith("https://github.com/sonjari/sonjari/releases/download/mac-100/python-")
    assert manifest["app"]["latest_json"] == "https://github.com/sonjari/sonjari/releases/download/mac-100/latest.json"
    assert "/latest/" not in manifest["python"]["url"]
    latest = json.loads((tmp_path / "out" / "latest.json").read_text(encoding="utf-8"))
    assert latest["platforms"]["darwin-aarch64"]["url"].startswith("https://github.com/sonjari/sonjari/releases/download/mac-100/")


# ── 윈도우는 그대로 ────────────────────────────────────────────────────────────────────────


def _routing_stub(calls: list[str]):
    stub = types.SimpleNamespace(
        config=types.SimpleNamespace(private_update_enabled=False, store_update_dir="x"),
        _mac_update_check=lambda: calls.append("mac_check") or {"kind": "mac"},
        _mac_update_apply=lambda: calls.append("mac_apply") or {"kind": "mac"},
        events=types.SimpleNamespace(publish=lambda *a: None),
    )
    return stub


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_windows_never_takes_the_mac_road(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import store_update

    calls: list[str] = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(store_update, "check", lambda: calls.append("store_check") or {"kind": "none"})
    monkeypatch.setattr(store_update, "package_full_name", lambda: calls.append("store_pkg") or "")
    stub = _routing_stub(calls)
    out = runtime.JarvisRuntime.update_check(stub)
    assert out == {"ok": True, "enabled": False, "available": False}, "윈도우 비활성 응답 모양이 바뀌었다"
    with pytest.raises(RuntimeError, match="private_update_disabled"):
        runtime.JarvisRuntime.update_apply(stub)
    assert calls == ["store_check", "store_pkg"]


def test_the_mac_takes_the_mac_road(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import store_update

    calls: list[str] = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(store_update, "check", lambda: calls.append("store_check") or {})
    stub = _routing_stub(calls)
    assert runtime.JarvisRuntime.update_check(stub)["kind"] == "mac"
    assert runtime.JarvisRuntime.update_apply(stub)["kind"] == "mac"
    assert calls == ["mac_check", "mac_apply"]


# ── 화면 앱(타우리) 설정 ──────────────────────────────────────────────────────────────────


def test_the_updater_crate_is_mac_only() -> None:
    """윈도우 exe 에는 업데이트 부품이 안 들어간다 — 스토어가 갱신한다."""
    cargo = (ROOT / "ui" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^\[", cargo)
    holders = [s.split("]", 1)[0] for s in sections if "tauri-plugin-updater" in s.split("\n", 1)[-1]]
    assert holders == ["target.'cfg(target_os = \"macos\")'.dependencies"], holders


def test_only_the_mac_config_carries_the_updater_section() -> None:
    conf = ROOT / "ui" / "src-tauri"
    mac = json.loads((conf / "tauri.macos.conf.json").read_text(encoding="utf-8"))
    # 플러그인 설정은 pubkey 칸이 반드시 있어야 켜진다(tauri-plugin-updater 2.12 config.rs — 기본값 없음).
    assert "pubkey" in mac["plugins"]["updater"]
    for name in ("tauri.conf.json", "tauri.msix.conf.json", "tauri.store.conf.json"):
        data = json.loads((conf / name).read_text(encoding="utf-8"))
        assert "updater" not in (data.get("plugins") or {}), f"{name} 에 업데이트 설정이 들어갔다"


def test_the_hud_registers_both_commands_and_the_mac_plugin() -> None:
    lib = (ROOT / "ui" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "mac_update::app_update_check" in lib and "mac_update::app_update_install" in lib
    assert "mac_update::with_updater(tauri::Builder::default())" in lib


# ── 교체 스크립트를 실제 sh 로 ────────────────────────────────────────────────────────────

_SH = shutil.which("sh")


def _stub_tools(tmp: Path, app: Path, health: Path) -> dict[str, str]:
    """맥의 plutil · curl · launchctl 대역. launchctl kickstart 는 **지금 app/ 의 코드로** /health build 를 바꾼다."""
    tools = tmp / "tools"
    tools.mkdir()
    py = sys.executable.replace("\\", "/")
    (tools / "plutil.py").write_text(
        "import json,sys\n"
        "a=sys.argv[1:]; key=a[a.index('-extract')+1]; src=a[-1]\n"
        "data=json.load(sys.stdin if src=='-' else open(src,encoding='utf-8'))\n"
        "for part in key.split('.'):\n"
        "    try:\n        data=data[int(part)] if isinstance(data,list) else data[part]\n"
        "    except (KeyError,IndexError,ValueError):\n        sys.exit(1)\n"
        "print(data)\n", encoding="utf-8")
    (tools / "kick.py").write_text(
        # 11-23: 진짜 본체처럼 판 번호를 config.code_digest(규칙 하나 · 줄 끝 무시)로 센다 — 시험 안에 규칙을 베끼지 않는다.
        "import json,sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, r'{ROOT / 'src'}')\nfrom alture_jarvis.config import code_digest\n"
        f"pkg=Path(r'{app}')/'src'/'alture_jarvis'\n"
        f"Path(r'{health}').write_text(json.dumps({{'build': code_digest(pkg)}}))\n", encoding="utf-8")
    for name, body in (("plutil", f'exec "{py}" "{tools / "plutil.py"}" "$@"'),
                       ("curl", f'cat "{health}"'),
                       ("launchctl", f'exec "{py}" "{tools / "kick.py"}"')):
        path = tools / name
        path.write_text("#!/bin/sh\n" + body.replace("\\", "/") + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)
    return {"SONJARI_PLUTIL": str(tools / "plutil").replace("\\", "/"),
            "SONJARI_CURL": str(tools / "curl").replace("\\", "/"),
            "SONJARI_LAUNCHCTL": str(tools / "launchctl").replace("\\", "/")}


def _apply_world(tmp: Path, fake_repo: Path, expected: str | None = None):
    app = tmp / "app"
    for name in ("src", "skills", "recipes"):
        shutil.copytree(fake_repo / name, app / name)
    (app / "src" / "alture_jarvis" / "agent.py").write_text("A = 'old'\n", encoding="utf-8")
    shutil.copy(fake_repo / "pyproject.toml", app / "pyproject.toml")
    (app / ".venv").mkdir()
    made = mac_update.write_bundle(fake_repo, tmp / "p.zip", seq=9)
    staging = tmp / "work" / "staged_mac"
    updater.unpack(Path(made["path"]), staging)
    work = tmp / "work"
    plan = mac_update.plan(app, staging, expected or updater.staged_build(staging), 9, work)
    plan["health_wait_sec"] = 4
    plan_path = updater.write_plan(work / "plan_mac.json", plan)
    health = tmp / "health.json"
    health.write_text(json.dumps({"build": "before"}), encoding="utf-8")
    env = {**os.environ, **_stub_tools(tmp, app, health)}
    return app, staging, plan_path, work, env


def _run(staging: Path, plan_path: Path, env: dict) -> subprocess.CompletedProcess:
    script = (staging / "scripts" / "mac" / "apply_update_mac.sh").as_posix()
    return subprocess.run([_SH, script, plan_path.as_posix()], env=env, capture_output=True, timeout=60)


@pytest.mark.skipif(_SH is None, reason="sh 가 없다")
def test_the_apply_script_swaps_restarts_and_confirms(tmp_path: Path, fake_repo: Path) -> None:
    app, staging, plan_path, work, env = _apply_world(tmp_path, fake_repo)
    _run(staging, plan_path, env)
    result = json.loads((work / "last_result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True, result
    assert (app / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8") == "A = 1\n"
    assert (app / "src" / "alture_jarvis" / "update_seq.txt").read_text().strip() == "9"
    assert (app / ".venv").is_dir(), "가상환경까지 갈아치웠다"
    assert any((work / "backup").iterdir()), "옮겨 둔 것이 없다"


@pytest.mark.skipif(_SH is None, reason="sh 가 없다")
def test_the_apply_script_rolls_back_when_the_new_build_does_not_show(tmp_path: Path, fake_repo: Path) -> None:
    """새 판이 /health 에 안 뜨면(여기선 기대값을 일부러 틀리게) 옛 코드로 되돌린다."""
    app, staging, plan_path, work, env = _apply_world(tmp_path, fake_repo, expected="neverappears")
    _run(staging, plan_path, env)
    result = json.loads((work / "last_result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False and "되돌렸습니다" in result["reason"]
    assert (app / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8") == "A = 'old'\n"
    # 깔려 있던 것(fake_repo 에서 복사한 낡은 값 「1」)으로 돌아왔다 — 새 묶음의 9 가 아니라.
    assert (app / "src" / "alture_jarvis" / "update_seq.txt").read_text().strip() == "1"
    assert (app / "skills" / "a.md").is_file() and (app / "recipes" / "r.json").is_file()
