"""첫 실행 3단계 — 지침 가져오기 (전략안 §43, P4).

지시서 「끝났다고 말하려면」의 시험을 그대로 옮겼다:

    - 정해진 경로만 읽는다 (목록 밖 파일을 안 여는지)
    - config.toml · Cursor settings.json 은 내용을 안 읽는다
    - 확인 전에는 아무것도 저장 안 된다
    - 바뀐 파일 알림 · 지우기

★ 가짜 비밀은 실행 중에 조립한다(`test_secret_scrub.py` 와 같은 이유).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.instruction_import import MAX_BYTES, InstructionImportService

FAKE_KEY = "sk-" + "ant-api03-" + "Q7fK2mZp9Lx4Rt8Vb3Nc6Hy1Wd5Js0Ge" + "Aa11Bb22"


class _Reader:
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def __call__(self, path: Path) -> bytes:
        self.opened.append(Path(path))
        return Path(path).read_bytes()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 바이트로 쓴다 — 윈도우의 write_text 는 \n 을 \r\n 으로 바꿔 비교를 흔든다.
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    project = tmp_path / "project"
    _write(home / ".claude" / "CLAUDE.md", f"# 전역 지침\n한국어로 답한다.\n검증 키: {FAKE_KEY}\n")
    _write(home / ".claude" / "settings.json", '{"not": "a list member"}')
    _write(home / ".codex" / "AGENTS.md", "# 코덱스 지침\n작게 고친다.\n")
    _write(home / ".codex" / "config.toml", f'api_key = "{FAKE_KEY}"\n')
    _write(home / ".codex" / "auth.json", "{}")
    _write(appdata / "Cursor" / "User" / "settings.json", "{}")
    _write(project / "CLAUDE.md", "# 프로젝트 지침\n문의 someone@example.com\n")
    _write(project / "AGENTS.md", "# 프로젝트 코덱스\n")
    _write(project / ".cursorrules", "커서 규칙\n")
    _write(project / ".cursor" / "rules" / "00_never.mdc", "하지 말 것\n")
    _write(project / ".cursor" / "rules" / "notes.txt", "목록 밖\n")
    _write(project / ".cursor" / "rules" / "sub" / "deep.mdc", "하위 폴더 — 목록 밖\n")
    _write(project / ".env", f"TOKEN={FAKE_KEY}\n")
    monkeypatch.setattr(InstructionImportService, "_home", staticmethod(lambda: home))
    monkeypatch.setattr(InstructionImportService, "_appdata", staticmethod(lambda: appdata))
    reader = _Reader()
    service = InstructionImportService(tmp_path / "data" / "jarvis.db", read_bytes=reader)
    return service, reader, home, appdata, project


EXPECTED_IDS = {
    "claude:global", "codex:global", "codex:config", "cursor:settings",
    "claude:project", "codex:project", "cursor:cursorrules", "cursor:rule:00_never.mdc",
}


# ── 정해진 경로만 ────────────────────────────────────────────────────────────
def test_scan_lists_only_the_fixed_paths_and_reads_nothing(world) -> None:
    service, reader, *_ , project = world
    result = service.scan(str(project))
    assert {c["id"] for c in result["candidates"]} == EXPECTED_IDS
    assert reader.opened == []  # 찾기는 stat 만


def test_preview_opens_only_listed_files(world) -> None:
    service, reader, home, appdata, project = world
    ids = sorted(EXPECTED_IDS) + ["../.env", "project:.env", str(project / ".env"), "cursor:rule:sub/deep.mdc"]
    result = service.preview(str(project), ids)
    allowed = {
        home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md",
        project / "CLAUDE.md", project / "AGENTS.md", project / ".cursorrules",
        project / ".cursor" / "rules" / "00_never.mdc",
    }
    assert set(reader.opened) == allowed
    errors = {item["id"]: item.get("error") for item in result["items"]}
    for bogus in ("../.env", "project:.env", str(project / ".env"), "cursor:rule:sub/deep.mdc"):
        assert errors[bogus] == "not_in_list"


def test_settings_files_are_never_opened(world) -> None:
    service, reader, home, appdata, project = world
    result = service.preview(str(project), ["codex:config", "cursor:settings"])
    assert reader.opened == []
    assert [item["error"] for item in result["items"]] == ["settings_file", "settings_file"]
    # 넣기로도 못 연다.
    assert service.commit(str(project), [{"id": "codex:config", "sha256": "x"}])["saved"] == []
    assert reader.opened == []


def test_a_project_inside_a_sensitive_folder_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "home" / ".ssh"
    _write(project / "CLAUDE.md", "비밀 폴더 안\n")
    monkeypatch.setattr(InstructionImportService, "_home", staticmethod(lambda: home))
    monkeypatch.setattr(InstructionImportService, "_appdata", staticmethod(lambda: None))
    reader = _Reader()
    service = InstructionImportService(tmp_path / "db.sqlite", read_bytes=reader)
    item = service.preview(str(project), ["claude:project"])["items"][0]
    assert item["error"] == "sensitive_location" and reader.opened == []


# ── 미리보기: 걷은 결과만 ─────────────────────────────────────────────────────
def test_preview_shows_scrubbed_segments_and_never_the_key(world) -> None:
    service, _, _, _, project = world
    item = service.preview(str(project), ["claude:global"])["items"][0]
    assert item["secret_total"] == 1 and item["secrets"] == {"API 키": 1}
    assert FAKE_KEY not in str(item)
    assert len(item["sha256"]) == 64


def test_contacts_are_shown_not_removed_by_default(world) -> None:
    service, _, _, _, project = world
    item = service.preview(str(project), ["claude:project"])["items"][0]
    assert item["contact_total"] == 1 and item["secret_total"] == 0


# ── 확인 전에는 저장 안 함 ─────────────────────────────────────────────────────
def test_nothing_is_saved_before_commit(world) -> None:
    service, _, _, _, project = world
    service.preview(str(project), sorted(EXPECTED_IDS), {"tool": "manus", "text": "마누스 지침"})
    assert service.list()["count"] == 0


def test_commit_saves_scrubbed_text_with_source_hash_and_time(world) -> None:
    service, _, home, _, project = world
    preview = service.preview(str(project), ["claude:global"])["items"][0]
    result = service.commit(str(project), [{"id": "claude:global", "sha256": preview["sha256"]}])
    assert result["ok"] and result["saved"][0]["secret_total"] == 1
    row = service.list()["items"][0]
    assert row["source_path"] == str(home / ".claude" / "CLAUDE.md")
    assert row["tool"] == "claude" and row["imported_at"] > 0 and row["status"] == "same"
    assert FAKE_KEY not in row["text"] and "[비밀 걷어 냄: API 키]" in row["text"]


def test_a_file_changed_after_preview_is_not_saved(world) -> None:
    service, _, home, _, project = world
    preview = service.preview(str(project), ["claude:global"])["items"][0]
    _write(home / ".claude" / "CLAUDE.md", "미리보기 뒤에 바뀜\n")
    result = service.commit(str(project), [{"id": "claude:global", "sha256": preview["sha256"]}])
    assert result["refused"][0]["error"] == "changed_since_preview"
    assert service.list()["count"] == 0


def test_paste_is_previewed_then_committed(world) -> None:
    service, _, _, _, project = world
    paste = {"tool": "manus", "text": f"마누스에 적어 둔 지침\n{FAKE_KEY}"}
    item = service.preview("", [], paste)["items"][0]
    assert item["secret_total"] == 1
    saved = service.commit("", [], {**paste, "sha256": item["sha256"]})
    assert saved["ok"]
    row = service.list()["items"][0]
    assert row["scope"] == "paste" and FAKE_KEY not in row["text"]
    assert service.commit("", [], {"tool": "chatgpt", "text": "x", "sha256": ""})["refused"][0]["error"] == "unknown_tool"


def test_too_large_is_refused_not_cut(world) -> None:
    service, reader, home, _, project = world
    _write(home / ".codex" / "AGENTS.md", "가" * (MAX_BYTES // 2))  # 3바이트 × 절반 > 상한
    item = service.preview(str(project), ["codex:global"])["items"][0]
    assert item["error"] == "too_large" and reader.opened == []


# ── 바뀜 알림 · 지우기 ──────────────────────────────────────────────────────────
def test_changed_and_missing_are_reported_without_auto_update(world) -> None:
    service, _, home, _, project = world
    preview = service.preview(str(project), ["codex:global"])["items"][0]
    service.commit(str(project), [{"id": "codex:global", "sha256": preview["sha256"]}])
    _write(home / ".codex" / "AGENTS.md", "# 고친 지침\n")
    assert service.list()["items"][0]["status"] == "changed"
    assert service.list()["items"][0]["text"].startswith("# 코덱스 지침")  # 자동 갱신 없음
    scanned = {c["id"]: c for c in service.scan(str(project))["candidates"]}
    assert scanned["codex:global"]["imported"]["status"] == "changed"
    (home / ".codex" / "AGENTS.md").unlink()
    assert service.list()["items"][0]["status"] == "missing"


def test_reimport_replaces_the_same_source(world) -> None:
    service, _, home, _, project = world
    for text in ("첫 판\n", "둘째 판\n"):
        _write(home / ".codex" / "AGENTS.md", text)
        sha = service.preview(str(project), ["codex:global"])["items"][0]["sha256"]
        service.commit(str(project), [{"id": "codex:global", "sha256": sha}])
    rows = service.list()["items"]
    assert len(rows) == 1 and rows[0]["text"] == "둘째 판\n" and rows[0]["status"] == "same"


def test_remove_one(world) -> None:
    service, _, _, _, project = world
    for cid in ("codex:global", "claude:project"):
        sha = service.preview(str(project), [cid])["items"][0]["sha256"]
        service.commit(str(project), [{"id": cid, "sha256": sha}])
    first = service.list()["items"][0]["import_id"]
    assert service.remove(first)["ok"]
    assert service.list()["count"] == 1
    assert service.remove(first) == {"ok": False, "error": "not_found"}


def test_a_bad_project_folder_says_so(world) -> None:
    service, *_ = world
    assert service.scan("상대/경로")["project_error"] == "project_not_found"


# ── HTTP ──────────────────────────────────────────────────────────────────────
def test_import_routes_require_the_token_and_round_trip(world, tmp_path: Path) -> None:
    _, _, _, _, project = world
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    auth = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.get("/v1/setup/import/scan").status_code == 401
        scan = client.get("/v1/setup/import/scan", params={"project": str(project)}, headers=auth).json()
        assert {c["id"] for c in scan["candidates"]} == EXPECTED_IDS
        preview = client.post("/v1/setup/import/preview", headers=auth,
                              json={"project": str(project), "ids": ["claude:global"]}).json()["items"][0]
        assert FAKE_KEY not in str(preview)
        commit = client.post("/v1/setup/import/commit", headers=auth, json={
            "project": str(project), "items": [{"id": "claude:global", "sha256": preview["sha256"]}]}).json()
        assert commit["ok"]
        listed = client.get("/v1/setup/import/list", headers=auth).json()
        assert listed["count"] == 1
        removed = client.post("/v1/setup/import/remove", headers=auth,
                              json={"import_id": listed["items"][0]["import_id"]}).json()
        assert removed["ok"]


def test_only_the_two_instruction_files_escape_the_secret_folders(tmp_path: Path) -> None:
    """★ `.claude`·`.codex` 는 통째로 비밀이다 (2026-09-20). 지침 파일 **둘만** 예외다.

    그 폴더에는 대화 원문과 토큰이 들어 있다. 예외를 「폴더 통째로」로 풀면 이 기능이
    곧 토큰 유출구가 된다 — 부모 폴더와 이름이 정확히 맞는 것만 열린다.
    """
    from alture_jarvis.instruction_import import _is_sensitive

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()

    # 읽어야 하는 둘
    assert _is_sensitive(home / ".claude" / "CLAUDE.md") is False
    assert _is_sensitive(home / ".codex" / "AGENTS.md") is False

    # 같은 폴더의 나머지는 전부 막힌다
    for blocked in (
        home / ".claude" / "settings.json",
        home / ".claude" / "history.jsonl",
        home / ".codex" / "auth.json",
        home / ".codex" / "config.toml",
        home / ".claude" / "projects" / "CLAUDE.md",  # 한 층 깊으면 예외 아님
    ):
        assert _is_sensitive(blocked) is True, f"{blocked} 이 열렸다"
