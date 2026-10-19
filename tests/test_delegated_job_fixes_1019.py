"""맡기기 판 75aaa296(벤치 스크립트 24개에 측정 표시)에서 나온 손자리 버그 넷 (2026-10-19 밤).

1. 허술한 확인 명령을 **설명 글에 낱말을 끼워 넣어** 통과시켰다 → 가지 요약에 「설명 글 · 주석만 바뀐 파일」을 이름으로 싣는다.
2. 작업 폴더 끝(`tools/alture-jarvis`)을 경로에 한 번 더 붙여 엉뚱한 자리에 사본을 남겼다 → 도구 앞에서 접는다.
3. 코드 판인데 진행 문구가 18분 내내 「아직 읽은 본문 없음」 → 연 파일 · 고친 파일을 센다.
4. 파일 23개를 하나씩 23걸음에 읽었다(걸음당 약 11초) → 여러 파일을 한 걸음에 읽고, grep 이 그 인자를 만들어 준다.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegated_branch import finish, prepare, wording_only
from alture_jarvis.delegation import summarize_job
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.promise_gate import anchor_relative_paths, collapse_doubled_root

_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git 이 없는 환경")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.example", *args], capture_output=True, check=True)
    return done.stdout.decode("utf-8", "replace").strip()


# ── 1. 설명 글만 바뀐 파일 ─────────────────────────────────────────────

_SCRIPT = '''"""조회만 하는 스크립트."""
import json

def main():
    # 결과를 본다
    return json.dumps({"ok": True})
'''


@_needs_git
def test_a_docstring_only_change_is_named_and_a_real_change_is_not(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "bench").mkdir(parents=True)
    (root / "bench" / "look.py").write_text(_SCRIPT, encoding="utf-8")
    (root / "bench" / "start.py").write_text(_SCRIPT, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    made = prepare(str(root), home=tmp_path / "home", clock=lambda: 3_000)
    work = Path(made["worktree"])
    # 시험만 맞춘 변경: 설명 글과 주석에 낱말만 넣는다
    (work / "bench" / "look.py").write_text(
        _SCRIPT.replace("조회만 하는 스크립트.", "조회만 하는 스크립트 — measurement 와 무관.").replace("# 결과를 본다", "# measurement 없음"),
        encoding="utf-8",
    )
    # 진짜 변경: 요청 본문에 키가 들어간다
    (work / "bench" / "start.py").write_text(_SCRIPT.replace('{"ok": True}', '{"ok": True, "measurement": True}'), encoding="utf-8")
    done = finish(str(work), made["base"], message="t")
    assert done["changed_count"] == 2
    assert done["wording_only"] == ["bench/look.py"]


@_needs_git
def test_compiled_leftovers_are_not_committed_to_the_branch(tmp_path: Path) -> None:
    # 2026-10-20 dd6c008c: `.gitignore` 없는 저장소에서 바뀐 파일 173개 중 130여 개가 `__pycache__/*.pyc` 였다.
    root = tmp_path / "repo"
    (root / "bench").mkdir(parents=True)
    (root / "bench" / "s.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    made = prepare(str(root), home=tmp_path / "home", clock=lambda: 4_000)
    work = Path(made["worktree"])
    (work / "bench" / "s.py").write_text("X = 2\n", encoding="utf-8")
    (work / "bench" / "__pycache__").mkdir()
    (work / "bench" / "__pycache__" / "s.cpython-311.pyc").write_bytes(b"\x00\x01")
    (work / ".pytest_cache").mkdir()
    (work / ".pytest_cache" / "README.md").write_text("x", encoding="utf-8")
    done = finish(str(work), made["base"], message="t")
    assert [item["path"] for item in done["changed"]] == ["bench/s.py"]


def test_a_broken_file_is_never_called_wording_only() -> None:
    from alture_jarvis.delegated_branch import _code_shape

    assert _code_shape("def f(:\n") is None
    assert _code_shape('"""a"""\nX = 1\n') == _code_shape('"""b"""\nX = 1  # c\n')
    assert _code_shape("X = 1\n") != _code_shape("X = 2\n")


def test_the_caller_is_told_which_files_only_changed_wording() -> None:
    job = {"id": "j1", "status": "completed", "payload": {"prompt": "고쳐줘"}, "result": {
        "answer": "고쳤습니다.", "completion_state": "complete",
        "agent_trace": {"steps": [{"tool": "local_apply_edit", "ok": True, "arguments": {}}], "verification": {}},
        "delegated": {
            "repo": "C:/work/repo", "branch": "sonjari/task-1", "worktree": "C:/out/repo-1", "base": "abcdef1234567890",
            "changed": [{"status": "M", "path": "bench/look.py"}, {"status": "M", "path": "bench/start.py"}],
            "changed_count": 2, "stat": "2 files changed", "wording_only": ["bench/look.py"],
            "take_home": {"review": "git diff", "take": "git cherry-pick -n", "discard": "git ..."},
        },
    }}
    summary = summarize_job(job)
    assert summary["branch"]["wording_only"] == ["bench/look.py"]
    assert any("설명 글 · 주석만" in note for note in summary["review_notes"])


def test_no_wording_note_when_every_change_is_code() -> None:
    job = {"id": "j1", "status": "completed", "payload": {"prompt": "고쳐줘"}, "result": {
        "answer": "고쳤습니다.", "completion_state": "complete",
        "agent_trace": {"steps": [{"tool": "local_apply_edit", "ok": True, "arguments": {}}], "verification": {}},
        "delegated": {"repo": "r", "branch": "b", "worktree": "w", "base": "x", "changed": [{"status": "M", "path": "a.py"}],
                      "changed_count": 1, "stat": "", "wording_only": [], "take_home": {}},
    }}
    summary = summarize_job(job)
    assert "wording_only" not in summary["branch"]
    assert not any("설명 글" in note for note in summary.get("review_notes") or [])


# ── 2. 겹친 경로 접기 ─────────────────────────────────────────────

def test_the_root_tail_written_twice_is_folded(tmp_path: Path) -> None:
    root = tmp_path / "repo-1" / "tools" / "alture-jarvis"
    (root / "tests").mkdir(parents=True)
    doubled = root / "tools" / "alture-jarvis" / "tests" / "test_x.py"
    folded = collapse_doubled_root({"path": str(doubled), "content": "x"}, str(root))
    assert folded == {"path": str(root / "tests" / "test_x.py"), "content": "x"}


def test_three_times_is_folded_too(tmp_path: Path) -> None:
    root = tmp_path / "w" / "tools" / "alture-jarvis"
    root.mkdir(parents=True)
    tripled = root / "tools" / "alture-jarvis" / "tools" / "alture-jarvis" / "tests" / "t.py"
    assert collapse_doubled_root({"path": str(tripled)}, str(root)) == {"path": str(root / "tests" / "t.py")}


def test_a_real_folder_with_the_same_name_is_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "proj" / "src"
    (root / "src").mkdir(parents=True)  # 저장소에 정말 src/src 가 있다
    path = str(root / "src" / "a.py")
    assert collapse_doubled_root({"path": path}, str(root)) is None


def test_a_new_python_package_with_the_project_name_is_not_folded(tmp_path: Path) -> None:
    root = tmp_path / "calc"
    root.mkdir()
    new_package = str(root / "calc" / "__init__.py")  # 꾸러미를 새로 만든다 — 접으면 안 된다
    assert collapse_doubled_root({"path": new_package, "content": ""}, str(root)) is None


def test_one_doubled_name_is_folded_only_onto_a_file_that_exists(tmp_path: Path) -> None:
    root = tmp_path / "bench" / "poker"
    root.mkdir(parents=True)
    (root / "INSTRUCTIONS.md").write_text("x", encoding="utf-8")
    got = collapse_doubled_root({"path": str(root / "poker" / "INSTRUCTIONS.md")}, str(root))
    assert got == {"path": str(root / "INSTRUCTIONS.md")}


def test_a_relative_repo_path_is_anchored_then_folded(tmp_path: Path) -> None:
    root = tmp_path / "repo-2" / "tools" / "alture-jarvis"
    (root / "tests").mkdir(parents=True)
    anchored = anchor_relative_paths({"path": "tools/alture-jarvis/tests/t.py"}, str(root))
    assert collapse_doubled_root(anchored, str(root)) == {"path": str(root / "tests" / "t.py")}


def test_paths_items_are_folded_and_outside_paths_are_untouched(tmp_path: Path) -> None:
    root = tmp_path / "r" / "tools" / "alture-jarvis"
    root.mkdir(parents=True)
    outside = str(tmp_path / "elsewhere" / "tools" / "alture-jarvis" / "x.py")
    got = collapse_doubled_root({"paths": [{"path": str(root / "tools" / "alture-jarvis" / "a.py"), "line_start": 3}, outside]}, str(root))
    assert got == {"paths": [{"path": str(root / "a.py"), "line_start": 3}, outside]}


# ── 3. 코드 판 진행 문구 ─────────────────────────────────────────────

def _read(path: str) -> dict:
    return {"tool": "local_read_text_file", "ok": True, "arguments": {"path": path}}


def _edit(path: str) -> dict:
    return {"tool": "local_apply_edit", "ok": True, "arguments": {"path": path, "old": "a", "new": "b"}}


def test_a_code_job_reports_files_not_web_pages() -> None:
    steps = [_read("C:/w/a.py"), _read("C:/w/b.py"), _edit("C:/w/a.py"), _edit("C:/w/c.py"),
             {"tool": "local_read_text_file", "ok": True, "arguments": {"paths": [{"path": "C:/w/d.py"}, "C:/w/e.py"]}}]
    line = BrowserAgent._interim_report(steps=steps, plan_results=[], remaining_sec=180, code=True)
    assert "아직 읽은 본문 없음" not in line
    assert "파일 5개 읽음 · 2개 고침" in line  # a b c d e — 고친 c 는 읽은 것으로도 센다
    assert line.endswith("3분 남음")


def test_a_code_job_before_any_file_says_so() -> None:
    line = BrowserAgent._interim_report(steps=[], plan_results=[], remaining_sec=50, code=True)
    assert "아직 연 파일 없음" in line


def test_a_web_job_keeps_its_old_line() -> None:
    line = BrowserAgent._interim_report(steps=[], plan_results=[], remaining_sec=50)
    assert "아직 읽은 본문 없음" in line


def test_the_new_lines_have_english() -> None:
    import json

    table = json.loads((Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "ui_i18n_en.json").read_text(encoding="utf-8"))
    for key in ("파일 {0}개 읽음 · {1}개 고침", "파일 {0}개 읽음", "아직 연 파일 없음"):
        assert table.get(key)


# ── 4. 여러 파일 한 걸음에 ─────────────────────────────────────────────

def _computer(tmp_path: Path) -> LocalComputerTools:
    return LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))


def _bench(tmp_path: Path, count: int) -> list[Path]:
    files = []
    for n in range(count):
        target = tmp_path / "bench" / f"s{n:02d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = [f"# 스크립트 {n}"] + [f"x{i} = {i}" for i in range(30)]
        body.insert(20, '    job = call("/v1/chat", {"prompt": P})')
        target.write_text("\n".join(body) + "\n", encoding="utf-8")
        files.append(target)
    return files


def test_many_files_are_read_in_one_call_with_their_ranges(tmp_path: Path) -> None:
    a, b, c = _bench(tmp_path, 3)
    result = _computer(tmp_path).read_text_file({"paths": [{"path": str(a), "line_start": 18, "line_end": 23}, str(b), {"path": str(c), "line_start": 1, "line_end": 2}]})
    assert result["file_count"] == 3
    assert result["path"] == str(a)
    assert '/v1/chat' in result["content"]
    assert f"=== {a} (줄 18–23)" in result["content"] and f"=== {c} (줄 1–2)" in result["content"]
    assert [entry["line_start"] for entry in result["files"]] == [18, 1, 1]


def test_one_bad_file_does_not_sink_the_others(tmp_path: Path) -> None:
    (a,) = _bench(tmp_path, 1)
    outside = tmp_path.parent / "not_allowed_1019.py"
    result = _computer(tmp_path).read_text_file({"paths": [str(outside), str(a)]})
    assert result["file_count"] == 1
    assert [entry["ok"] for entry in result["files"]] == [False, True]
    assert "못 읽음" in result["content"]


def test_more_than_twelve_files_are_cut_with_a_way_on(tmp_path: Path) -> None:
    files = _bench(tmp_path, 14)
    result = _computer(tmp_path).read_text_file({"paths": [str(f) for f in files]})
    assert result["file_count"] == 12
    assert "남은 2개" in result["instruction"]


def test_no_path_at_all_is_refused_with_an_example(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="paths_required"):
        _computer(tmp_path).read_text_file({"paths": [{}]})


def test_grep_over_many_files_hands_back_a_ready_read_all(tmp_path: Path) -> None:
    _bench(tmp_path, 14)
    tools = _computer(tmp_path)
    found = tools.grep_files({"path": str(tmp_path / "bench"), "pattern": "/v1/chat", "max_results": 100})
    assert found["count"] == 14
    batch = found["read_all"]["paths"]
    assert len(batch) == 12 and len(found["read_all_more"][0]["paths"]) == 2
    assert batch[0]["line_start"] == 21 - 3 and batch[0]["line_end"] == 21 + 15
    # 그대로 넣으면 읽힌다
    read = tools.read_text_file(found["read_all"])
    assert read["file_count"] == 12 and read["content"].count("/v1/chat") == 12


def test_grep_in_one_file_adds_nothing(tmp_path: Path) -> None:
    _bench(tmp_path, 1)
    found = _computer(tmp_path).grep_files({"path": str(tmp_path / "bench"), "pattern": "/v1/chat"})
    assert "read_all" not in found


def test_the_schema_offers_paths_and_does_not_demand_path(tmp_path: Path) -> None:
    definitions = _computer(tmp_path).ollama_tools
    read = next(d for d in definitions if (d.get("function") or d).get("name") == "local_read_text_file")
    spec = (read.get("function") or read)["parameters"]
    assert "paths" in spec["properties"]
    assert "path" not in spec.get("required", [])
