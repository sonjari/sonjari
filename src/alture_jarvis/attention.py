"""사람이 화면을 봐야 하는 순간을 알린다 — 조용히 실패하지 않게.

브라우저 작업이 어긋나는 방식은 두 갈래다. 하나는 에이전트가 스스로 회복할 수 있는
것(ref 가 낡았다, 셀렉터를 못 찾았다)이고, 다른 하나는 **사람 말고는 아무도 못 푸는
것**이다: 봇 확인 화면, 로그인 요구, 반쯤 채워진 폼, 눌렀는데 바뀐 걸 못 읽은 저장.

앞의 것은 모델에게 돌려주면 된다. 뒤의 것은 돌려줘 봐야 모델이 같은 자리를 계속
두드리거나, 더 나쁘게는 "완료했습니다"라고 답한다(사고: 모델이 안 한 일을 했다고 답함).
그래서 뒤의 것만 골라서 **화면 카드 · 윈도우 알림 · 음성** 세 갈래로 사람에게 올린다.

의도적으로 **막지 않는다**. 확인을 기다리며 브라우저 스레드를 붙잡으면 교착이 난다 —
확인창이 떠 있는 동안 그것을 띄운 클릭이 끝나지 않고, 브라우저 작업은 한 스레드에서
직렬로 돌기 때문이다(2026-08-05 실브라우저에서 실측하고 되돌린 설계). 알리고, 에이전트는
그 실패를 관찰값으로 받아 계속 판단한다.

경보는 아껴 쓴다. 잦은 경보는 무시되고, 무시되는 경보는 없는 것과 같다.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AttentionRule:
    code: str
    pattern: re.Pattern[str]
    title: str
    message: str
    speech: str


# 사람이 아니면 못 푸는 것들만. 여기에 무엇을 넣을지가 이 파일의 전부다 —
# 에이전트가 스스로 회복하는 실패(selector_not_found, stale_element_ref,
# not_a_select …)를 넣으면 하루에 수십 번 울리고, 그러면 진짜일 때 아무도 안 본다.
_RULES: tuple[AttentionRule, ...] = (
    AttentionRule(
        code="bot_check",
        pattern=re.compile(
            r"(search_blocked|captcha|bot_check|manual_intervention|보안문자|캡차|"
            r"로봇이 아닙니다|과제 해결|사람인지 확인)",
            re.IGNORECASE,
        ),
        title="사람인지 확인하는 화면이 떴어요",
        message=(
            "체크 표시나 그림 고르기 같은 확인 화면에서 멈췄어요. 이건 제가 대신 누르지 않아요 — "
            "작업 표시줄에서 깜빡이는 크롬 아이콘을 눌러 직접 확인해 주시면 이어서 할게요. 창이 안 보이면 「크롬 창 보기」를 눌러 주세요."
        ),
        speech="사람인지 확인하는 화면이 떴어요. 크롬 창에서 한번 확인해 주시겠어요?",
    ),
    AttentionRule(
        code="google_reauth_required",
        # 리프레시 토큰이 죽으면 토큰 엔드포인트가 400/invalid_grant 를 준다.
        # 이건 자비스가 절대 못 푼다 — 브라우저에서 사람이 다시 승인해야 한다.
        pattern=re.compile(
            r"(oauth2\.googleapis\.com/token|invalid_grant|token_refresh_failed|"
            r"google_not_connected|google_auth_expired)",
            re.IGNORECASE,
        ),
        title="구글을 다시 연결해 주세요",
        message=(
            "구글 토큰이 만료됐습니다. 지메일·캘린더·드라이브가 **전부** 막혀 있습니다. "
            "손자리 화면에서 구글 연결하기를 눌러 다시 승인해 주시면 이어서 진행합니다."
        ),
        speech="구글 연결이 끊겼습니다. 다시 연결해 주셔야 캘린더와 메일을 쓸 수 있습니다.",
    ),
    AttentionRule(
        code="login_required",
        pattern=re.compile(r"(login_required|not_signed_in|로그인이 필요|nid\.naver\.com)", re.IGNORECASE),
        title="로그인이 필요해요",
        message=(
            "이 사이트에 로그인이 안 되어 있어요. 작업 표시줄에서 깜빡이는 크롬 아이콘을 눌러 로그인해 주시고 "
            "'로그인 상태 유지'를 켜 두시면 다음부터는 안 물어봐요. 창이 안 보이면 「크롬 창 보기」를 눌러 주세요."
        ),
        speech="로그인이 필요해요. 크롬 창에서 한번 로그인해 주시겠어요?",
    ),
    AttentionRule(
        code="form_partially_filled",
        pattern=re.compile(r"fill_form_stopped_at", re.IGNORECASE),
        title="폼이 반쯤 채워진 채 멈췄습니다",
        message=(
            "양식을 채우다 중간에서 막혔습니다. 어디까지 들어갔는지는 아래 내용에 있습니다. "
            "제출 전에 화면에서 직접 확인해 주세요."
        ),
        speech="양식을 채우다 중간에 막혔습니다. 화면을 한번 확인해 주시겠어요?",
    ),
    AttentionRule(
        code="upload_blocked",
        pattern=re.compile(r"(upload_path_not_allowed|file_too_large|sensitive_field_blocked)", re.IGNORECASE),
        title="첨부를 진행하지 않았습니다",
        message="파일 첨부가 규칙에 막혔습니다. 필요한 파일이면 직접 첨부해 주세요.",
        speech="파일 첨부가 막혔습니다. 확인해 주시겠어요?",
    ),
    AttentionRule(
        code="editor_not_ready",
        pattern=re.compile(r"(editor_not_ready|naver_blog_element_missing)", re.IGNORECASE),
        title="편집기 화면이 예상과 다릅니다",
        message=(
            "글 쓰는 화면이 뜨기를 기다렸는데 나타나지 않았습니다. 브라우저에 로그인 화면이나 "
            "안내 팝업이 떠 있는지 봐 주세요. 아직 아무것도 입력되지 않았습니다."
        ),
        speech="편집기 화면을 못 찾았습니다. 브라우저를 한번 확인해 주시겠어요?",
    ),
    AttentionRule(
        code="browser_stuck",
        pattern=re.compile(r"(browser_action_timeout|browser_start_failed|target closed|browser has been closed)", re.IGNORECASE),
        title="브라우저가 응답하지 않습니다",
        message="브라우저 조작이 시간 안에 끝나지 않았습니다. 창이 떠 있는지, 무엇이 막고 있는지 봐 주세요.",
        speech="브라우저가 응답하지 않습니다. 화면을 한번 봐 주시겠어요?",
    ),
    AttentionRule(
        code="dialog_needs_confirmation",
        pattern=re.compile(r"(dialog_needs_confirmation|confirm_dialog|확인이 필요한 창)", re.IGNORECASE),
        title="확인이 필요한 창이 떴습니다",
        message=(
            "긍정 버튼을 눌러야 넘어가는 창이 떠 있습니다. 그건 제가 누르지 않습니다 — "
            "문구를 보시고 직접 눌러 주세요."
        ),
        speech="확인 창이 떠 있습니다. 직접 확인해 주셔야 합니다.",
    ),
)

# 눌렀는데 화면이 바뀐 걸 못 읽은 경우. 실패가 아니라 **모름**이라 규칙이 다르다:
# 다시 누르면 두 번 저장될 수 있으므로 재시도가 아니라 사람 확인이 정답이다.
_UNVERIFIED = AttentionRule(
    code="change_not_verified",
    pattern=re.compile(r"^$"),
    title="눌렀지만 반영됐는지 확인 못 했습니다",
    message=(
        "동작은 실행했는데 화면에서 결과를 읽지 못했습니다. 먹었을 수도, 안 먹었을 수도 "
        "있습니다 — 다시 누르면 두 번 처리될 수 있어 멈췄습니다. 화면에서 확인해 주세요."
    ),
    speech="눌렀는데 반영됐는지 확인이 안 됩니다. 화면을 한번 봐 주시겠어요?",
)

# 같은 자리에서 계속 막힐 때. 개별 실패는 흔하지만 반복은 사람이 볼 신호다.
_REPEATED = AttentionRule(
    code="repeated_failure",
    pattern=re.compile(r"^$"),
    title="같은 곳에서 계속 막히고 있습니다",
    message="같은 도구가 연달아 실패했습니다. 화면이 예상과 다른 상태일 수 있습니다.",
    speech="같은 곳에서 계속 막히고 있습니다. 화면을 확인해 주시겠어요?",
)


#: 우리 하네스의 **차례 규칙**이 되돌려 보낸 것. 화면이 막힌 게 아니라 사람이 볼 것이 없다 (2026-09-28 확인 판 947a1d65:
#: 산출물 단계 되돌림 다섯 번에 「화면을 확인해 주세요」를 띄우고 판을 멈췄다).
_ORDER_RULE_ERRORS = frozenset({"not_this_stage", "code_recon_required"})


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


# 로그인 창은 사이트마다 다른 말을 쓴다. **문구 하나로 잡으면 못 잡는다.**
#
# 2026-08-10 크몽 실측: 자비스가 의뢰 등록 화면까지 눌러서 도착했고 로그인 모달에
# 막혔는데, 그 모달의 문구는 이랬다:
#
#   "로그인 유지 / 아이디·비밀번호 찾기 / 로그인 / SNS 간편 로그인 / 휴대폰 인증 /
#    아직 크몽 회원이 아니신가요? / 회원가입"
#
# '로그인'이 네 번 나오는데 정작 규칙이 찾던 **'로그인이 필요'** 라는 어구가 없다.
# 그래서 login_required 로 분류되지 않았고, 사람 문이 아니니 워커를 놓지도,
# 체크포인트를 남기지도, 지켜보지도 않았다 — **6단계 전체가 첫 관문에서 죽었다.**
# 두 번 두드려 보고 그냥 답을 내고 끝냈다.
#
# 그래서 문구가 아니라 **로그인 폼의 생김새**로 본다. 다만 넓히면 머리글에 '로그인'
# 글자만 있어도 걸리므로, 두 가지를 **모두** 요구한다:
#   (1) 무언가가 가로막고 있다는 맥락(팝업·대화상자·차단)
#   (2) 로그인 폼 표지가 **둘 이상**
# 크몽 모달은 (1) browser_popup_blocking, (2) 표지 4개로 넉넉히 걸린다.
_LOGIN_FORM_MARKS = (
    re.compile(r"회원\s*가입|가입하기|sign\s*up", re.IGNORECASE),
    re.compile(r"간편\s*로그인|SNS\s*로그인|소셜\s*로그인|social\s*login", re.IGNORECASE),
    re.compile(r"아이디\s*찾기|비밀번호\s*찾기|비밀번호를\s*잊|forgot\s*password", re.IGNORECASE),
    re.compile(r"로그인\s*유지|자동\s*로그인|remember\s*me|keep\s*me\s*signed", re.IGNORECASE),
    re.compile(r"이메일\s*로그인|아이디\s*입력|휴대폰\s*인증", re.IGNORECASE),
)

_BLOCKING_CONTEXT = re.compile(
    r"(popup|dialog|modal|overlay|blocking|blocked|가로막|팝업|모달|차단)", re.IGNORECASE
)


_BY_CODE = {rule.code: rule for rule in _RULES}

#: 읽기 전용 브라우저에서 「확인 못 한 변경」 경고를 올리지 않는 도구 — 누르기·키·좌표 누르기.
#: 채우기(`browser_fill`)는 넣지 않는다: 폼에 값이 반쯤 들어간 채로 남는 것은 사람이 알아야 한다.
_READ_ONLY_SAFE_TOOLS = frozenset({"browser_click", "browser_press", "browser_click_at", "browser_select"})


def _looks_like_a_login_wall(haystack: str) -> bool:
    if not _BLOCKING_CONTEXT.search(haystack):
        return False
    return sum(1 for mark in _LOGIN_FORM_MARKS if mark.search(haystack)) >= 2


def classify(observation: dict[str, Any]) -> AttentionRule | None:
    """이 관찰값이 사람을 불러야 하는 것인지. 아니면 None."""
    result = observation.get("result")
    evidence = result if isinstance(result, dict) else {}
    if observation.get("ok"):
        # 성공했다고 보고했지만 확인은 못 한 변경.
        if evidence.get("verified") is False:
            # exit!=0인 테스트는 결과를 못 읽은 변경이 아니라 읽힌 복구 근거다.
            if str(evidence.get("action") or "") == "local_run_project_command":
                return None
            # 기대는 빗나갔어도 화면이 분명히 바뀌었다면 사람을 부르지 않는다.
            # 에이전트가 새 화면을 다시 읽고 이어갈 수 있는 상황이고, 이런 것까지
            # 울리면 진짜일 때 아무도 안 본다(게이트는 좋은 표본으로 역검증할 것).
            status = str((evidence.get("verification") or {}).get("status") or "")
            if status == "changed_otherwise":
                return None
            return _UNVERIFIED
        return None
    haystack = " ".join(
        str(part)
        for part in (observation.get("error"), observation.get("status"), evidence.get("error"))
        if part
    )
    if not haystack:
        return None
    # 로그인 벽을 먼저 본다. 다른 규칙이 먼저 걸려도(편집기를 못 찾았다든가) 진짜
    # 원인이 로그인이면 그걸 말해 줘야 사람이 무엇을 할지 안다.
    if _looks_like_a_login_wall(haystack):
        return _BY_CODE["login_required"]
    for rule in _RULES:
        if rule.pattern.search(haystack):
            return rule
    return None


class AttentionService:
    """사람을 부르는 한 곳. 화면·알림·음성이 같은 판정에서 나가야 한다."""

    def __init__(
        self,
        events: Any,
        notifications: Any = None,
        speak: Callable[[str], Any] | None = None,
        *,
        max_per_job: int = 3,
        repeat_threshold: int = 3,
        enabled: bool = True,
        browser_read_only: Callable[[], bool] | None = None,
    ) -> None:
        self.events = events
        #: 읽기 전용 브라우저면 누르기·Enter 는 저장·결제·게시를 못 한다(`browser._read_only_blocks`).
        #: 그러면 「다시 누르면 두 번 처리될 수 있다」는 경고의 근거가 없다.
        self.browser_read_only = browser_read_only or (lambda: False)
        self.notifications = notifications
        self.speak = speak
        self.max_per_job = max(1, int(max_per_job))
        self.repeat_threshold = max(2, int(repeat_threshold))
        self.enabled = bool(enabled)
        # job_id -> {"raised": set[str], "count": int, "failures": {tool: int}}
        self._jobs: dict[str, dict[str, Any]] = {}

    def reset(self, job_id: str) -> None:
        self._jobs.pop(str(job_id), None)

    def _state(self, job_id: str) -> dict[str, Any]:
        state = self._jobs.get(job_id)
        if state is None:
            if len(self._jobs) > 64:  # 오래된 잡이 무한히 쌓이지 않게
                self._jobs.clear()
            state = {"raised": set(), "count": 0, "failures": {}}
            self._jobs[job_id] = state
        return state

    def announce(
        self,
        *,
        code: str,
        title: str,
        message: str,
        speech: str,
        job_id: str = "",
        tool: str = "",
        detail: str = "",
        url: str = "",
    ) -> dict[str, Any] | None:
        """도구 결과가 **아닌** 곳에서 사람을 부른다(관찰 초소 등).

        규칙 표(`_RULES`)를 안 거친다 — 부르는 쪽이 이미 판정을 끝냈기 때문이다.
        그래도 **길은 여기 하나**여야 한다: 화면 카드·윈도우 알림·음성이 서로 다른
        자리에서 나가기 시작하면, 어디를 끄면 조용해지는지 아무도 모르게 된다.
        """
        if not self.enabled:
            return None
        notice = {
            "job_id": job_id,
            "code": code,
            "tool": tool,
            "title": title,
            "message": message,
            "speech": speech,
            "detail": detail,
            "url": url,
            "at": time.time(),
        }
        self.events.publish("attention_required", notice)
        if self.notifications is not None:
            try:
                self.notifications.notify(f"Sonjari · {title}", message)
            except Exception:  # noqa: BLE001 — 알림이 안 떠도 카드와 음성은 살아야 한다
                pass
        if self.speak is not None:
            try:
                self.speak(speech)
            except Exception:  # noqa: BLE001
                pass
        return notice

    def check(
        self,
        *,
        job_id: str,
        tool: str,
        arguments: dict[str, Any] | None,
        observation: dict[str, Any],
    ) -> dict[str, Any] | None:
        """도구 결과 하나를 보고, 필요하면 사람을 부른다. 부른 내용을 돌려준다."""
        if not self.enabled or not job_id:
            return None
        state = self._state(job_id)
        rule = classify(observation)
        if rule is _UNVERIFIED and tool in _READ_ONLY_SAFE_TOOLS and self.browser_read_only():
            # ★ 2026-09-26 노트북: 네이버 지도에서 **검색 단추**를 누른 뒤 「눌렀지만 반영됐는지 확인 못 했습니다 — 다시 누르면
            #   두 번 처리될 수 있어 멈췄습니다」가 떴다. 읽기 전용에서는 두 번 처리될 것이 없다. 모델에게는 도구 결과의
            #   instruction(다시 보고 다음 수)이 그대로 가고, 사람만 안 부른다.
            rule = None
        if rule is _UNVERIFIED and tool.startswith("local_"):
            # ★ 2026-10-05 AWS 영어 윈도우: 문서를 쓰다 블록 일부를 못 읽은 판에 「눌렀지만 반영됐는지 확인 못 했습니다 —
            #   다시 누르면 두 번 처리될 수 있어 멈췄습니다」가 떴다. 파일 쓰기는 누른 것이 아니고 두 번 처리될 것도 없다.
            #   무엇이 빠졌는지는 도구 결과(`unreadable_blocks`)가 모델에게, 대조표가 사람에게 말한다.
            rule = None
        if rule is None and not observation.get("ok") and str(observation.get("error") or "") not in _ORDER_RULE_ERRORS:
            # 개별 실패는 흔하다. 같은 도구가 반복해서 실패할 때만 신호로 본다.
            failures = state["failures"]
            failures[tool] = int(failures.get(tool, 0)) + 1
            if failures[tool] >= self.repeat_threshold:
                rule = _REPEATED
        if rule is None:
            return None
        if rule.code in state["raised"] or state["count"] >= self.max_per_job:
            # 같은 원인으로 두 번, 또는 한 작업에서 너무 여러 번 울리지 않는다.
            return None
        state["raised"].add(rule.code)
        state["count"] = int(state["count"]) + 1

        result = observation.get("result")
        evidence = result if isinstance(result, dict) else {}
        detail = _clean(
            observation.get("error")
            or evidence.get("error")
            or evidence.get("verification")
            or observation.get("status")
        )
        notice = {
            "job_id": job_id,
            "code": rule.code,
            "tool": tool,
            "title": rule.title,
            "message": rule.message,
            "speech": rule.speech,
            "detail": detail,
            "url": _clean(evidence.get("url"), 400),
            "at": time.time(),
        }
        self.events.publish("attention_required", notice)
        if self.notifications is not None:
            try:
                self.notifications.notify(f"Sonjari · {rule.title}", rule.message)
            except Exception:
                # 알림이 안 떠도 화면 카드와 음성은 살아 있어야 한다.
                pass
        if self.speak is not None:
            try:
                self.speak(rule.speech)
            except Exception:
                pass
        return notice
