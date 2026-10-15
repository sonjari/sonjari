from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.code_scout import (
    CodeScout,
    format_scout_handoff,
    normalize_scout_report,
    parse_scout_json,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult


def test_scout_report_rejects_hallucinated_paths_and_keeps_ranked_fallback() -> None:
    report = normalize_scout_report(
        {
            "priority_files": ["made/up.py"],
            "hypotheses": ["인증 헤더 조립을 확인해야 한다"],
            "next_reads": ["src/auth.py", "outside.py"],
            "risks": ["테스트 누락"],
        },
        ["src/auth.py", "tests/test_auth.py"],
    )

    assert report["priority_files"] == ["src/auth.py", "tests/test_auth.py"]
    assert report["next_reads"] == ["src/auth.py"]
    assert "made/up.py" not in format_scout_handoff(report)


def test_scout_json_accepts_fence_but_rejects_non_object() -> None:
    parsed = parse_scout_json(
        "```json\n{\"priority_files\": [], \"hypotheses\": [], "
        "\"next_reads\": [], \"risks\": []}\n```"
    )
    assert parsed["priority_files"] == []
    with pytest.raises(ValueError, match="object_required"):
        parse_scout_json("[1, 2, 3]")


def test_code_agent_receives_scout_handoff_after_forced_index(tmp_path) -> None:
    class Tools:
        names = {"local_index_codebase"}
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": "local_index_codebase",
                    "description": "index",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        def __init__(self) -> None:
            self.authorized = ""

        def authorize_code_workspace(self, job_id: str, root: str) -> None:
            self.authorized = f"{job_id}:{root}"

    class Gateway:
        def execute(self, name, arguments, *, job_id=""):
            assert name == "local_index_codebase"
            return ToolResult(
                True,
                name,
                result={
                    "index": {"total_files": 2},
                    "repo_map": {
                        "matches": [
                            {"path": "src/app.py"},
                            {"path": "tests/test_app.py"},
                        ]
                    },
                },
            )

    class Scout:
        enabled = True

        def analyze(self, task, index_result):
            assert task == "app 버그를 분석해줘"
            assert index_result["index"]["total_files"] == 2
            return {
                "priority_files": ["src/app.py"],
                "hypotheses": ["상태 분기 확인"],
                "next_reads": ["tests/test_app.py"],
                "risks": ["회귀"],
                "model": "qwen3.5:9b",
                "candidate_count": 2,
                "elapsed_sec": 0.01,
            }

    class Model:
        def __init__(self) -> None:
            self.messages = []

        def chat_messages(self, messages, **kwargs):
            self.messages = list(messages)
            assert any(
                "[Qwen3.5 읽기 전용 정찰기 인수인계]" in str(row.get("content"))
                and "src/app.py" in str(row.get("content"))
                for row in messages
            )
            return {"role": "assistant", "content": "색인과 정찰 인수인계를 확인했습니다."}

    class Browser:
        def status(self):
            return {"started": False}

    root = tmp_path / "repo"
    root.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_task_timeout_sec=30,
    )
    store = JobStore(tmp_path / "jarvis.db")
    tools = Tools()
    model = Model()
    agent = BrowserAgent(
        config,
        model,
        Gateway(),
        Browser(),
        tools,
        store,
        EventBus(),
        code_scout=Scout(),
    )
    job = store.create_job("chat", "code", {"prompt": "app 버그를 분석해줘"})
    store.claim_next()

    result = agent.run(
        "app 버그를 분석해줘",
        job_id=job["id"],
        origin="chat",
        model_role="code",
        required_local_root=str(root),
        auto_continue_budget=True,
    )

    assert result.answer.startswith("색인과 정찰")
    assert tools.authorized.startswith(job["id"])


def test_scout_skips_new_model_load_when_3060_has_too_little_vram(tmp_path, monkeypatch) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        code_scout_min_free_vram_mb=8000,
    )
    scout = CodeScout(config)
    monkeypatch.setattr(scout, "_model_is_loaded", lambda client: False)
    monkeypatch.setattr(scout, "_free_vram_mb", lambda: 7200)

    with pytest.raises(RuntimeError, match="code_scout_vram_guard:7200<8000"):
        scout._ensure_capacity(object())
