from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.mission import build_mission, inject_mission_context, resume_goal
from alture_jarvis.plan import extract


def test_mission_records_done_when_remaining_and_last_verified_step() -> None:
    prompt = "위시켓과 크몽에서 공고를 4개 읽고 메일 보내줘"
    steps = [
        {
            "step": 1,
            "tool": "browser_extract",
            "ok": True,
            "evidence": {"url": "https://www.wishket.com/project/1"},
        }
    ]

    mission = build_mission(
        prompt=prompt,
        requirements=extract(prompt, has_named_source=True),
        sources=["https://www.wishket.com/project/1"],
        steps=steps,
        fingerprints={"browser_extract:{}": 1},
    )

    assert mission["goal"] == prompt
    assert "4개 이상 직접 열어 읽기" in mission["done_when"]
    assert "크몽에서 하기" in mission["remaining"]
    assert "메일 발송" in mission["remaining"]
    assert mission["last_verified_step"] == 1
    assert mission["attempt_budget"]["used"] == {"browser_extract:{}": 1}


def test_resume_uses_the_saved_goal_and_replaces_old_mission_context() -> None:
    mission = {
        "goal": "세 사이트에서 네 건을 읽어라",
        "done_when": ["4개 읽기"],
        "remaining": ["크몽에서 하기"],
        "invariants": ["성공한 쓰기를 반복하지 않는다"],
        "last_verified_step": 7,
    }
    messages = [
        {"role": "system", "content": "원래 시스템"},
        {"role": "system", "content": "[MISSION CHECKPOINT]\n낡은 내용"},
    ]

    restored = inject_mission_context(messages, mission)

    assert resume_goal("이어가", {"prompt": "옛 목표", "mission": mission}) == mission["goal"]
    assert sum("[MISSION CHECKPOINT]" in item["content"] for item in restored) == 1
    assert "크몽에서 하기" in restored[-1]["content"]
    assert "마지막 검증 단계: 7" in restored[-1]["content"]


def test_checkpoint_json_adds_mission_without_a_database_migration(tmp_path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
    )
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.config = config
    agent.store = store
    prompt = "위시켓에서 공고 2개를 읽어줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})

    agent._save_checkpoint_state(
        job_id=job["id"],
        prompt=prompt,
        origin="chat",
        messages=[{"role": "system", "content": "system"}],
        steps=[],
        fingerprints={},
        evidence_urls=[],
        elapsed_sec=3.0,
        thinking_chars=0,
        continuation_count=0,
        last_action_ids={},
    )

    checkpoint = store.get_agent_checkpoint(job["id"])
    assert checkpoint is not None
    assert checkpoint["mission"]["goal"] == prompt
    assert checkpoint["mission"]["remaining"] == [
        "2개 이상 직접 열어 읽기",
        "위시켓에서 하기",
    ]


def test_old_checkpoint_without_mission_keeps_working() -> None:
    checkpoint = {"prompt": "원래 저장된 목표"}

    assert resume_goal("재개 요청", checkpoint) == "원래 저장된 목표"
    assert inject_mission_context([{"role": "system", "content": "system"}], {}) == [
        {"role": "system", "content": "system"}
    ]
