from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .browser import BrowserWorker
from .config import JarvisConfig
from .external_actions import SETTLED_STATUSES, ExternalActionStore
from .local_computer import LocalComputerTools
from .models import RiskLevel
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec

# 임시저장 목록 화면을 **실제로 열어서** 확인한 절차다(2026-08-10). 짐작이 아니다:
#   편집기 우측 상단 '저장 N' 옆 → 버튼 "임시저장된 글 보기, N개"
#   → "편집" → 지울 글 체크 → "선택 삭제"
_DRAFT_DELETE_STEPS = (
    "편집기 우측 상단 '저장' 옆의 임시저장 목록을 열고 → [편집] → 그 글을 체크 → "
    "[선택 삭제] 를 누르시면 됩니다."
)

_UNPUBLISH_STEPS = (
    "그 글을 열고 본문 아래 [수정] → 발행 설정에서 공개 범위를 '비공개' 로 바꾸고 "
    "다시 발행하시면 목록에서 내려갑니다. 아주 지우려면 [삭제] 입니다."
)


_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _clean_detail(evidence: dict[str, Any]) -> str:
    """Why the save could not be proven, for the error the model has to read."""
    before = evidence.get("draft_count_before")
    after = evidence.get("draft_count_after")
    return f"count {before}->{after}, url {str(evidence.get('url') or '')[:120]}"


class NaverBlogTools:
    """Naver Blog computer-use automation.

    Reuses BrowserWorker's single Playwright thread (self.browser.execute)
    and never touches Playwright objects directly. All safety logic here --
    origin lock, commit-time re-verification -- operates only on the evidence
    dicts BrowserWorker.execute() returns, which keeps it unit-testable
    without a real browser (see tests/test_naver_blog.py).

    Two-tier prepared-action design:
      naver_blog_prepare_post creates the "source of truth" content plan
      (kind=naver_blog_post_plan). naver_blog_prepare_save_draft/publish each
      create a downstream commit-tier action (kind=naver_blog_save_draft /
      naver_blog_publish) that references the plan by post_action_id, so the
      final commit tools only ever receive {"action_id": ...} as arguments.
    """

    def __init__(
        self,
        config: JarvisConfig,
        browser: BrowserWorker,
        local_computer: LocalComputerTools,
        actions: ExternalActionStore,
    ) -> None:
        self.config = config
        self.browser = browser
        self.local_computer = local_computer
        self.actions = actions
        self._allowed_hosts = {
            host.strip().lower()
            for host in config.naver_blog_allowed_hosts.split(";")
            if host.strip()
        }
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "naver_blog_prepare_post",
                "네이버 블로그에 올릴 글의 제목·본문·태그·카테고리·이미지·공개범위·발행시각을 정리해 준비한다. "
                "이 단계는 브라우저를 열거나 편집기를 건드리지 않는다.",
                {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "category": {"type": "string"},
                    "images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "허용된 로컬 폴더 안의 이미지 절대경로",
                    },
                    "visibility": {"type": "string", "enum": ["public", "protected", "private"]},
                    "publish_at": {"type": "string", "description": "예약 발행 시각. 비우면 즉시 발행"},
                },
                ["title", "body"],
            ),
            self._function(
                "naver_blog_fill_editor",
                "naver_blog_prepare_post의 action_id로 저장된 제목·본문·태그를 네이버 블로그 편집기에 채운다. "
                "이미지 업로드나 저장·발행은 하지 않는다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "naver_blog_prepare_save_draft",
                "지금까지 채운 내용을 임시저장할 준비를 한다. 실제 저장은 하지 않고 승인용 미리보기를 만든다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "naver_blog_save_draft",
                "naver_blog_prepare_save_draft가 만든 action_id로 실제 임시저장을 커밋한다. "
                "임시저장은 되돌릴 수 있어서(목록에서 지우면 끝) 승인을 묻지 않는다 — 대신 저장 뒤에 "
                "되돌리는 방법을 사용자에게 알린다. 발행은 다르다(naver_blog_publish 는 승인이 필요하다). "
                "저장 사실이 화면에서 확인되지 않으면 실패로 반환된다 — 이 도구가 성공을 반환했을 때만 저장됐다고 말할 수 있다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "naver_blog_prepare_publish",
                "지금까지 채운 내용을 실제로 발행할 준비를 한다. 계정·제목·공개범위·카테고리·태그·발행시각·이미지 "
                "개수와 현재 화면 캡처를 승인용 미리보기로 만든다. 실제 발행은 하지 않는다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "naver_blog_publish",
                "naver_blog_prepare_publish가 만든 action_id로 실제 발행을 커밋한다. 화면 승인이 필요하다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "naver_blog_prepare_post": self.prepare_post,
            "naver_blog_fill_editor": self.fill_editor,
            "naver_blog_prepare_save_draft": self.prepare_save_draft,
            "naver_blog_save_draft": self.save_draft,
            "naver_blog_prepare_publish": self.prepare_publish,
            "naver_blog_publish": self.publish,
        }
        risks: dict[str, RiskLevel] = {
            "naver_blog_prepare_post": RiskLevel.L1,
            "naver_blog_fill_editor": RiskLevel.L1,
            "naver_blog_prepare_save_draft": RiskLevel.L1,
            # ★ L2 -> L1 (2026-08-10). 승인 없이 임시저장한다.
            #
            # 등급을 "파괴적인가"가 아니라 **"되돌릴 수 있는가"** 로 다시 매긴 첫
            # 사례다. 임시저장은 아무에게도 안 보이고, 알림도 안 가고, 목록에서
            # 지우면 끝난다 — 되돌릴 방법이 있고 그 방법을 자비스가 제목까지
            # 집어서 알려 준다(아래 _inverses).
            #
            # 발행(naver_blog_publish)은 L2 로 남긴다. 되돌린다고 해도 그 사이에
            # 사람이 봤을 수 있고, 본 것은 못 되돌린다.
            "naver_blog_save_draft": RiskLevel.L1,
            "naver_blog_prepare_publish": RiskLevel.L1,
            "naver_blog_publish": RiskLevel.L2,
        }
        enabled = self.config.naver_blog_enabled and self.config.browser_enabled
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    inverse=self._inverses().get(name),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=enabled,
                )
            )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.naver_blog_enabled and self.config.browser_enabled,
            "allowed_hosts": sorted(self._allowed_hosts),
            # Surfaced here so "왜 또 안 되지" is answerable before starting,
            # rather than several minutes into a post as an editor timeout.
            "session": self.browser.naver_session_alive(),
        }

    def _inverses(self) -> dict[str, "InverseSpec"]:
        """되돌릴 수 있는 블로그 동작.

        ★ 임시저장 되돌리기를 **자동화하지 않은 이유**(실제 화면을 열어 보고 정함):

          1. 편집 모드에서는 글 행이 접근성 트리에 안 잡힌다(실측: 제목으로 찾으면
             0 매치). 조준하려면 손으로 확인한 CSS 셀렉터가 있어야 하는데, 그건
             지금 없다. 없으면 **지어내면 안 된다** — 이 저장소가 이틀을 태운 규칙이다.
          2. **'전체 삭제'가 '선택 삭제' 바로 옆에 있다.** 조준이 틀리면 실패로
             끝나지 않고 임시저장이 통째로 날아간다. 자비스가 만들지도 않은,
             몇 달 전 글까지.
          3. 되돌릴 대상은 임시저장이다 — 아무에게도 안 보이고 알림도 안 간다.

        되돌리기가 되돌릴 대상보다 위험하면 그건 나쁜 거래다. 그래서 자동으로 하지
        않고, **어느 글인지 제목으로 집어서** 사람에게 넘긴다. `undo=None` 이 그 뜻이다.

        ★ 발행(naver_blog_publish)도 2026-08-15 에 넣었다 — **다만 `undo=None` 이다.**

        원래 여기 "발행은 여기 없다. 비공개로 돌릴 수는 있어도 그 사이에 누가 봤을
        수 있고, 본 것은 못 되돌린다"고 적혀 있었다. 그 문장은 지금도 맞지만,
        **되돌리기를 아예 안 내주는 근거로는 약하다.** 본 사람을 되돌릴 수 없다는 것과
        더 보이지 않게 만드는 것은 다른 일이고, 뒤의 것은 여전히 가치가 있다.
        무엇보다 지금까지는 발행하고 나면 **돌아갈 길이 기록조차 안 됐다** —
        어느 글이었는지 찾는 것부터 사람 몫이었다.

        자동(`undo`)으로 안 하는 이유는 위 임시저장과 **정확히 같다**: 비공개 전환은
        글 관리 화면을 거치는데 거기서 조준이 틀리면 자비스가 만들지도 않은 글이
        날아간다. 손으로 확인한 셀렉터가 없고, 없으면 **지어내면 안 된다.**
        자동으로 만들려면 실제 블로그를 열어 셀렉터를 떠야 한다.

        발행의 위험 등급(L2)은 이것 때문에 **안 내린다.** 되돌릴 수 있어서 등급을
        내리는 것은 `undo` 가 실제로 도는 것에만 해당한다 — 안내문은 자율을 못 산다.
        """
        return {
            "naver_blog_save_draft": InverseSpec(
                label="방금 임시저장한 글 지우기",
                handle_from=lambda result: (
                    {"title": str(result.get("title") or "")}
                    if result.get("status") == "draft_saved" and result.get("title")
                    else None
                ),
                undo=None,  # 사람 몫 — 위 주석 참고
                manual_hint=(
                    "임시저장은 손자리가 직접 못 지웁니다(목록에서 '전체 삭제'를 잘못 누를 위험이 "
                    f"있어 일부러 막아 뒀습니다). {_DRAFT_DELETE_STEPS}"
                ),
            ),
            "naver_blog_publish": InverseSpec(
                label="방금 발행한 글 내리기",
                # 주소가 있어야 **어느 글인지** 집을 수 있다. 발행은 편집기가 글
                # 페이지로 넘어간 것을 확인해야만 커밋되므로(`published_verified`),
                # status 가 published 면 주소도 있다. 없으면 안 내준다 —
                # 눌렀는데 어디로 가야 할지 모르는 되돌리기가 제일 나쁘다.
                handle_from=lambda result: (
                    {"url": str(result.get("url") or ""), "title": str(result.get("title") or "")}
                    if result.get("status") == "published" and result.get("url")
                    else None
                ),
                undo=None,  # 사람 몫 — 위 주석 참고(셀렉터를 지어내지 않는다)
                manual_hint=(
                    "발행 취소는 손자리가 직접 못 합니다(글 관리 화면에서 조준이 틀리면 "
                    f"다른 글이 날아갈 수 있어 일부러 막아 뒀습니다). {_UNPUBLISH_STEPS} "
                    "※ 이미 본 사람은 되돌릴 수 없습니다 — 더 보이지 않게 하는 것까지입니다."
                ),
            ),
        }

    # ---- safety helpers ----

    def _assert_origin(self, evidence: dict[str, Any]) -> dict[str, Any]:
        host = (urlparse(str(evidence.get("url") or "")).hostname or "").lower()
        if host not in self._allowed_hosts:
            raise RuntimeError(f"naver_blog_origin_not_allowed:{host or '(no_url)'}")
        return evidence

    def _require_post_plan(self, action_id: str) -> tuple[dict[str, Any], str]:
        """Resolve the post plan, recovering from an id the model got wrong.

        Returns (action, recovered_id) where recovered_id is non-empty only when
        the requested id could not be used and the newest live plan was taken
        instead. Every user message starts a fresh agent run whose
        last_action_ids map is empty, so from the second turn on the model is
        retyping an opaque token out of chat history -- agent.py already
        documents it inventing plausible ones. Throwing away a written draft
        over that is pure loss: this tier is L1, has no side effect, and the
        commit tier below still resolves its own id strictly, because that id
        is what the approval nonce was issued against.
        """
        action = self.actions.get_prepared_action(action_id)
        if action is not None and action["kind"] != "naver_blog_post_plan":
            raise RuntimeError("external_action_kind_mismatch")
        if action is not None and action["status"] in {"prepared", "committing", "committed"}:
            return action, ""
        fallback = self.actions.latest_prepared_of_kind("naver_blog_post_plan")
        if fallback is None:
            if action is None:
                raise RuntimeError("external_action_not_found_or_expired")
            raise RuntimeError(f"external_action_invalid_status:{action['status']}")
        return fallback, str(fallback["action_id"])

    # ---- naver_blog_prepare_post ----

    def prepare_post(self, arguments: dict[str, Any]) -> dict[str, Any]:
        title = str(arguments.get("title") or "").strip()
        if not title:
            raise ValueError("naver_blog_title_required")
        body = str(arguments.get("body") or "").strip()
        if not body:
            raise ValueError("naver_blog_body_required")
        tags = [str(tag).strip()[:30] for tag in (arguments.get("tags") or []) if str(tag).strip()][:30]
        category = str(arguments.get("category") or "").strip()[:60]
        visibility = str(arguments.get("visibility") or "public")
        if visibility not in {"public", "protected", "private"}:
            raise ValueError("naver_blog_visibility_invalid")
        publish_at = str(arguments.get("publish_at") or "").strip()

        max_count = self.config.naver_blog_image_max_count
        max_bytes = self.config.naver_blog_image_max_bytes
        raw_images = list(arguments.get("images") or [])
        if len(raw_images) > max_count:
            raise ValueError("naver_blog_image_count_exceeded")
        images: list[dict[str, Any]] = []
        for raw_path in raw_images:
            path = self.local_computer.resolve_export_path(str(raw_path))
            if not path.is_file():
                raise ValueError(f"naver_blog_image_not_a_file:{path.name}")
            if path.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
                raise ValueError(f"naver_blog_image_unsupported_format:{path.name}")
            size = path.stat().st_size
            if size > max_bytes:
                raise ValueError(f"naver_blog_image_too_large:{path.name}")
            images.append({"path": str(path), "name": path.name, "size": size})

        payload = {
            "title": title,
            "body": body,
            "tags": tags,
            "category": category,
            "visibility": visibility,
            "publish_at": publish_at,
            "images": images,
        }
        preview = {
            "title": title,
            "tags": tags,
            "category": category,
            "visibility": visibility,
            "publish_at": publish_at or "즉시",
            "image_count": len(images),
            "body_preview": body[:300],
        }
        action = self.actions.create_prepared_action(
            kind="naver_blog_post_plan",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.naver_blog_plan_ttl_sec,
        )
        return {
            "action": "naver_blog_prepare_post",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": False,
        }

    # ---- naver_blog_fill_editor (L1, no commit, no images) ----

    def fill_editor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        plan, recovered = self._require_post_plan(action_id)
        payload = plan["payload"]

        opened = self._assert_origin(self.browser.execute("naver_blog_open_editor", {}))
        filled = self._assert_origin(
            self.browser.execute(
                "naver_blog_fill_editor",
                {"title": payload["title"], "body": payload["body"], "tags": payload["tags"]},
            )
        )
        # 넣은 본문이 화면에 그대로 남았는지는 아래 계층이 읽어서 판정한다. 그 값을
        # 여기서 흘리면 위에서는 아무도 모른다 — 2026-08-05 에 문단이 뒤섞인 글이
        # 성공으로 올라온 것이 정확히 이 지점이었다.
        verified = bool(filled.get("verified"))
        return {
            "action": "naver_blog_fill_editor",
            "action_id": str(plan["action_id"]),
            "action_id_recovered": bool(recovered),
            "title": payload["title"],
            "tag_count": len(payload["tags"]),
            "url": filled.get("url", ""),
            "verified": verified,
            "body_length": filled.get("body_length", 0),
            "body_chars_landed": filled.get("body_chars_landed", 0),
            **({} if verified else {"body_mismatch": str(filled.get("body_mismatch") or "본문이 화면과 다릅니다")}),
            "popups_dismissed": (opened.get("popups_dismissed") or [])
            + (filled.get("popups_dismissed") or []),
        }

    # ---- naver_blog_prepare_save_draft -> naver_blog_save_draft ----

    def prepare_save_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        plan, recovered = self._require_post_plan(action_id)
        payload = plan["payload"]
        account_evidence = self._assert_origin(self.browser.execute("naver_blog_read_account", {}))

        commit_payload = {
            "post_action_id": str(plan["action_id"]),
            "expected_title": payload["title"],
            "expected_account": str(account_evidence.get("account") or ""),
        }
        preview = {
            "account": commit_payload["expected_account"] or "(확인 안됨)",
            "title": payload["title"],
            "tag_count": len(payload["tags"]),
        }
        action = self.actions.create_prepared_action(
            kind="naver_blog_save_draft",
            payload=commit_payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "naver_blog_prepare_save_draft",
            "action_id": action["action_id"],
            "action_id_recovered": bool(recovered),
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def save_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "naver_blog_save_draft":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "naver_blog_save_draft", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        try:
            evidence = self._assert_origin(self.browser.execute("naver_blog_click_save_draft", {}))
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        # A click that returned without throwing is not a saved draft. On
        # 2026-08-03 the user was told "임시 저장 완료" on the strength of exactly
        # that, and there was no draft. The save is only real if the page shows
        # it, so an unproven save is reported as unknown -- the click may well
        # have landed, which is why this is not mark_failed and why the user is
        # asked to look rather than told a comfortable answer.
        if not evidence.get("saved_verified"):
            detail = _clean_detail(evidence)
            self.actions.mark_unknown(action_id, f"naver_blog_draft_save_unverified:{detail}")
            raise RuntimeError(f"naver_blog_draft_save_unverified:{detail}")

        result = {
            "status": "draft_saved",
            "url": evidence.get("url", ""),
            "title": payload["expected_title"],
            "saved_evidence": str(evidence.get("saved_evidence") or ""),
        }
        self.actions.mark_committed(action_id, result)
        return {"action": "naver_blog_save_draft", "action_id": action_id, **result}

    # ---- naver_blog_prepare_publish -> naver_blog_publish ----

    def prepare_publish(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        plan, recovered = self._require_post_plan(action_id)
        payload = plan["payload"]
        account_evidence = self._assert_origin(self.browser.execute("naver_blog_read_account", {}))
        screenshot_evidence = self._assert_origin(self.browser.execute("naver_blog_capture_screen", {}))

        commit_payload = {
            "post_action_id": str(plan["action_id"]),
            "expected_title": payload["title"],
            "expected_account": str(account_evidence.get("account") or ""),
            "images": payload["images"],
        }
        preview = {
            "account": commit_payload["expected_account"] or "(확인 안됨)",
            "title": payload["title"],
            "visibility": payload["visibility"],
            "category": payload["category"],
            "tags": payload["tags"],
            "publish_at": payload["publish_at"] or "즉시",
            "image_count": len(payload["images"]),
            "screenshot_path": screenshot_evidence.get("screenshot_path", ""),
        }
        action = self.actions.create_prepared_action(
            kind="naver_blog_publish",
            payload=commit_payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "naver_blog_prepare_publish",
            "action_id": action["action_id"],
            "action_id_recovered": bool(recovered),
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def publish(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "naver_blog_publish":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "naver_blog_publish", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        publish_evidence: dict[str, Any] = {}
        try:
            state = self._assert_origin(self.browser.execute("naver_blog_read_account", {}))
            current_account = str(state.get("account") or "")
            if payload["expected_account"] and current_account != payload["expected_account"]:
                raise RuntimeError("naver_blog_account_mismatch_at_commit")
            current_title = str(state.get("title_text") or "")
            if payload["expected_title"] and current_title and payload["expected_title"] not in current_title:
                raise RuntimeError("naver_blog_title_mismatch_at_commit")

            for image in payload.get("images") or []:
                self._assert_origin(
                    self.browser.execute("naver_blog_upload_image", {"path": image["path"]})
                )

            publish_evidence = self._assert_origin(self.browser.execute("naver_blog_click_publish", {}))
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        # Same rule as save_draft: publishing is claimed only when the editor
        # actually left the write page for the published post.
        if not publish_evidence.get("published_verified"):
            detail = str(publish_evidence.get("url_after") or "")[:160]
            self.actions.mark_unknown(action_id, f"naver_blog_publish_unverified:{detail}")
            raise RuntimeError(f"naver_blog_publish_unverified:{detail}")

        result = {
            "status": "published",
            "url": publish_evidence.get("url_after") or publish_evidence.get("url", ""),
            "title": payload["expected_title"],
        }
        self.actions.mark_committed(action_id, result)
        return {"action": "naver_blog_publish", "action_id": action_id, **result}
