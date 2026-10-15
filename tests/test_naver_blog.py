from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.naver_blog import NaverBlogTools
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


class FakeBrowser:
    """Stands in for BrowserWorker: only structurally satisfies
    execute(action, arguments) -> evidence dict, exactly what test_agent.py's
    FakeGateway does for the agent loop. No real Playwright involved, so the
    safety logic under test (origin lock, commit-time re-verification) is
    exercised without needing a live browser."""

    def __init__(self, url: str = "https://blog.naver.com/GoBlogWrite.naver") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.url = url
        self.overrides: dict[str, list[dict[str, Any]]] = {}
        self.account = "test-account"
        self.title_text = ""
        # Default to a page that actually showed the save/publish landed. The
        # unverified case is a separate, explicit setting because that is the
        # state the 2026-08-03 incident was in.
        self.save_verified = True
        self.body_verified = True
        self.publish_verified = True
        self.published_url = "https://blog.naver.com/test-account/223999999"

    def queue(self, action: str, response: dict[str, Any]) -> None:
        self.overrides.setdefault(action, []).append(response)

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, dict(arguments)))
        queued = self.overrides.get(action)
        if queued:
            return queued.pop(0)
        if action == "naver_blog_read_account":
            return {"action": action, "url": self.url, "account": self.account, "title_text": self.title_text}
        if action == "naver_blog_capture_screen":
            return {"action": action, "url": self.url, "screenshot_path": "/tmp/preview.png"}
        if action == "naver_blog_click_save_draft":
            return {
                "action": action,
                "url": self.url,
                "saved_verified": self.save_verified,
                "saved_evidence": "draft_count:0->1" if self.save_verified else "",
                "draft_count_before": 0,
                "draft_count_after": 1 if self.save_verified else 0,
            }
        if action == "naver_blog_fill_editor":
            # 넣은 본문이 화면에 그대로 남았는지. 2026-08-05 에 순서가 뒤섞인 채로
            # 성공이 올라온 뒤부터, 이 판정이 위층까지 올라와야 한다.
            return {
                "action": action,
                "url": self.url,
                "verified": self.body_verified,
                "body_length": 100,
                "body_chars_landed": 100 if self.body_verified else 40,
                "body_mismatch": "" if self.body_verified else "넣은 본문과 화면의 본문이 다릅니다",
            }
        if action == "naver_blog_click_publish":
            return {
                "action": action,
                "url": self.url,
                "published_verified": self.publish_verified,
                "url_before": self.url,
                "url_after": self.published_url if self.publish_verified else self.url,
            }
        return {"action": action, "url": self.url, "title": ""}

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def count(self, action: str) -> int:
        return sum(1 for name, _ in self.calls if name == action)


def _config(tmp_path: Path) -> JarvisConfig:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        naver_blog_enabled=True,
        external_action_ttl_sec=300,
    )


def _tools(tmp_path: Path, config: JarvisConfig, browser: FakeBrowser | None = None):
    browser = browser or FakeBrowser()
    local_computer = LocalComputerTools(config)
    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    tools = NaverBlogTools(config, browser, local_computer, actions)
    return tools, browser, actions


def test_prepare_post_requires_title_and_body(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    with pytest.raises(ValueError, match="title_required"):
        tools.prepare_post({"title": "", "body": "본문"})
    with pytest.raises(ValueError, match="body_required"):
        tools.prepare_post({"title": "제목", "body": ""})
    assert browser.calls == []


def test_prepare_post_rejects_invalid_visibility(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, _, _ = _tools(tmp_path, config)
    with pytest.raises(ValueError, match="visibility_invalid"):
        tools.prepare_post({"title": "제목", "body": "본문", "visibility": "everyone"})


def test_prepare_post_blocks_image_outside_allowed_root(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, _, _ = _tools(tmp_path, config)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"fake-image-bytes")
    with pytest.raises(PermissionError, match="outside"):
        tools.prepare_post({"title": "제목", "body": "본문", "images": [str(outside)]})


def test_prepare_post_blocks_unsupported_image_format(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, _, _ = _tools(tmp_path, config)
    allowed_root = Path(config.local_file_allowed_roots)
    bad_file = allowed_root / "note.txt"
    bad_file.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported_format"):
        tools.prepare_post({"title": "제목", "body": "본문", "images": [str(bad_file)]})


def test_prepare_post_blocks_oversized_image(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.naver_blog_image_max_bytes = 10
    tools, _, _ = _tools(tmp_path, config)
    allowed_root = Path(config.local_file_allowed_roots)
    image = allowed_root / "photo.jpg"
    image.write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="too_large"):
        tools.prepare_post({"title": "제목", "body": "본문", "images": [str(image)]})


def test_prepare_post_succeeds_without_touching_browser(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    result = tools.prepare_post({"title": "제목", "body": "본문", "tags": ["a", "b"]})
    assert result["action_id"]
    assert result["requires_approval"] is False
    assert browser.calls == []
    action = actions.get_prepared_action(result["action_id"])
    assert action["status"] == "prepared"
    assert action["kind"] == "naver_blog_post_plan"


def test_fill_editor_uses_stored_payload_not_fresh_arguments(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "저장된 제목", "body": "저장된 본문", "tags": ["x"]})

    result = tools.fill_editor({"action_id": prepared["action_id"]})

    assert result["title"] == "저장된 제목"
    fill_call = next(args for name, args in browser.calls if name == "naver_blog_fill_editor")
    assert fill_call["title"] == "저장된 제목"
    assert fill_call["body"] == "저장된 본문"
    assert fill_call["tags"] == ["x"]


def test_fill_editor_carries_the_body_verdict_upward(tmp_path: Path) -> None:
    """넣었다는 사실이 아니라 남았다는 사실이 올라와야 한다.

    2026-08-05: 순서가 멀쩡한 979자를 넣었는데 편집기 안에서 문단이 뒤섞였고
    (`## 2` 절이 맨 뒤로 갔다), 도구는 성공을 반환했다. 아래 계층이 읽어서 판정해도
    이 래퍼가 그 값을 빼고 돌려주면 위에서는 아무도 모른다.
    """
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    browser.body_verified = False
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})

    result = tools.fill_editor({"action_id": prepared["action_id"]})

    assert result["verified"] is False
    assert result["body_mismatch"]


def test_fill_editor_reports_a_clean_fill_as_verified(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, _browser, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})

    result = tools.fill_editor({"action_id": prepared["action_id"]})

    assert result["verified"] is True
    assert "body_mismatch" not in result


def test_fill_editor_blocks_wrong_origin(tmp_path: Path) -> None:
    config = _config(tmp_path)
    browser = FakeBrowser(url="https://evil.example.com/phishing")
    tools, browser, _ = _tools(tmp_path, config, browser)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    with pytest.raises(RuntimeError, match="naver_blog_origin_not_allowed"):
        tools.fill_editor({"action_id": prepared["action_id"]})


def test_save_draft_commits_exactly_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})
    assert browser.count("naver_blog_click_save_draft") == 0

    result = tools.save_draft({"action_id": ready["action_id"]})
    assert result["status"] == "draft_saved"
    assert browser.count("naver_blog_click_save_draft") == 1

    second = tools.save_draft({"action_id": ready["action_id"]})
    assert second["duplicate_commit"] is True
    assert browser.count("naver_blog_click_save_draft") == 1

    action = actions.get_prepared_action(ready["action_id"])
    assert action["status"] == "committed"


def test_unapproved_save_draft_never_clicks_save_via_tool_gateway(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})

    store = JobStore(tmp_path / "data" / "gateway.db")
    gateway = ToolGateway(store, EventBus())
    gateway.register(
        ToolSpec(
            name="naver_blog_save_draft",
            description="",
            risk_level=RiskLevel.L2,
            handler=tools.save_draft,
        )
    )
    result = gateway.execute("naver_blog_save_draft", {"action_id": ready["action_id"]})

    assert result.status == "approval_required"
    assert browser.count("naver_blog_click_save_draft") == 0


def test_publish_happy_path_uploads_images_and_publishes_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    allowed_root = Path(config.local_file_allowed_roots)
    image = allowed_root / "photo.jpg"
    image.write_bytes(b"fake-image-bytes")

    tools, browser, actions = _tools(tmp_path, config)
    browser.title_text = "제목"
    prepared = tools.prepare_post({"title": "제목", "body": "본문", "images": [str(image)]})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_publish({"action_id": prepared["action_id"]})
    assert ready["preview"]["image_count"] == 1
    assert browser.count("naver_blog_upload_image") == 0

    result = tools.publish({"action_id": ready["action_id"]})
    assert result["status"] == "published"
    assert browser.count("naver_blog_upload_image") == 1
    assert browser.count("naver_blog_click_publish") == 1

    second = tools.publish({"action_id": ready["action_id"]})
    assert second["duplicate_commit"] is True
    assert browser.count("naver_blog_click_publish") == 1

    action = actions.get_prepared_action(ready["action_id"])
    assert action["status"] == "committed"


def test_publish_refuses_on_title_drift_at_commit_time(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "원래 제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_publish({"action_id": prepared["action_id"]})

    # Simulate someone/something changing the editor content between
    # approval-time preview and commit-time execution.
    browser.title_text = "완전히 다른 제목"

    with pytest.raises(RuntimeError, match="title_mismatch_at_commit"):
        tools.publish({"action_id": ready["action_id"]})
    assert browser.count("naver_blog_click_publish") == 0
    action = actions.get_prepared_action(ready["action_id"])
    assert action["status"] == "failed"


def test_publish_refuses_on_account_mismatch_at_commit_time(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    browser.account = "원래계정"
    ready = tools.prepare_publish({"action_id": prepared["action_id"]})

    browser.account = "다른계정"

    with pytest.raises(RuntimeError, match="account_mismatch_at_commit"):
        tools.publish({"action_id": ready["action_id"]})
    assert browser.count("naver_blog_click_publish") == 0
    action = actions.get_prepared_action(ready["action_id"])
    assert action["status"] == "failed"


def test_publish_blocks_wrong_origin(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_publish({"action_id": prepared["action_id"]})

    browser.url = "https://evil.example.com/phishing"
    with pytest.raises(RuntimeError, match="naver_blog_origin_not_allowed"):
        tools.publish({"action_id": ready["action_id"]})


def test_save_draft_without_page_proof_reports_failure_not_success(tmp_path: Path) -> None:
    """2026-08-03: every 임시저장 attempt failed and the user was still told
    "임시 저장 완료. 브라우저에 '저장됨' 표시가 떠 있을 것입니다." The click handler
    returned an evidence dict unconditionally, so a click that changed nothing
    was indistinguishable from a saved draft."""
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    browser.save_verified = False
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.fill_editor({"action_id": prepared["action_id"]})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})

    with pytest.raises(RuntimeError, match="draft_save_unverified"):
        tools.save_draft({"action_id": ready["action_id"]})

    assert browser.count("naver_blog_click_save_draft") == 1
    action = actions.get_prepared_action(ready["action_id"])
    # Unknown, not failed: the click may have landed, so it must never be
    # silently retried into a duplicate draft either.
    assert action["status"] == "unknown"


def test_unverified_save_is_not_replayable_as_a_cached_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    browser.save_verified = False
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})
    with pytest.raises(RuntimeError, match="draft_save_unverified"):
        tools.save_draft({"action_id": ready["action_id"]})

    with pytest.raises(RuntimeError, match="not_claimable:unknown"):
        tools.save_draft({"action_id": ready["action_id"]})
    assert browser.count("naver_blog_click_save_draft") == 1


def test_verified_save_reports_the_evidence_that_proved_it(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, _, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})
    result = tools.save_draft({"action_id": ready["action_id"]})
    assert result["status"] == "draft_saved"
    assert result["saved_evidence"] == "draft_count:0->1"


def test_publish_without_navigation_proof_reports_failure(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, actions = _tools(tmp_path, config)
    browser.publish_verified = False
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    ready = tools.prepare_publish({"action_id": prepared["action_id"]})

    with pytest.raises(RuntimeError, match="publish_unverified"):
        tools.publish({"action_id": ready["action_id"]})
    assert actions.get_prepared_action(ready["action_id"])["status"] == "unknown"


def test_fill_editor_recovers_when_model_supplies_an_unknown_action_id(tmp_path: Path) -> None:
    """The model retypes the action_id from chat history and gets it wrong, so
    a draft it just wrote came back as external_action_not_found_or_expired.
    The plan tier has no side effect, so it falls back to the newest live plan
    -- and says that it did."""
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    tools.prepare_post({"title": "진짜 제목", "body": "진짜 본문"})

    result = tools.fill_editor({"action_id": "AE5UBsDx-made-up"})

    assert result["action_id_recovered"] is True
    assert result["title"] == "진짜 제목"
    fill_call = next(args for name, args in browser.calls if name == "naver_blog_fill_editor")
    assert fill_call["body"] == "진짜 본문"


def test_fill_editor_still_fails_when_no_plan_was_ever_prepared(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    with pytest.raises(RuntimeError, match="not_found_or_expired"):
        tools.fill_editor({"action_id": "AE5UBsDx-made-up"})
    assert browser.calls == []


def test_commit_action_id_is_never_recovered_from_another_action(tmp_path: Path) -> None:
    """Recovery stops at the plan tier. A commit action_id is what the approval
    nonce was issued against, so guessing there would let an approval for one
    action execute a different one."""
    config = _config(tmp_path)
    tools, browser, _ = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    tools.prepare_save_draft({"action_id": prepared["action_id"]})

    with pytest.raises(RuntimeError, match="not_found_or_expired"):
        tools.save_draft({"action_id": "wrong-commit-id"})
    assert browser.count("naver_blog_click_save_draft") == 0


def test_post_plan_outlives_the_short_commit_ttl(tmp_path: Path) -> None:
    """A drafted post used to expire in the same 10 minutes as a commit token,
    so a normal back-and-forth about the draft invalidated the draft."""
    config = _config(tmp_path)
    config.external_action_ttl_sec = 300
    config.naver_blog_plan_ttl_sec = 3600
    tools, _, actions = _tools(tmp_path, config)
    prepared = tools.prepare_post({"title": "제목", "body": "본문"})
    ready = tools.prepare_save_draft({"action_id": prepared["action_id"]})

    plan = actions.get_prepared_action(prepared["action_id"])
    commit = actions.get_prepared_action(ready["action_id"])
    assert plan["expires_at"] - plan["created_at"] == pytest.approx(3600, abs=2)
    assert commit["expires_at"] - commit["created_at"] == pytest.approx(300, abs=2)


def test_disabled_config_disables_registration(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.naver_blog_enabled = False
    tools, _, _ = _tools(tmp_path, config)
    store = JobStore(tmp_path / "data" / "gateway2.db")
    gateway = ToolGateway(store, EventBus())
    tools.register(gateway)
    listed = {row["name"]: row for row in gateway.list_tools()}
    assert listed["naver_blog_publish"]["enabled"] is False
