"""잘 해낸 판 → 레시피 초안 (2026-10-20 · 확장 설계 P1 · `docs/EXTENSION_DESIGN_RECIPES_MCP.ko.md` §3-2).

판 기록(`agent_trace.steps`)에는 이미 연 주소 · 누른 것 · 채운 것과 그 뒤 화면 증거가 있다. 그것을 사람이 읽고 승인할 수 있는
레시피 초안으로 옮긴다. 모델을 부르지 않는 **결정론 변환**이다 — 같은 판은 같은 초안이 된다.

옮기는 규칙(설계 문서 그대로):
  * **잘 해낸 판만** 후보다 — 완료 · 시킨 것 n/n · 답 충돌 없음. 근거 없는 판을 레시피로 굳히지 않는다(`run_is_a_candidate`).
  * 판마다 다른 번호(`j5`)는 버리고 **다시 찾을 수 있는 셀렉터**로 적는다. 새 판은 브라우저가 적어 둔 후보(`selectors`)를,
    옛 판은 남은 이름(누른 것의 이름 · 칸의 안내문)으로 만든다.
  * 입력값은 칸으로 바꾼다(「닌텐도 스위치 2」 → `{query}`) · 주소의 추적 인자는 뗀다.
  * 바꾸는 걸음(누르기 · 키 누르기)에는 **그 걸음 직후 실제로 바뀐 것**에서 `expect` 를 뽑는다. 뽑을 증거가 없으면 초안을 쓰지
    않는다(로더 규칙 그대로 — 설계의 불변식 I2). 걸음을 빼고 쓰면 다른 절차가 된다.
  * 결과 목록에서 몇 번째를 연 뒤부터는 그 판의 **자료**에 달린 일이라 싣지 않는다 — 초안은 목록 화면까지다.
  * 같은 칸을 두 번째 채우는 자리에서 끊는다 — 질문 셋을 차례로 넣은 판은 한 바퀴가 곧 절차다.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, unquote_plus, urlencode, urlparse, urlunparse

#: 주소에서 떼는 추적 인자(이름 그대로 · 앞머리). 사람인 레시피가 `rec_idx` 하나만 남긴 판단과 같다 — 길을 정하지 않는 꼬리표다.
_TRACKING_EXACT = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl", "spm", "scm",
    "ref", "ref_src", "referrer", "source", "src", "from", "trk", "tracking", "NaPm", "nacn", "n_media", "n_query",
    "n_rank", "n_ad_group", "n_ad", "n_keyword_id", "n_keyword", "n_campaign_type", "n_contract", "n_ad_group_type",
    # 판마다 바뀌는 검색 꼬리표 — 남기면 다음 판 주소가 지난 판 검색에 묶인다(실측: 쿠팡 `traceId=mt09uel1`).
    "traceId", "traceid", "searchId", "search_id", "sessionId", "session_id", "requestId", "qid", "sid",
})
#: 검색엔진 — 레시피로 권할 사이트가 아니다(검색 도구가 따로 있다). `BrowserWorker._SEARCH_ENGINE_HOSTS` 와 같은 결.
_SEARCH_ENGINES = ("search.naver.com", "google.", "bing.com", "search.daum.net", "duckduckgo.com", "search.yahoo.")
_TRACKING_PREFIX = ("utm_",)

#: 판 기록에서 옮기는 도구.
_OPEN = "browser_open"
_SITE_SEARCH = "browser_site_search"
_CLICK = "browser_click"
_FILL = "browser_fill"
_PRESS = "browser_press"
#: 이 도구가 나오면 거기서 끊는다 — 그 판의 결과 목록(자료)에 달린 걸음이다.
_DATA_DEPENDENT = frozenset({"browser_open_result", "browser_pick_suggestion"})

#: 답에 붙는 경고 줄 — 이런 줄이 있는 판은 「잘 해낸 판」이 아니다.
_WARNING_LINE = re.compile(r"읽지 않고 적은|확인하지 못한|못 한 것|일부만|⚠|❌")


class DraftRefused(ValueError):
    """이 판으로는 초안을 쓰지 않는다 — 까닭을 문장으로 담는다(화면 · 측정 기록에 그대로 나간다)."""


def run_is_a_candidate(result: dict[str, Any]) -> str:
    """레시피 후보인 판이면 빈 문자열, 아니면 까닭."""
    if str(result.get("completion_state") or "") != "complete":
        return "끝까지 하지 못한 판"
    trace = result.get("agent_trace") if isinstance(result.get("agent_trace"), dict) else {}
    plan = trace.get("plan") if isinstance(trace.get("plan"), dict) else {}
    total = int(plan.get("total") or 0)
    if total and int(plan.get("met") or 0) < total:
        return "시킨 것을 다 채우지 못한 판"
    verification = trace.get("verification") if isinstance(trace.get("verification"), dict) else {}
    if str(verification.get("answer_conflict") or "").strip():
        return "답과 기록이 부딪친 판"
    if _WARNING_LINE.search(str(result.get("answer") or "")):
        return "답에 경고가 붙은 판"
    return ""


def strip_tracking(url: str) -> str:
    """주소에서 추적 인자를 뗀다. 나머지 인자와 순서는 그대로 둔다."""
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_EXACT and not key.lower().startswith(_TRACKING_PREFIX)
    ]
    return urlunparse(parts._replace(query=urlencode(kept, doseq=True, quote_via=quote)))


def site_of(host: str) -> str:
    """같은 사이트로 묶는 열쇠 — 끝의 두 마디(「co.kr」 같은 두 마디 끝은 세 마디)."""
    labels = [label for label in host.lower().split(".") if label]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "or", "go", "ac", "ne", "re", "com", "net", "org"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_local(host: str) -> bool:
    """이 PC · 사설망 · 예시 주소 — 사람이 다시 돌릴 사이트가 아니다(벤치 · 시험 앱)."""
    host = host.lower()
    return (
        host in {"localhost", "example.com", "example.org", "example.net"} or host.endswith((".localhost", ".test", ".example"))
        or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host)) or host.startswith("[")
    )


def _clean_label(text: str) -> str:
    """기록에 남은 칸 이름(「무엇이든 물어보세요… 안의 div」)에서 안내문만 남긴다."""
    text = re.sub(r"\s*안의\s+\w+$", "", str(text or "")).strip()
    return text.rstrip("…").rstrip(".").strip()


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _selectors_for(step: dict[str, Any], kind: str) -> list[str]:
    """이 걸음의 요소를 다시 찾을 셀렉터. 브라우저가 적은 후보가 먼저, 없으면(옛 판) 이름으로 만든다."""
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    recorded = [str(item) for item in (evidence.get("selectors") or []) if str(item).strip() and not str(item).startswith("…")]
    if recorded:
        return recorded
    if kind == "fill":
        name = _clean_label(str(evidence.get("field") or ""))
        if not name:
            return []
        # 옛 판은 안내문이 잘려 남는다 — 앞머리로 찾는다(`^=`).
        return [f"[placeholder^={_quoted(name)}]", f"[aria-label^={_quoted(name)}]", f"[data-placeholder^={_quoted(name)}]"]
    name = str(evidence.get("label") or "").strip()
    if not name or len(name) > 40:
        return []
    return [f"role=button[name={_quoted(name)}]", f"role=link[name={_quoted(name)}]", f"text={_quoted(name)}"]


def _templated(url: str, values: dict[str, str]) -> str:
    """주소 속 입력값을 칸으로 바꾼다 — 인코딩된 꼴(「%EB%8B%8C…」·「닌텐도+스위치」)까지 찾는다."""
    for value, slot in values.items():
        for spelled in {value, quote(value), quote_plus(value), quote(value, safe="")}:
            if spelled and spelled in url:
                url = url.replace(spelled, "{" + slot + "}")
    return url


def _query_values(url: str) -> list[str]:
    return [unquote_plus(value) for _key, value in parse_qsl(urlparse(url).query) if value.strip()]


def draft_from_run(prompt: str, steps: list[dict[str, Any]], *, job_id: str = "", at: float = 0.0, allow_local: bool = False) -> dict[str, Any]:
    """판 기록을 레시피 초안(dict)으로. 못 옮기면 `DraftRefused`(까닭).

    `allow_local` 은 이 PC · 시험 주소에서 한 판도 받는다(2026-10-28). 기본은 거절이다 — 벤치 · 시험 앱 판이 사람이 다시 돌릴 레시피로 굳으면 안 된다.
    사람이 직접 보여 준 시연을 시험 사이트로 끝에서 끝까지 재 볼 때만 켠다(`JARVIS_DEMO_ALLOW_LOCAL=1`).
    """
    kept = [step for step in steps if isinstance(step, dict) and step.get("ok")]
    recipe_steps: list[dict[str, Any]] = []
    targets: dict[str, list[str]] = {}
    target_of_ref: dict[str, str] = {}
    slots: dict[str, str] = {}
    hosts: list[str] = []
    last_url = ""
    filled_targets: set[str] = set()
    seen = 0

    def slot_for(value: str) -> str:
        if value not in slots:
            slots[value] = "query" if not slots else f"query{len(slots) + 1}"
        return slots[value]

    def note_host(url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host and host not in hosts:
            hosts.append(host)

    def target_for(step: dict[str, Any], kind: str, index: int) -> str:
        ref = str((step.get("arguments") or {}).get("ref") or "")
        if ref and ref in target_of_ref and kind != "fill":
            return target_of_ref[ref]
        selectors = _selectors_for(step, kind)
        if not selectors:
            raise DraftRefused(f"{index}번째 걸음({kind})의 요소를 다시 찾을 이름이 기록에 없습니다")
        for name, existing in targets.items():
            if existing == selectors:
                target_of_ref[ref] = name
                return name
        name = f"{kind}_{len(targets) + 1}"
        targets[name] = selectors
        if ref:
            target_of_ref[ref] = name
        return name

    for step in kept:
        tool = str(step.get("tool") or "")
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if tool in _DATA_DEPENDENT:
            break
        if tool not in {_OPEN, _SITE_SEARCH, _CLICK, _FILL, _PRESS}:
            continue
        seen += 1
        index = len(recipe_steps) + 1
        now_url = str(evidence.get("url") or "")
        if tool in {_OPEN, _SITE_SEARCH}:
            url = now_url or str(arguments.get("url") or "")
            if not url.startswith("http"):
                raise DraftRefused(f"{index}번째 걸음: 연 주소가 기록에 없습니다")
            if tool == _SITE_SEARCH and str(arguments.get("query") or "").strip():
                slot_for(str(arguments.get("query")).strip())
            recipe_steps.append({"do": "open", "url": strip_tracking(url)})
            note_host(url)
        elif tool == _FILL:
            target = target_for(step, "fill", index)
            if target in filled_targets:
                break  # 같은 칸을 다시 채운다 — 한 바퀴가 끝났다
            filled_targets.add(target)
            value = str(arguments.get("value") or "")
            recipe_steps.append({"do": "fill", "target": target, "value": "{" + slot_for(value) + "}" if value.strip() else ""})
        else:
            kind = "click" if tool == _CLICK else "press"
            target = target_for(step, kind, index)
            expect: dict[str, Any] = {}
            given = arguments.get("expect") if isinstance(arguments.get("expect"), dict) else {}
            if given.get("kind") and evidence.get("verified") is True:
                expect = dict(given)
            elif now_url and last_url and strip_tracking(now_url) != strip_tracking(last_url):
                expect = {"kind": "url_changes"}
            if not expect:
                raise DraftRefused(f"{index}번째 걸음({kind}) 뒤에 바뀐 것이 기록에 없어 확인 조건을 만들 수 없습니다")
            entry: dict[str, Any] = {"do": kind, "target": target, "expect": expect}
            if kind == "press":
                entry["key"] = str(arguments.get("key") or "Enter")
            recipe_steps.append(entry)
            if now_url:
                note_host(now_url)
        if now_url:
            last_url = now_url

    if not recipe_steps or recipe_steps[0]["do"] != "open":
        raise DraftRefused("주소를 여는 걸음으로 시작하지 않는 판입니다")
    # 헤맨 자리는 절차가 아니다 — 바로 다음 걸음도 주소 열기면 앞의 열기는 아무 일도 안 한 것이다(절대 주소로 다시 갔다).
    #   (실측: 2,623판을 옮겨 보니 petfinder 판 하나가 「열기」만 여섯 번이었다.)
    recipe_steps = [
        entry for position, entry in enumerate(recipe_steps)
        if not (entry["do"] == "open" and position + 1 < len(recipe_steps) and recipe_steps[position + 1]["do"] == "open")
    ]
    # 연 뒤에는 가로막는 창(쿠키 · 알림)을 먼저 치운다 — 엔진의 `dismiss` 는 거부 · 닫기 쪽만 누른다.
    #   (재생 실측: ign 판이 쿠키 동의 창에 가려 「Walkthrough」를 못 눌렀다.) 열기로 끝나는 초안에는 붙이지 않는다.
    with_dismiss: list[dict[str, Any]] = []
    for position, entry in enumerate(recipe_steps):
        with_dismiss.append(entry)
        if entry["do"] == "open" and position + 1 < len(recipe_steps):
            with_dismiss.append({"do": "dismiss"})
    recipe_steps = with_dismiss
    if any(_is_local(host) for host in hosts) and not allow_local:
        raise DraftRefused("이 PC · 시험 주소에서 한 판입니다")
    sites = {site_of(host) for host in hosts}
    if len(sites) != 1:
        raise DraftRefused(f"여러 사이트를 오간 판입니다({', '.join(sorted(sites))})")

    # 주소 속 입력값을 칸으로. 사람이 친 값이 주소에 그대로 들어간 꼴(검색 주소)이면 그 값이 곧 칸이다.
    if not slots:
        for value in _query_values(recipe_steps[0]["url"]):
            if len(value) >= 2 and value in (prompt or ""):
                slot_for(value)
                break
    for entry in recipe_steps:
        if entry["do"] == "open":
            entry["url"] = _templated(entry["url"], slots)

    mutating = any(entry["do"] in {"click", "fill", "press"} for entry in recipe_steps)
    site = sorted(sites)[0].split(".")[0]
    if not re.search(r"[A-Za-z]", site):
        site = "local"  # 127.0.0.1 → 「0」 같은 이름이 되지 않게(이 PC 주소를 받는 시험에서만 나온다)
    return {
        "name": site,
        "description": "",
        "hosts": sorted({host for host in hosts} | sites),
        "targets": targets,
        "actions": {
            "from_run": {
                "description": (prompt or "").strip().splitlines()[0][:80] if (prompt or "").strip() else "",
                "risk": "L2" if mutating else "L1",
                "steps": recipe_steps,
            }
        },
        "status": "draft",
        "_learned_from": {"kind": "run", "job_id": job_id, "at": at, "steps_seen": seen, "steps_kept": len(recipe_steps)},
        "_slots": {slot: value for value, slot in slots.items()},
    }


#: 배운 레시피 이름 꼬리 — 손자리에 들어 있는 레시피(사람인 · 네이버 블로그)와 섞이지 않게 한다(설계 §3-5).
LEARNED_SUFFIX = "_learned"


def learned_search_recipe(draft: dict[str, Any]) -> dict[str, Any] | None:
    """「검색 주소 하나 + 빈칸 하나({query})」 초안을 **배운 검색 레시피**로. 아니면 None.

    P0 재생 실측(설계 §10): 주소 열기 초안은 28/30 이 다시 돌았고(평균 1.2초) 누르는 절차는 1/14 였다 — 그래서 첫 판은
    잘 되는 쪽만 저장을 권한다. 이름에 「search」를 단 L0 절차라, 그 사이트에서 모델이 사이트 안 검색을 부르면
    엔진이 이 주소로 바로 연다(`SiteRecipeTools._auto_search_recipe` — 이미 있는 문). 읽기만 하므로 L0 이다.
    """
    action = (draft.get("actions") or {}).get("from_run") or {}
    steps = action.get("steps") or []
    if len(steps) != 1 or steps[0].get("do") != "open":
        return None
    url = str(steps[0].get("url") or "")
    host = (urlparse(url.replace("{query}", "x")).hostname or "").lower()
    if any(host == engine or host.startswith(engine) or host.endswith("." + engine.strip(".")) or ("." + engine) in "." + host
           for engine in _SEARCH_ENGINES):
        return None
    if url.count("{query}") != 1 or re.search(r"\{(?!query\})[a-zA-Z_]\w*\}", url):
        return None
    site = str(draft.get("name") or "").strip()
    if not site:
        return None
    return {
        "name": f"{site}{LEARNED_SUFFIX}",
        "description": f"{site} 검색 — 잘 끝난 판에서 배운 주소",
        "hosts": list(draft.get("hosts") or []),
        "actions": {
            "search": {
                "description": "검색어로 이 사이트의 검색 결과 화면을 바로 연다",
                "risk": "L0",
                "steps": [{"do": "open", "url": url}],
            }
        },
        "_learned_from": dict(draft.get("_learned_from") or {}),
        "_example_query": str((draft.get("_slots") or {}).get("query") or ""),
        # 사람에게 보일 사이트 이름 하나(「www.yes24.com, yes24.com」 두 번 대신 「yes24.com」 — 2026-10-20 첫 실사용 판).
        "_where": min((str(h) for h in (draft.get("hosts") or [])), key=len, default=site),
    }


def read_out(recipe: dict[str, Any], lang: str = "ko") -> str:
    """읽어 주기 — 사람이 승인하기 전에 **무엇을 하고 무엇을 확인하는지** 그대로 보인다(설계 §3-3)."""
    action = (recipe.get("actions") or {}).get("search") or {}
    url = str(((action.get("steps") or [{}])[0]).get("url") or "")
    hosts = str(recipe.get("_where") or ", ".join(recipe.get("hosts") or []))
    example = str(recipe.get("_example_query") or "")
    if lang == "en":
        return (
            f"Learned: search on {hosts} · 1 step · stays on {hosts}\n"
            f" 1. Open the search address with your words ({url.replace('{query}', '{search words}')})"
            f"  → check: the page opens on {hosts}\n"
            "Changes: nothing (read only)"
            + (f" · learned from this run (\"{example}\")" if example else "")
        )
    return (
        f"배운 것: {hosts} 검색 · 1걸음 · {hosts} 안에서만\n"
        f" 1. 찾을 말을 넣은 검색 주소를 연다 ({url.replace('{query}', '{찾을 말}')})"
        f"  → 확인: {hosts} 화면이 열린다\n"
        "바꾸는 것: 없음(읽기만)"
        + (f" · 배운 곳: 방금 판(「{example}」)" if example else "")
    )


#: 사람이 보여 준 레시피 이름 꼬리 — 배운 검색(`_learned`)과 나눈다.
DEMO_SUFFIX = "_demo"


def demo_recipe(draft: dict[str, Any], label: str = "", taken: dict[str, str] | None = None) -> dict[str, Any]:
    """사람 시연에서 옮긴 초안 → 저장할 레시피. 누르는 걸음이 있으면 L2 그대로(저장에 사람의 「응」이 승인이다).

    `taken` = 이미 있는 시연 레시피의 {이름: 설명}. 같은 설명(같은 일)이면 그 이름을 그대로 써서 **다시 보여 준 것이 옛것을 대신**하고,
    다른 일이면 `쿠팡2_demo` 처럼 번호를 붙여 옛것을 덮어쓰지 않는다(2026-10-28 · 같은 사이트의 두 번째 시연이 첫째를 지우던 자리).
    """
    action = dict((draft.get("actions") or {}).get("from_run") or {})
    site = str(draft.get("name") or "site")
    label = " ".join(str(label or "").split())[:60]
    action["description"] = label or f"{site} 에서 사람이 보여 준 절차"
    taken = taken or {}
    name = f"{site}{DEMO_SUFFIX}"
    if name in taken and taken[name] != action["description"]:
        number = 2
        while f"{site}{number}{DEMO_SUFFIX}" in taken and taken[f"{site}{number}{DEMO_SUFFIX}"] != action["description"]:
            number += 1
        name = f"{site}{number}{DEMO_SUFFIX}"
    return {
        "name": name,
        "description": action["description"],
        "hosts": list(draft.get("hosts") or []),
        "targets": dict(draft.get("targets") or {}),
        "actions": {"from_demo": action},
        "_learned_from": {**dict(draft.get("_learned_from") or {}), "kind": "demo"},
        "_example_query": str((draft.get("_slots") or {}).get("query") or ""),
        # 다시 돌려 볼 때 쓸 값 — 사람이 보여 준 그 말(칸 이름 → 값). 비밀번호 · 파일 칸은 애초에 기록에 없다.
        "_slots": {str(k): str(v) for k, v in (draft.get("_slots") or {}).items()},
        "_where": min((str(h) for h in (draft.get("hosts") or [])), key=len, default=site),
    }


_EXPECT_SAYS = {
    "url_changes": ("주소가 바뀐다", "the address changes"),
    "text_appears": ("「{value}」 글이 나타난다", "the text \"{value}\" appears"),
    "text_disappears": ("「{value}」 글이 사라진다", "the text \"{value}\" goes away"),
    "appears": ("그 요소가 나타난다", "the element appears"),
    "disappears": ("그 요소가 사라진다", "the element goes away"),
    "number_increases": ("숫자가 올라간다", "the number goes up"),
    "count_increases": ("개수가 늘어난다", "the count goes up"),
}


def _target_name(recipe: dict[str, Any], step: dict[str, Any]) -> str:
    targets = recipe.get("targets") or {}
    selectors = targets.get(str(step.get("target") or "")) or []
    for selector in selectors:
        found = re.search(r'(?:name|placeholder\^?|aria-label\^?|data-placeholder\^?)=\"([^\"]+)\"|text=\"([^\"]+)\"', selector)
        if found:
            return found.group(1) or found.group(2)
    return selectors[0] if selectors else "?"


def step_lines(recipe: dict[str, Any], action_name: str, lang: str = "ko") -> list[tuple[str, str]]:
    """걸음마다 (무엇을 하나, 무엇을 확인하나). 쿠키 창을 치우는 `dismiss` 는 사람에게 보이지 않는다 — 읽어 주기와 되돌려 보기가 같은 번호를 쓴다."""
    en = lang == "en"
    action = (recipe.get("actions") or {}).get(action_name) or {}
    out: list[tuple[str, str]] = []
    for step in (step for step in (action.get("steps") or []) if step.get("do") != "dismiss"):
        do = step.get("do")
        if do == "open":
            what = (f"Open {step.get('url', '').replace('{query}', '{search words}')}" if en
                    else f"{step.get('url', '').replace('{query}', '{찾을 말}')} 을 연다")
        elif do == "fill":
            value = str(step.get("value") or "").replace("{query}", "{search words}" if en else "{찾을 말}")
            what = f"Type {value} into 「{_target_name(recipe, step)}」" if en else f"「{_target_name(recipe, step)}」 칸에 {value} 을 넣는다"
        elif do == "press":
            what = f"Press {step.get('key', 'Enter')}" if en else f"{step.get('key', 'Enter')} 를 누른다"
        elif do == "click":
            what = f"Click 「{_target_name(recipe, step)}」" if en else f"「{_target_name(recipe, step)}」 을 누른다"
        else:
            what = str(do)
        expect = step.get("expect") or {}
        check = ""
        if expect.get("kind"):
            ko, en_text = _EXPECT_SAYS.get(str(expect["kind"]), (str(expect["kind"]), str(expect["kind"])))
            said = (en_text if en else ko).replace("{value}", str(expect.get("value") or ""))
            check = f"  → check: {said}" if en else f"  → 확인: {said}"
        out.append((what, check))
    return out


def read_out_steps(recipe: dict[str, Any], action_name: str, lang: str = "ko") -> str:
    """여러 걸음 레시피의 읽어 주기 — 걸음마다 무엇을 하고 **무엇을 확인하는지**(설계 §3-3 · 이 카드의 핵심은 「확인」 줄)."""
    en = lang == "en"
    action = (recipe.get("actions") or {}).get(action_name) or {}
    steps = [step for step in (action.get("steps") or []) if step.get("do") != "dismiss"]
    where = str(recipe.get("_where") or ", ".join(recipe.get("hosts") or []))
    lines = [f" {number}. {what}{check}" for number, (what, check) in enumerate(step_lines(recipe, action_name, lang), 1)]
    changes = any(step.get("do") in {"click", "fill", "press"} for step in steps)
    head = (f"Learned: {action.get('description') or where} · {len(steps)} steps · stays on {where}" if en
            else f"배운 것: {action.get('description') or where} · {len(steps)}걸음 · {where} 안에서만")
    tail = (("Changes: it clicks and types on the page — saving needs your OK" if changes else "Changes: nothing (read only)") if en
            else ("바꾸는 것: 화면에서 누르고 입력합니다 — 저장하려면 확인이 필요합니다" if changes else "바꾸는 것: 없음(읽기만)"))
    # 바꾸는 것 줄은 한 줄 비워 둔다 — 대화 화면(마크다운)에서 마지막 걸음 줄에 이어 붙어 보이지 않게(2026-10-28 화면 확인).
    return "\n".join([head, *lines]) + "\n\n" + tail


#: 누르기 · 고르기 계열 — 여기서 거듭 실패했으면 「막혔다」(2026-10-20 실측: 2,632판 중 53판 · 실사용 약 19판).
_HANDS = frozenset({"browser_click", "browser_select_option", "browser_fill", "browser_press", "browser_pick_suggestion"})


def stuck_on_a_site(result: dict[str, Any]) -> str:
    """끝까지 못 한 판이 **어느 사이트에서 누르기 · 고르기로 막혔는지**(호스트). 아니면 빈 문자열.

    막힘 = 누르기 · 고르기 실패 2번 이상, 또는 「사이트 정렬 · 필터로 보기」를 못 채움. 이 PC · 시험 주소 · 검색엔진은 뺀다.
    """
    if str(result.get("completion_state") or "") == "complete":
        return ""
    trace = result.get("agent_trace") if isinstance(result.get("agent_trace"), dict) else {}
    steps = [step for step in (trace.get("steps") or []) if isinstance(step, dict)]
    failed = [step for step in steps if step.get("tool") in _HANDS and not step.get("ok")]
    plan = trace.get("plan") if isinstance(trace.get("plan"), dict) else {}
    filter_unmet = any(item.get("kind") == "filter" and not item.get("met") for item in (plan.get("items") or []) if isinstance(item, dict))
    if len(failed) < 2 and not filter_unmet:
        return ""
    for step in reversed(steps):
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        url = str(evidence.get("url") or "")
        if url.startswith("http"):
            host = (urlparse(url).hostname or "").lower()
            if not host or _is_local(host) or any(engine in host for engine in _SEARCH_ENGINES):
                return ""
            return host
    return ""


def demo_offer_text(host: str, lang: str = "ko") -> str:
    """막힌 판의 답 끝 한 줄 — 창은 건드리지 않는다(대표 10-20: 「안 될 때마다 크롬을 앞으로 띄우는 건 반대」)."""
    if lang == "en":
        return (f"\n\n---\nI got stuck clicking or choosing on {host}. Show me once and I'll do it the same way next time. "
                "Want to show me? (yes / no)")
    return (f"\n\n---\n{host} 에서 누르거나 고르는 데서 막혔습니다. 한 번 보여 주시면 다음부터 그대로 하겠습니다. "
            "보여 주시겠어요? (응 / 아니)")


#: 손자리 크롬의 그 페이지 구석에 잠깐 뜨는 알림 — 누르기를 가로채지 않고(pointer-events: none) 저절로 사라진다. 창은 안 올린다.
HINT_JS = """text => {
  const id = 'sonjari-stuck-hint';
  const old = document.getElementById(id);
  if (old) old.remove();
  if (!document.documentElement) return false;
  const box = document.createElement('div');
  box.id = id;
  box.textContent = text;
  box.setAttribute('style', 'position:fixed;right:16px;bottom:16px;max-width:340px;z-index:2147483647;'
    + 'background:rgba(30,30,30,.92);color:#fff;font:500 13px/1.5 sans-serif;padding:10px 14px;border-radius:10px;'
    + 'box-shadow:0 2px 10px rgba(0,0,0,.3);pointer-events:none;transition:opacity .6s;');
  document.documentElement.appendChild(box);
  setTimeout(() => { box.style.opacity = '0'; setTimeout(() => box.remove(), 700); }, 30000);
  return true;
}"""
