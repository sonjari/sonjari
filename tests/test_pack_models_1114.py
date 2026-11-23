"""팩이 켜질 때 모델 · 실행기를 받는 장치 (2026-11-14) — 칸 검증 · 해시 · 이어 받기 · 거울 · 디스크 · 라이선스. 네트워크는 가짜."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from alture_jarvis.pack_models import ModelError, ModelFetcher, parse_models, platform_fits, this_platform
from alture_jarvis.packs import PackError, PackRegistry, load_packs

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _short_paths(monkeypatch):
    # 11-23: 긴 폴더면 허깅페이스 라이브러리를 건너뛴다(test_pack_hf_long_path_1123). 여기 시험은 라이브러리 길을 보므로
    # 이 PC 의 임시 폴더 길이에 결과가 흔들리지 않게 「짧음」으로 고정한다.
    import alture_jarvis.pack_models as pm
    monkeypatch.setattr(pm, "_hf_temp_too_long", lambda target, windows=None: False)


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buffer.getvalue()


ZIP = _zip({"trellis-cli.exe": b"EXE" * 100, "lib/a.dll": b"DLL"})
ZIP_SHA = hashlib.sha256(ZIP).hexdigest()


def _binary(**over):
    base = {
        "id": "runner", "kind": "binary", "dir": "runner-dir",
        "source": {"github_release": "o/r", "tag": "v1", "asset": "r.zip"},
        "sha256": ZIP_SHA, "size": len(ZIP), "license": "MIT", "license_url": "https://github.com/o/r/blob/main/LICENSE",
        "unpack": True, "required": True,
    }
    base.update(over)
    return base


class _Packs:
    def __init__(self, *models):
        self.packs = {"gen3d": type("P", (), {"models": parse_models("gen3d", list(models))})()}


class Net:
    """가짜 인터넷. 부른 주소를 센다. `serve` 가 (status, 본문) 을 정한다."""

    def __init__(self, routes: dict[str, bytes], *, ignore_range: bool = False, cut_at: int | None = None):
        self.routes, self.calls, self.ignore_range, self.cut_at = routes, [], ignore_range, cut_at

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url not in self.routes:
            raise ModelError(f"http_404: {url}")
        body = self.routes[url]
        start = 0
        status = 200
        if "Range" in headers and not self.ignore_range:
            start = int(headers["Range"].split("=")[1].rstrip("-"))
            if start >= len(body):
                return _R(416, b"", {})
            body, status = body[start:], 206
        full = len(body)
        if self.cut_at is not None and status in (200, 206) and start == 0:
            body = body[: self.cut_at]
        return _R(status, body, {"content-length": str(full)})


class _R:
    def __init__(self, status, body, headers):
        self.status, self.headers, self._io = status, headers, io.BytesIO(body)

    def read(self, n=-1):
        return self._io.read(n)

    def close(self):
        pass


URL = "https://github.com/o/r/releases/download/v1/r.zip"
LIC = "https://raw.githubusercontent.com/o/r/main/LICENSE"


def _fetcher(tmp_path, *models, net=None, mirror=None, free=10**12):
    return ModelFetcher(_Packs(*models), tmp_path / "data", mirror_dir=mirror, opener=net or Net({}),
                        hf_snapshot=None, free_bytes=lambda _p: free)


# ── models 칸 검증 ──


@pytest.mark.parametrize("bad", [
    {"id": "Bad Id"}, {"kind": "exe"}, {"sha256": "abc"}, {"size": -1}, {"license": ""},
    {"source": {}}, {"source": {"github_release": "o/r", "tag": "v1"}},
    {"source": {"github_release": "o/r", "tag": "v1", "asset": "../x.zip"}},
    {"source": {"hf": "nope"}}, {"license_url": "http://x"}, {"dir": ".."}, {"dir": "a/b"},
    {"unpack": True, "kind": "weights", "source": {"hf": "o/r"}},
    {"source": {"github_release": "o/r", "tag": "v1", "asset": "a.zip", "hf": "o/r"}},
])
def test_bad_models_are_refused_with_a_reason(bad) -> None:
    with pytest.raises(ModelError, match="gen3d"):
        parse_models("gen3d", [_binary(**bad)])


def test_good_models_and_duplicate_ids() -> None:
    parsed = parse_models("gen3d", [_binary(), {
        "id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["q8/*"]}, "size": 5, "license": "MIT"}])
    assert [m["id"] for m in parsed] == ["runner", "w"] and parsed[1]["source"]["revision"] == "main"
    with pytest.raises(ModelError, match="겹친다"):
        parse_models("gen3d", [_binary(), _binary(dir="other")])
    with pytest.raises(ModelError, match="같은 자리"):
        parse_models("gen3d", [_binary(), _binary(id="runner2")])


def test_a_pack_with_a_bad_models_field_is_not_loaded(tmp_path) -> None:
    folder = tmp_path / "packs" / "gen3d"
    folder.mkdir(parents=True)
    data = {"id": "gen3d", "name": "x", "version": "1", "kind": "code", "summary": "s", "tools": [], "skills": [],
            "permissions": {"reads": [], "writes": [], "runs": [], "network": "n"}, "models": [_binary(sha256="zz")]}
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    packs, problems = load_packs(tmp_path / "packs")
    assert "gen3d" not in packs and "sha256" in problems[0]
    data["models"] = [_binary()]
    data["kind"] = "content"
    data["tools"] = []
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    assert "코드 팩" in load_packs(tmp_path / "packs")[1][0]
    data["kind"] = "code"
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    packs, problems = load_packs(tmp_path / "packs")
    assert problems == [] and packs["gen3d"].models[0]["id"] == "runner"
    listed = PackRegistry(tmp_path / "packs", tmp_path / "d").describe("gen3d")
    assert listed["models"][0]["license"] == "MIT" and "source" not in listed["models"][0]


# ── 받기 ──


def test_download_unpack_license_and_ready(tmp_path) -> None:
    net = Net({URL: ZIP, LIC: b"MIT License text"})
    f = _fetcher(tmp_path, _binary(), net=net)
    outcome = f.fetch("gen3d", wait=True)
    assert outcome["started"] is True
    status = f.status("gen3d")
    assert status["state"] == "done" and status["all_ready"] is True and status["models"][0]["state"] == "ready"
    target = tmp_path / "data" / "tools" / "gen3d" / "runner-dir"
    assert (target / "trellis-cli.exe").read_bytes() == b"EXE" * 100
    assert (target / "LICENSE.txt").read_text(encoding="utf-8") == "MIT License text"
    assert not (tmp_path / "data" / "tools" / "gen3d" / ".dl" / "r.zip.part").exists(), "받은 압축 파일은 푼 뒤 지운다"
    # 한 번 더 누르면 받을 것이 없다
    calls = len(net.calls)
    f.fetch("gen3d", wait=True)
    assert len(net.calls) == calls


def test_wrong_hash_fails_and_leaves_nothing(tmp_path) -> None:
    net = Net({URL: ZIP + b"tampered", LIC: b"x"})
    f = _fetcher(tmp_path, _binary(), net=net)
    f.fetch("gen3d", wait=True)
    status = f.status("gen3d")
    assert status["state"] == "failed" and "sha256_mismatch" in status["error"]
    assert status["models"][0]["state"] == "failed" and status["all_ready"] is False
    data = tmp_path / "data" / "tools" / "gen3d"
    leftovers = [p for p in data.rglob("*") if p.is_file()]
    assert leftovers == [], f"해시가 틀리면 파일을 남기지 않는다: {leftovers}"


def test_resume_continues_from_the_partial_file(tmp_path) -> None:
    net = Net({URL: ZIP, LIC: b"lic"})
    f = _fetcher(tmp_path, _binary(), net=net)
    part = tmp_path / "data" / "tools" / "gen3d" / ".dl" / "r.zip.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(ZIP[:100])
    assert f.status("gen3d")["models"][0]["state"] == "partial" and f.status("gen3d")["models"][0]["received"] == 100
    f.fetch("gen3d", wait=True)
    assert net.calls[0][1]["Range"] == "bytes=100-"
    assert f.status("gen3d")["state"] == "done"


def test_server_that_ignores_range_restarts_cleanly(tmp_path) -> None:
    net = Net({URL: ZIP, LIC: b"lic"}, ignore_range=True)
    f = _fetcher(tmp_path, _binary(), net=net)
    part = tmp_path / "data" / "tools" / "gen3d" / ".dl" / "r.zip.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"junk" * 10)
    f.fetch("gen3d", wait=True)
    assert f.status("gen3d")["state"] == "done"


def test_a_cut_connection_keeps_the_part_for_resume(tmp_path) -> None:
    net = Net({URL: ZIP, LIC: b"lic"}, cut_at=50)
    f = _fetcher(tmp_path, _binary(), net=net)
    f.fetch("gen3d", wait=True)
    status = f.status("gen3d")
    assert status["state"] == "failed" and "incomplete" in status["error"]
    assert (tmp_path / "data" / "tools" / "gen3d" / ".dl" / "r.zip.part").stat().st_size == 50
    f2 = _fetcher(tmp_path, _binary(), net=Net({URL: ZIP, LIC: b"lic"}))
    f2.fetch("gen3d", wait=True)
    assert f2.status("gen3d")["state"] == "done"


def test_mirror_is_used_and_the_internet_is_not(tmp_path) -> None:
    mirror = tmp_path / "nas"
    mirror.mkdir()
    (mirror / "r.zip").write_bytes(ZIP)
    (mirror / "runner.LICENSE.txt").write_text("mirror license", encoding="utf-8")
    weights = {"id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["q8/*"]}, "size": 6, "license": "MIT"}
    (mirror / "w" / "q8").mkdir(parents=True)
    (mirror / "w" / "q8" / "m.gguf").write_bytes(b"GGUF12")
    net = Net({})
    f = _fetcher(tmp_path, _binary(), weights, net=net, mirror=mirror)
    assert all(m["via_mirror"] for m in f.status("gen3d")["models"])
    f.fetch("gen3d", wait=True)
    assert net.calls == [], "거울에 있으면 인터넷에 안 나간다(라이선스 포함)"
    assert f.status("gen3d")["state"] == "done"
    assert (tmp_path / "data" / "models" / "gen3d" / "w" / "q8" / "m.gguf").read_bytes() == b"GGUF12"
    assert (tmp_path / "data" / "tools" / "gen3d" / "runner-dir" / "LICENSE.txt").read_text(encoding="utf-8") == "mirror license"
    assert (tmp_path / "data" / "models" / "gen3d" / "w" / "LICENSE.txt").exists()


def test_a_bad_mirror_file_is_refused_not_trusted(tmp_path) -> None:
    mirror = tmp_path / "nas"
    mirror.mkdir()
    (mirror / "r.zip").write_bytes(ZIP + b"x")
    f = _fetcher(tmp_path, _binary(), net=Net({}), mirror=mirror)
    f.fetch("gen3d", wait=True)
    assert f.status("gen3d")["state"] == "failed" and "sha256_mismatch" in f.status("gen3d")["error"]
    assert not (tmp_path / "data" / "tools" / "gen3d" / "runner-dir").exists()


def test_not_enough_disk_does_not_start(tmp_path) -> None:
    net = Net({URL: ZIP})
    f = _fetcher(tmp_path, _binary(size=10**9), net=net, free=10**8)
    outcome = f.fetch("gen3d", wait=True)
    assert outcome["ok"] is False and outcome["error"] == "not_enough_disk" and outcome["disk_ok"] is False
    assert net.calls == [] and not (tmp_path / "data" / "tools").exists()
    assert f.status("gen3d")["disk_free_bytes"] == 10**8


def test_status_before_fetch_shows_size_license_disk(tmp_path) -> None:
    f = _fetcher(tmp_path, _binary(size=1000), net=Net({}))
    s = f.status("gen3d")
    assert s["models"][0]["state"] == "missing" and s["models"][0]["license"] == "MIT"
    assert s["to_download_bytes"] == 1000 and s["disk_needed_bytes"] == 2000, "압축을 풀 자리까지 센다"
    assert s["disk_ok"] is True and s["state"] == "idle"


def test_license_fallback_when_it_cannot_be_fetched(tmp_path) -> None:
    f = _fetcher(tmp_path, _binary(), net=Net({URL: ZIP}))  # LIC 주소는 404
    f.fetch("gen3d", wait=True)
    text = (tmp_path / "data" / "tools" / "gen3d" / "runner-dir" / "LICENSE.txt").read_text(encoding="utf-8")
    assert "MIT" in text and "github.com/o/r" in text


def test_zip_slip_is_refused(tmp_path) -> None:
    evil = _zip({"../../evil.txt": b"x"})
    sha = hashlib.sha256(evil).hexdigest()
    f = _fetcher(tmp_path, _binary(sha256=sha, size=len(evil)), net=Net({URL: evil}))
    f.fetch("gen3d", wait=True)
    assert f.status("gen3d")["state"] == "failed" and "unsafe_zip_path" in f.status("gen3d")["error"]
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "data" / "evil.txt").exists()


def test_cancel_stops_and_keeps_the_part(tmp_path) -> None:
    import threading

    gate = threading.Event()

    class Slow(Net):
        def __call__(self, url, headers):
            r = super().__call__(url, headers)
            real = r.read

            def read(n=-1):
                gate.set()
                f.cancel("gen3d")
                return real(10)
            r.read = read
            return r

    f = _fetcher(tmp_path, _binary(), net=Slow({URL: ZIP, LIC: b"x"}))
    f.fetch("gen3d", wait=True)
    assert f.status("gen3d")["state"] == "cancelled"
    assert not (tmp_path / "data" / "tools" / "gen3d" / "runner-dir").exists()


def test_hf_https_path_filters_include_and_checks_lfs_hash(tmp_path) -> None:
    good = b"GGUF" * 10
    tree = [
        {"type": "file", "path": "q8/a.gguf", "size": len(good), "lfs": {"oid": hashlib.sha256(good).hexdigest()}},
        {"type": "file", "path": "q4/b.gguf", "size": 1},
        {"type": "directory", "path": "q8"},
    ]
    base = "https://huggingface.co/a/b"
    net = Net({f"{base.replace('huggingface.co/', 'huggingface.co/api/models/')}/tree/main?recursive=true": json.dumps(tree).encode(),
               f"{base}/resolve/main/q8/a.gguf": good})
    w = {"id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["q8/*"]}, "size": len(good), "license": "MIT"}
    f = _fetcher(tmp_path, w, net=net)
    f.fetch("gen3d", wait=True)
    root = tmp_path / "data" / "models" / "gen3d" / "w"
    assert f.status("gen3d")["state"] == "done" and (root / "q8" / "a.gguf").read_bytes() == good
    assert not (root / "q4").exists(), "include 밖 파일은 받지 않는다"
    # 해시가 틀린 파일은 지운다
    net2 = Net({k: (v if "resolve" not in k else b"BAD" * 20) for k, v in net.routes.items()})
    f2 = ModelFetcher(_Packs(w), tmp_path / "d2", opener=net2, hf_snapshot=None, free_bytes=lambda _p: 10**12)
    f2.fetch("gen3d", wait=True)
    assert "sha256_mismatch" in f2.status("gen3d")["error"]
    assert [p for p in (tmp_path / "d2").rglob("*") if p.is_file()] == []


def test_hf_hub_library_is_used_when_given(tmp_path) -> None:
    seen = {}

    def snapshot(**kw):
        seen.update(kw)
        Path(kw["local_dir"], "q8").mkdir(parents=True)
        Path(kw["local_dir"], "q8", "m.gguf").write_bytes(b"x")

    w = {"id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["q8/*"]}, "size": 1, "license": "MIT"}
    net = Net({})
    f = ModelFetcher(_Packs(w), tmp_path / "d", opener=net, hf_snapshot=snapshot, free_bytes=lambda _p: 10**12)
    f.fetch("gen3d", wait=True)
    assert seen["repo_id"] == "a/b" and seen["allow_patterns"] == ["q8/*"] and f.status("gen3d")["state"] == "done"


def test_unknown_pack_and_api_routes() -> None:
    f = ModelFetcher(_Packs(), Path("x"), hf_snapshot=None)
    with pytest.raises(ModelError):
        f.status("nope")
    source = (REPO / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    for route in ('"/v1/packs/{pack_id}/models"', '"/v1/packs/{pack_id}/models/fetch"', '"/v1/packs/{pack_id}/models/cancel"'):
        assert route in source, route
    assert "models_status" in source


def test_the_api_end_to_end_with_a_fake_pack(tmp_path) -> None:
    """실제 FastAPI 문으로: 켜기 응답에 받을 것이 실리고 · 꺼진 팩은 받기를 거절하고 · 받은 뒤 상태가 ready · 열쇠 없으면 401."""
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    folder = tmp_path / "packs" / "gen3d"
    folder.mkdir(parents=True)
    data = {"id": "gen3d", "name": "x", "version": "1", "kind": "code", "summary": "s", "tools": [], "skills": [],
            "permissions": {"reads": [], "writes": [], "runs": [], "network": "n"}, "models": [_binary()]}
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
                          tts_enabled=False, packs_dir=tmp_path / "packs")
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    runtime.pack_models = ModelFetcher(runtime.packs, tmp_path / "data", opener=Net({URL: ZIP, LIC: b"lic"}),
                                       hf_snapshot=None, free_bytes=lambda _p: 10**12)
    auth = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.get("/v1/packs/gen3d/models").status_code == 401
        assert client.post("/v1/packs/gen3d/models/fetch", headers=auth).status_code == 409  # 아직 안 켰다
        enabled = client.post("/v1/packs/gen3d/enable", headers=auth).json()
        card = enabled["models_status"]
        assert card["models"][0]["license"] == "MIT" and card["disk_ok"] is True and card["models"][0]["size"] == len(ZIP)
        started = client.post("/v1/packs/gen3d/models/fetch", headers=auth).json()
        assert started["ok"] is True
        runtime.pack_models.join("gen3d", 10)
        final = client.get("/v1/packs/gen3d/models", headers=auth).json()
        assert final["state"] == "done" and final["models"][0]["state"] == "ready"
        assert client.post("/v1/packs/gen3d/models/cancel", headers=auth).json()["ok"] is True
        assert client.get("/v1/packs/nope/models", headers=auth).status_code == 404


# ── 이 기계용만 받기(11-14 맥: 받기를 누르자 윈도우 실행기 826MB 가 맥에 받아졌다) ──

WIN = ("win", "x64")
MAC = ("macos", "arm64")
MAC_ZIP = _zip({"trellis-cli": b"MACH" * 50, "libggml.0.dylib": b"DYLIB"})
MAC_ZIP_SHA = hashlib.sha256(MAC_ZIP).hexdigest()


def _win_bin():
    return _binary(id="runner-win", dir="runner-win", platform="win-x64-cuda")


def _mac_bin(**over):
    base = _binary(id="runner-mac", dir="runner-mac", platform="macos-arm64-metal",
                   source={"build": "o/r", "tag": "v1", "asset": "mac.zip", "how": "README 의 cmake 두 줄"},
                   sha256=MAC_ZIP_SHA, size=len(MAC_ZIP))
    base.update(over)
    return base


def _weights():
    return {"id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["q8/*"]}, "size": 1, "license": "MIT"}


def _snapshot(**kw):
    Path(kw["local_dir"], "q8").mkdir(parents=True, exist_ok=True)
    Path(kw["local_dir"], "q8", "m.gguf").write_bytes(b"x")


def _platform_fetcher(tmp_path, here, *, net=None, mirror=None):
    return ModelFetcher(_Packs(_win_bin(), _mac_bin(), _weights()), tmp_path / "data", mirror_dir=mirror,
                        opener=net or Net({URL: ZIP, LIC: b"lic"}), hf_snapshot=_snapshot,
                        free_bytes=lambda _p: 10**12, platform=here)


@pytest.mark.parametrize("system,machine,want", [
    ("win32", "AMD64", ("win", "x64")), ("darwin", "arm64", ("macos", "arm64")), ("linux", "x86_64", ("linux", "x64")),
    ("linux", "aarch64", ("linux", "arm64")),
])
def test_this_platform_names(system, machine, want) -> None:
    assert this_platform(system, machine) == want


def test_platform_fits_only_the_os_and_chip() -> None:
    assert platform_fits("win-x64-cuda", WIN) and not platform_fits("win-x64-cuda", MAC)
    assert platform_fits("macos-arm64-metal", MAC) and not platform_fits("macos-arm64-metal", WIN)
    assert not platform_fits("macos-x64-metal", MAC), "칩이 다르면 안 맞는다(인텔 맥)"
    assert platform_fits("", MAC) and platform_fits("", WIN), "칸이 비면(가중치) 어디서나 받는다"


@pytest.mark.parametrize("bad", [{"platform": "Windows"}, {"platform": "win"}, {"platform": "win x64"}])
def test_a_bad_platform_tag_is_refused(bad) -> None:
    with pytest.raises(ModelError, match="platform"):
        parse_models("gen3d", [_binary(**bad)])


def test_build_source_is_for_binaries_only() -> None:
    with pytest.raises(ModelError, match="build"):
        parse_models("gen3d", [{**_weights(), "source": {"build": "o/r", "tag": "v1", "asset": "a.zip"}}])
    parsed = parse_models("gen3d", [_mac_bin()])
    assert parsed[0]["source"] == {"build": "o/r", "tag": "v1", "asset": "mac.zip", "how": "README 의 cmake 두 줄"}


def test_windows_takes_only_the_windows_runner_and_the_weights(tmp_path) -> None:
    f = _platform_fetcher(tmp_path, WIN)
    before = {m["id"]: m for m in f.status("gen3d")["models"]}
    assert before["runner-mac"]["state"] == "not_for_this_machine"
    assert before["runner-win"]["state"] == "missing" and before["w"]["state"] == "missing"
    assert f.status("gen3d")["to_download_bytes"] == len(ZIP) + 1, "맥 실행기는 받을 양에 안 든다"
    f.fetch("gen3d", wait=True)
    after = f.status("gen3d")
    assert after["state"] == "done" and after["all_ready"] is True, after
    states = {m["id"]: m["state"] for m in after["models"]}
    assert states == {"runner-win": "ready", "runner-mac": "not_for_this_machine", "w": "ready"}
    assert not (tmp_path / "data" / "tools" / "gen3d" / "runner-mac").exists()
    assert after["leftovers"] == [] and after["platform"] == "win-x64"


def test_a_mac_never_downloads_the_windows_runner(tmp_path) -> None:
    net = Net({URL: ZIP, LIC: b"lic"})
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "mac.zip").write_bytes(MAC_ZIP)
    f = _platform_fetcher(tmp_path, MAC, net=net, mirror=mirror)
    assert f.status("gen3d")["to_download_bytes"] == 1, "윈도우 실행기는 받을 양에 안 든다 · 맥 실행기는 거울"
    f.fetch("gen3d", wait=True)
    status = f.status("gen3d")
    assert status["state"] == "done" and status["all_ready"] is True, status
    assert all(URL != url for url, _h in net.calls), "윈도우 zip 주소를 부르면 안 된다"
    states = {m["id"]: m["state"] for m in status["models"]}
    assert states == {"runner-win": "not_for_this_machine", "runner-mac": "ready", "w": "ready"}
    assert (tmp_path / "data" / "tools" / "gen3d" / "runner-mac" / "trellis-cli").read_bytes() == b"MACH" * 50
    assert not (tmp_path / "data" / "tools" / "gen3d" / "runner-win").exists()


def test_a_mac_without_a_mirror_says_how_and_takes_a_hand_built_folder(tmp_path) -> None:
    f = _platform_fetcher(tmp_path, MAC)
    f.fetch("gen3d", wait=True)
    status = f.status("gen3d")
    assert status["state"] == "failed" and status["error"].startswith("no_prebuilt"), status
    assert "runner-mac" in status["error"] and "mac.zip" in status["error"] and "cmake" in status["error"]
    assert status["to_download_bytes"] == 1, "빌드해 넣을 것은 인터넷에서 받을 양이 아니다"
    row = {m["id"]: m for m in status["models"]}["runner-mac"]
    assert row["hand_built"] is True and row["how"] == "README 의 cmake 두 줄"
    # 빌드한 것을 그 자리에 넣고 다시 누르면 들인다
    placed = tmp_path / "data" / "tools" / "gen3d" / "runner-mac"
    placed.mkdir(parents=True)
    (placed / "trellis-cli").write_bytes(b"built")
    f.fetch("gen3d", wait=True)
    status = f.status("gen3d")
    assert status["all_ready"] is True and {m["id"]: m["state"] for m in status["models"]}["runner-mac"] == "ready"
    assert json.loads((placed / ".ready.json").read_text(encoding="utf-8"))["by_hand"] is True


def test_a_wrong_mac_zip_in_the_mirror_is_refused(tmp_path) -> None:
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "mac.zip").write_bytes(_zip({"trellis-cli": b"OTHER"}))
    f = _platform_fetcher(tmp_path, MAC, mirror=mirror)
    f.fetch("gen3d", wait=True)
    assert "sha256_mismatch" in f.status("gen3d")["error"]
    assert not (tmp_path / "data" / "tools" / "gen3d" / "runner-mac").exists()


def test_leftovers_from_another_machine_are_shown_and_removed_only_on_request(tmp_path) -> None:
    # 맥에 윈도우 실행기가 이미 받아져 있다(11-14 실제로 일어남)
    stale = tmp_path / "data" / "tools" / "gen3d" / "runner-win"
    stale.mkdir(parents=True)
    (stale / "trellis-cli.exe").write_bytes(b"E" * 1000)
    weights = tmp_path / "data" / "models" / "gen3d" / "w" / "q8"
    weights.mkdir(parents=True)
    (weights / "m.gguf").write_bytes(b"x")
    f = _platform_fetcher(tmp_path, MAC)
    status = f.status("gen3d")
    assert status["leftovers"] == [{"id": "runner-win", "platform": "win-x64-cuda", "path": str(stale), "bytes": 1000}]
    assert stale.exists(), "보이기만 하고 지우지 않는다"
    # 받는 중에는 지우지 않는다
    f._runs["gen3d"] = {"state": "running"}
    assert f.remove_leftovers("gen3d")["ok"] is False and stale.exists()
    f._runs["gen3d"] = {"state": "idle"}
    removed = f.remove_leftovers("gen3d")
    assert removed["ok"] is True and [r["id"] for r in removed["removed"]] == ["runner-win"]
    assert not stale.exists() and (weights / "m.gguf").is_file(), "가중치(어디서나 쓰는 것)는 남는다"
    assert f.status("gen3d")["leftovers"] == []
    # 윈도우에서는 맥 자리에 아무것도 없으니 남은 것도 없다
    assert _platform_fetcher(tmp_path, WIN).status("gen3d")["leftovers"] == []


def test_the_real_gen3d_pack_has_one_runner_per_machine_and_the_runner_dirs_match() -> None:
    from alture_jarvis.gen3d_tools import BIN_DIRS

    manifest = json.loads((REPO / "packs" / "gen3d" / "pack.json").read_text(encoding="utf-8"))
    parsed = parse_models("gen3d", manifest["models"])
    for system, here in (("win32", WIN), ("darwin", MAC)):
        runners = [m for m in parsed if m["kind"] == "binary" and platform_fits(m["platform"], here)]
        assert len(runners) == 1, (system, runners)
        assert runners[0]["dir"] == BIN_DIRS[system], "실행기가 받히는 자리와 실행기를 찾는 자리가 같아야 한다"
        weights = [m for m in parsed if m["kind"] == "weights"]
        assert weights and all(platform_fits(m["platform"], here) for m in weights)
    mac = next(m for m in parsed if m["platform"].startswith("macos"))
    # 11-14 대표 승인: 맥 판은 우리 공개 저장소 릴리스(sonjari/sonjari · 빌드 경로 · 사용자 이름 지운 판)에서 받는다.
    assert mac["source"] == {"github_release": "sonjari/sonjari", "tag": "trellis-cpp-metal-v0.8.1",
                             "asset": "trellis-cpp-metal-macos-arm64.zip"}
    assert mac["sha256"] == "dc387a43b2ac9ef97ebc38d485b01d1672f27bb05ce9fb20974468056196e28d"


def test_the_leftover_route_exists() -> None:
    source = (REPO / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    assert '"/v1/packs/{pack_id}/models/leftovers/remove"' in source


def test_unzip_restores_the_executable_bit_from_the_zip(tmp_path, monkeypatch):
    """맥 실행기(trellis-cli)는 zip 에 적힌 실행 권한이 살아나야 돈다 — 파이썬 extractall 은 그것을 버린다(11-14)."""
    import zipfile as _zip

    from alture_jarvis import pack_models as pm

    archive = tmp_path / "bin.zip"
    with _zip.ZipFile(archive, "w") as zf:
        exe = _zip.ZipInfo("trellis-cpp-metal/trellis-cli")
        exe.external_attr = (0o100755 << 16)
        zf.writestr(exe, b"\xcf\xfa\xed\xfe")
        lic = _zip.ZipInfo("trellis-cpp-metal/LICENSE.txt")
        lic.external_attr = (0o100644 << 16)
        zf.writestr(lic, b"MIT")
    calls = {}
    real_chmod = pm.os.chmod
    monkeypatch.setattr(pm.os, "chmod", lambda path, mode: calls.__setitem__(str(path).replace("\\", "/").split("/")[-1], mode) or real_chmod(path, mode))
    pm.ModelFetcher._unzip(archive, tmp_path / "out")
    assert calls.get("trellis-cli") == 0o755
    assert calls.get("LICENSE.txt") == 0o644
