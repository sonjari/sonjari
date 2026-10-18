"""답이 기댄 페이지의 사진 — 읽는 순간 한 장 찍고, 판이 끝나면 「대표사진」을 고른다 (2026-10-18 대표 결정).

꾸미는 그림이 아니라 **증거**다: 「이 답이 이 화면에서 나왔다」. 디스코드에서는 답 아래 한두 장으로 붙이고,
손자리 앱에서는 출처 카드가 된다(화면 작업은 나중).

## 무엇을 찍나

본문을 읽는 웹 도구(`browser_extract` · `browser_read`)가 성공한 순간, 그 탭의 보이는 영역을 한 장.
연 것(`browser_open_result`)·목록(`browser_search`)은 안 찍는다 — 근거 원장(`evidence.MANIFEST`)이 「본문을 읽었다」로
세는 것만 찍는다. 열기만 한 화면은 답이 기댈 수 없는 화면이다(2026-09-02 사고의 자리).
`google_drive_read` 도 원장에서는 웹 본문 읽기지만 **브라우저 탭이 아니라 API** 다 — 찍으면 엉뚱한 탭이 찍힌다. 그래서 뺀다.

## 어떻게 고르나

답의 숫자 · 고유명사가 **그 걸음이 읽은 본문에** 가장 많이 있는 페이지 순, 같으면 나중에 읽은 것. 새 대조를 짜지 않았다 —
숫자는 「도구가 준 적 없는 숫자」 대조와 **같은 정규화**(`evidence.numbers_claimed_in` · `numbers_in_body`)를 쓴다.
한쪽만 다르게 세면 대조가 비대칭이 된다(그 함수들의 주석에 실측이 있다).

## 무엇을 빼나 — 로그인 · 개인 화면

사진은 PC 밖(디스코드 · 바깥 AI)으로 나간다. 글은 `outbound.refine` 이 가리지만 **그림은 못 가린다.** 그래서 고르는 단계에서 뺀다.
- 웹이 아닌 것(파일 · 내 PC 창 · `chrome://`), 이 PC · 사내 주소(localhost · 사설 IP · 점 없는 이름)
- 로그인 · 결제 문 — 기존 규칙 `human_gate._GATE_URL_MARKERS` · `PAYMENT_FRAME_HOSTS` 를 그대로 쓴다
- 그 판에서 사람에게 로그인 · 결제 · 봇 확인을 넘긴 사이트(`human_gate.HUMAN_GATE_CODES`) — 넘겨받은 뒤 읽은 화면은 로그인한 화면이다
- 주소 낱말: 메일 · 은행 · 장바구니 · 주문 · 마이페이지 · 계정 설정
- 그 페이지 본문에 `outbound.refine` 이 **늘** 가리는 값(주민등록번호 · 카드 번호 · 비밀 키)이 있으면
전화번호 · 메일 주소는 맡긴 쪽이 needs 로 밝히면 나가도 되는 값이라 빼지 않고 `contains` 에 적어 둔다 —
나가는 사본(`outbound.outbound_job_view`)이 needs 를 보고 거른다.
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

from .evidence import EFFECT_READ_WEB, MANIFEST, TYPE_BODY_READ, numbers_claimed_in, numbers_in_body
from .human_gate import HUMAN_GATE_CODES, PAYMENT_FRAME_HOSTS, _GATE_URL_MARKERS, is_local_dev_url
from .outbound import refine
from .site_atlas import registrable

__all__ = [
    "SHOT_TOOLS",
    "MAX_SHOTS_PER_JOB",
    "SHOT_MAX_WIDTH",
    "SHOT_QUALITY",
    "shot_dir",
    "shot_path_for",
    "save_jpeg",
    "private_reason",
    "pick_showcase_shots",
]

#: 찍는 도구 — 원장이 「웹 본문을 읽었다」로 세는 것 중 **브라우저 탭에서 읽는** 것만.
SHOT_TOOLS: frozenset[str] = frozenset(
    name
    for name in ("browser_extract", "browser_read")
    if (spec := MANIFEST.get(name)) is not None and spec.type == TYPE_BODY_READ and spec.effect == EFFECT_READ_WEB
)

#: 판 하나에서 찍는 상한. 읽기를 수십 번 도는 판(상세 30개)이 디스크를 채우지 않게 — 넘으면 안 찍고 그 사실을 적는다.
MAX_SHOTS_PER_JOB = 40
SHOT_MAX_WIDTH = 1280
SHOT_QUALITY = 70

#: 늘 가리는 값 — 이게 본문에 있으면 그 화면은 밖으로 안 낸다.
_ALWAYS_HIDDEN = frozenset({"주민등록번호", "카드 번호", "비밀 키"})

#: 개인 화면의 주소 — 호스트.
_PRIVATE_HOST = re.compile(
    r"(?:^|\.)(?:mail\.google\.com|mail\.naver\.com|mail\.daum\.net|outlook\.(?:live|office|office365)\.com|"
    r"mail\.yahoo\.com|accounts\.google\.com|myaccount\.google\.com|account\.microsoft\.com|"
    r"pay\.naver\.com|order\.pay\.naver\.com|kbstar\.com|shinhan\.com|wooribank\.com|hanabank\.com|ibk\.co\.kr|"
    r"nonghyup\.com|kakaobank\.com|tossbank\.com|kbank\.com|citibank\.co\.kr|scfirstbank\.com|"
    r"busanbank\.co\.kr|dgb\.co\.kr|epostbank\.go\.kr|hometax\.go\.kr|gov\.kr)$"
    r"|(?:^|[.-])(?:mail|webmail|bank|banking|pay|wallet|intranet|groupware|gw|erp|hr)(?:[.-])",
    re.IGNORECASE,
)
#: 개인 화면의 주소 — 경로 조각. 질의(`?order=price`)는 안 본다 — 공개 목록의 정렬도 그렇게 생겼다.
_PRIVATE_PATH = re.compile(
    r"(?:^|/)(?:my-?page|my_page|myinfo|my-?account|my|me|account|accounts|profile/edit|settings|"
    r"cart|basket|checkout|order|orders|orderlist|payment|payments|wallet|inbox|mailbox|messages|"
    r"login|signin|sign-in|logout|member/(?:info|modify|edit))(?:[/._;-]|$)",
    re.IGNORECASE,
)


def shot_dir(output_dir: str | os.PathLike[str], job_id: str) -> Path:
    """판의 사진 자리. **책상(`workspace/<job>`) 옆**이지 책상 안이 아니다.

    ★ 책상 안에 두면 두 가지가 틀린다(2026-10-18 확인): 모델이 책상을 훑을 때(`local_list_directory`) 남이 둔 그림이
      보이고, 코드 판의 「작업 폴더가 바뀌었나」 지문(`agent._workspace_mark`)이 읽을 때마다 바뀌어 제자리 판정을 흐린다.
    """
    return Path(output_dir) / "shots" / str(job_id)


def shot_path_for(output_dir: str | os.PathLike[str], job_id: str, step: int) -> Path:
    return shot_dir(output_dir, job_id) / f"step_{int(step):03d}.jpg"


def save_jpeg(raw: bytes, destination: str | os.PathLike[str], *, max_width: int = SHOT_MAX_WIDTH,
              quality: int = SHOT_QUALITY) -> dict[str, Any]:
    """찍은 JPEG 를 가로 `max_width` 이하로 줄여 저장한다. 줄일 필요가 없으면 받은 그대로 쓴다(두 번 누르지 않는다).

    Pillow 가 없으면(있어야 하지만) 받은 그대로 쓴다 — 크기가 크다고 증거를 버리지 않는다.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = bytes(raw or b"")
    if not data:
        raise ValueError("empty_image")
    width = height = 0
    resized = False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width > max_width:
                ratio = max_width / float(width)
                small = image.convert("RGB").resize((max_width, max(1, int(height * ratio))), Image.LANCZOS)
                out = io.BytesIO()
                small.save(out, format="JPEG", quality=int(quality), optimize=True)
                data = out.getvalue()
                width, height = small.size
                resized = True
    except ImportError:
        pass
    target.write_bytes(data)
    return {"path": str(target), "bytes": len(data), "width": width, "height": height, "resized": resized}


def _host(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _internal_host(host: str) -> bool:
    if not host:
        return True
    if "." not in host:  # 점 없는 이름 — 사내 이름(`intranet`, `nas`)이다
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith((".local", ".lan", ".internal", ".corp", ".home", ".intra"))
    return address.is_private or address.is_loopback or address.is_link_local


def private_reason(url: str, *, body: str = "", gated_sites: Iterable[str] = ()) -> str:
    """이 화면을 **밖에 보여 주면 안 되는** 까닭. 보여 줘도 되면 빈 문자열."""
    text = str(url or "")
    try:
        parts = urlsplit(text)
    except ValueError:
        return "not_web"
    if parts.scheme not in {"http", "https"}:
        return "not_web"
    host = (parts.hostname or "").lower()
    if is_local_dev_url(text) or _internal_host(host):
        return "internal"
    lowered = text.lower()
    if any(marker in lowered for marker in _GATE_URL_MARKERS) or any(marker in lowered for marker in PAYMENT_FRAME_HOSTS):
        return "login_or_payment"
    site = registrable(host) or host
    if site and site in {registrable(item) or item for item in gated_sites if item}:
        return "handed_to_person"
    if _PRIVATE_HOST.search(host):
        return "private_site"
    if _PRIVATE_PATH.search(parts.path or ""):
        return "private_page"
    if body:
        _cleaned, hidden = refine(body)
        if any(item.get("kind") in _ALWAYS_HIDDEN for item in hidden):
            return "sensitive_value"
    return ""


def _gated_sites(steps: Iterable[Mapping[str, Any]]) -> set[str]:
    """이 판에서 사람에게 넘긴(로그인 · 결제 · 봇 확인) 사이트."""
    sites: set[str] = set()
    for step in steps:
        # `agent._record_observation` 이 사람 문에 막힌 걸음에 적어 둔 표시 — 이게 첫째 근거다.
        gate = step.get("human_gate") if isinstance(step.get("human_gate"), Mapping) else {}
        if str(gate.get("code") or "") in HUMAN_GATE_CODES and _host(str(gate.get("url") or "")):
            sites.add(_host(str(gate.get("url") or "")))
        evidence = step.get("evidence") if isinstance(step.get("evidence"), Mapping) else {}
        codes = {str(step.get("status") or ""), str(step.get("error") or "").split(":", 1)[0],
                 str(evidence.get("code") or ""), str(evidence.get("gate") or ""), str(evidence.get("status") or "")}
        if not codes & HUMAN_GATE_CODES:
            continue
        url = str(evidence.get("url") or evidence.get("blocked_url") or "")
        host = _host(url)
        if host:
            sites.add(host)
    return sites


# ── 답의 고유명사 ─────────────────────────────────────────────────────
#: 사람 개인의 연락처 — 휴대폰 번호 · 개인 메일 서비스 주소. 가게 · 회사 대표 번호(02- · 055- · 1588-)와 회사 도메인 메일은 공개 정보다.
# ★ 2026-10-18 대표 결정: 처음엔 본문에 전화번호 · 메일이 하나라도 있으면 사진째 뺐는데, 그러면 가게 · 관광지 페이지가
#   거의 다 빠진다(대표 번호가 늘 있다 — 그날 거창 밥집 조사가 그 모양). 개인 연락처가 있을 때만 뺀다.
_MOBILE = re.compile(r"(?<![\d-])01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?![\d-])")
_PERSONAL_MAIL = re.compile(
    r"[\w.+-]+@(?:gmail|naver|daum|hanmail|kakao|nate|hotmail|outlook|live|yahoo|icloud|me|proton(?:mail)?)\.[a-z.]{2,6}\b",
    re.I,
)


def _personal_contacts(body: str) -> list[str]:
    """그 본문에 사람 개인의 연락처가 있으면 그 종류(전화번호 · 메일 주소)."""
    kinds = []
    if _MOBILE.search(body or ""):
        kinds.append("전화번호")
    if _PERSONAL_MAIL.search(body or ""):
        kinds.append("메일 주소")
    return kinds


_BOLD = re.compile(r"\*\*([^*\n]{2,80})\*\*")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?:\d+[.)]\s*)?(.{2,80}?)\s*#*\s*$", re.MULTILINE)
_LIST_LEAD = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?:\*\*)?([^:：\n*|]{2,60}?)(?:\*\*)?\s*[:：]", re.MULTILINE)
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
_LETTERS = re.compile(r"[가-힣A-Za-z]")
#: 우리가 답 끝에 붙이는 대조표 — 그 뒤는 모델의 말이 아니다(`delegation._OUR_CHECKLIST` 와 같은 모양).
_OUR_CHECKLIST = re.compile(r"\n\s*\*\*(?:시킨 것 대조|Checklist)\*\*")


def _squash(text: str) -> str:
    return re.sub(r"[\s*_`'\"“”‘’·]+", "", str(text or "")).casefold()


def answer_names(answer: str) -> list[str]:
    """답이 **이름으로 적은 것**: 굵은 글씨 · 제목 · 「- 이름: 값」의 이름 · 표의 칸(머리줄 빼고)."""
    found: list[str] = []
    lines = answer.split("\n")
    headers: set[int] = {index for index in range(len(lines) - 1) if _TABLE_RULE.match(lines[index + 1])}
    for index, line in enumerate(lines):
        if index in headers or _TABLE_RULE.match(line) or not line.strip().startswith("|"):
            continue
        found.extend(cell.strip() for cell in line.strip().strip("|").split("|"))
    found.extend(match.group(1) for match in _BOLD.finditer(answer))
    found.extend(match.group(1) for match in _HEADING.finditer(answer))
    found.extend(match.group(1) for match in _LIST_LEAD.finditer(answer))
    out: list[str] = []
    for raw in found:
        name = _squash(raw)
        # 숫자 · 기호뿐이거나 한 글자면 이름이 아니다(숫자는 따로 센다).
        if len(name) < 2 or not _LETTERS.search(name) or name in out:
            continue
        out.append(name)
    return out[:200]


def _model_words(answer: str) -> str:
    """대조에 쓸 답 — 우리가 붙인 대조표 · 경고 줄은 뺀다."""
    text = str(answer or "")
    checklist = _OUR_CHECKLIST.search(text)
    if checklist:
        text = text[: checklist.start()]
    return "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("⚠"))


def _body_of(sources: Mapping[int, str] | Callable[[int], str] | None, step: int) -> str:
    if sources is None:
        return ""
    try:
        body = sources(step) if callable(sources) else sources.get(step, "")
    except Exception:  # noqa: BLE001 — 본문 하나 못 읽었다고 고르기를 멈추지 않는다
        return ""
    return body if isinstance(body, str) else ""


def pick_showcase_shots(
    steps: Iterable[Mapping[str, Any]],
    answer: str,
    sources: Mapping[int, str] | Callable[[int], str] | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """판이 끝난 뒤 **답이 기댄 페이지의 사진**을 고른다.

    `steps` 는 판 기록(`agent_trace.steps`) — 사진은 걸음 증거의 `shot_path` · `shot_url` · `shot_title` · `shot_at`.
    `sources` 는 걸음 번호 → **그 걸음이 읽은 본문**(사전 또는 함수). 본문을 모르는 걸음은 고를 근거가 없어 건너뛴다.

    돌려주는 것: `[{path, url, title, read_at, matched, step, contains}]` — `matched` 는 답의 숫자 · 이름 중 그 본문에 있던 개수,
    `contains` 는 그 본문에 있던 「needs 로 밝히면 나가도 되는 값」의 종류(전화번호 · 메일 주소).
    답과 겹친 것이 하나도 없는 페이지는 고르지 않는다 — 읽기만 하고 답이 안 기댄 화면은 증거가 아니다.
    """
    rows = [step for step in steps if isinstance(step, Mapping)]
    text = _model_words(answer)
    numbers = numbers_claimed_in(text)
    names = answer_names(text)
    if not numbers and not names:
        return []
    gated = _gated_sites(rows)
    best: dict[str, dict[str, Any]] = {}
    for step in rows:
        if not step.get("ok") or str(step.get("tool") or "") not in SHOT_TOOLS:
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), Mapping) else {}
        path = str(evidence.get("shot_path") or "")
        if not path or not os.path.isfile(path):
            continue
        url = str(evidence.get("shot_url") or evidence.get("url") or "")
        number = int(step.get("step") or 0)
        body = _body_of(sources, number)
        if not body:
            continue
        if private_reason(url, body=body, gated_sites=gated):
            continue
        squashed = _squash(body)
        hit_numbers = numbers & numbers_in_body({"text": body})
        hit_names = [name for name in names if name in squashed]
        matched = len(hit_numbers) + len(hit_names)
        if matched <= 0:
            continue
        _cleaned, hidden = refine(body)
        row = {
            "path": path,
            "url": url,
            "title": str(evidence.get("shot_title") or evidence.get("title") or "")[:200],
            "read_at": float(evidence.get("shot_at") or 0.0),
            "matched": matched,
            "step": number,
            # 전화번호 · 메일은 개인 것만 센다(`_personal_contacts`). 그 밖에 refine 이 가린 종류는 그대로 적는다.
            "contains": sorted(
                {str(item.get("kind")) for item in hidden if str(item.get("kind")) not in {"전화번호", "메일 주소"}}
                | set(_personal_contacts(body))
            ),
        }
        # 같은 페이지를 여러 번 읽었으면 한 장만 — 더 많이 겹친 것, 같으면 나중 것.
        key = url.split("#", 1)[0].rstrip("/") or path
        held = best.get(key)
        if held is None or (matched, number) >= (held["matched"], held["step"]):
            best[key] = row
    ranked = sorted(best.values(), key=lambda row: (-row["matched"], -row["step"]))
    return ranked[: max(0, int(limit))]


def shot_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    """`BrowserWorker.capture_read_shot` 의 결과 → 걸음 증거에 실을 칸."""
    if result.get("ok"):
        return {
            "shot_path": str(result.get("path") or "")[:1000],
            "shot_url": str(result.get("url") or "")[:1000],
            "shot_title": str(result.get("title") or "")[:200],
            "shot_at": round(float(result.get("at") or time.time()), 3),
            "shot_ms": int(result.get("ms") or 0),
        }
    return {"shot_error": str(result.get("reason") or "capture_failed")[:200], "shot_ms": int(result.get("ms") or 0)}
