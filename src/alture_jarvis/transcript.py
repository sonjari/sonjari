"""모델 창에 무엇을 남길지 — **시킨 일은 절대 안 버린다.**

## 무엇이 있었나 (2026-08-20, 쿠팡 판)

쿠팡에서 그래픽카드를 로켓배송만 골라 비교하라고 시켰다. 자비스는 25걸음을 잘
돌았다 — 쿠팡을 열고, 검색하고, 필터를 누르고, 상품 상세를 넷이나 열어 읽었다.
그리고 마지막 정리에서 **자기 시스템 프롬프트를 요약해서** 뱉었다.

    "네, 알겠습니다. 제공해주신 지침을 완벽하게 숙지했습니다…"

원인은 모델이 아니었다. 예전 `_bounded_transcript` 는 **새 것부터 담다가 예산이
떨어지면 멈췄다.** 도구 결과가 176,021자였고 예산은 110,000자였으니, 못 담은 앞쪽이
통째로 잘렸다 — 그 앞쪽 첫 줄이 **사용자가 시킨 일**이었다. 정리 시점에 모델에게
남은 것은 시스템 프롬프트와 최근 도구 결과와 "정리해라" 한 줄뿐이었다.
시킨 일이 사라졌으니 시스템 프롬프트를 요약한 것이다. 모델은 있는 것을 답했다.

## 그래서 규칙 셋

  1. **시킨 일은 고정이다.** 무슨 일이 있어도 첫 사용자 메시지는 남는다.
  2. **길 찾기 결과는 접는다.** 스냅샷·요소 찾기·누르기는 *그때* 어디를 누를지
     정하려고 찍은 것이지 정리 단계의 근거가 아니다. 오래된 것부터 한 줄로 접어
     자리를 비운다 — 통째로 버리는 것보다 낫다(무엇을 했는지는 남는다).
  3. **근거는 오래 남긴다.** 본문 추출·파일 읽기는 답의 근거다. 접기는 마지막이다.

## 왜 앞에서 자르는 것이 비싼가

Ollama 는 프리픽스 캐시를 쓴다(실측: 같은 앞부분 재사용 시 prefill 2.64s → 0.24s,
11배). 앞을 자르면 그 캐시가 통째로 무효가 되어 그때부터 매 스텝 전부 다시
prefill 한다. 접기는 그 절벽을 **뒤로 미룬다** — 접힌 줄은 짧아도 자리를 지키므로
앞부분이 계속 같기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

_LOG = logging.getLogger(__name__)

# 한글·코드 섞인 우리 전사에서 **약 2자 = 1토큰**(2026-08-10 실측: 20,000자 → 10,024토큰).
CHARS_PER_TOKEN = 2

# 길 찾기 도구. 이것들의 결과는 "그 순간 화면이 어떻게 생겼나"이지 답의 근거가 아니다.
# ★ 새 길 찾기 도구를 만들면 여기 넣어라. 안 넣으면 그 결과가 근거인 척 창을 먹는다.
NAVIGATION_TOOLS = frozenset({
    "browser_snapshot", "browser_find", "browser_click", "browser_click_confirmed",
    "browser_scroll", "browser_back", "browser_tabs", "browser_switch_tab",
    "browser_wait", "browser_hover", "browser_press", "browser_probe_frames", "browser_click_at",
    "browser_links", "browser_load_more", "browser_dismiss_dialog",
    "ui_find_target", "ui_click_target", "ui_verify",
    "windows_uia_snapshot", "windows_focus_window", "windows_list_open_windows",
})

CODE_TOOLS = frozenset({
    "local_index_codebase", "local_list_directory", "local_search_files",
    "local_read_text_file", "local_write_file", "local_apply_edit",
    "local_run_project_command",
})


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ── 읽은 페이지는 접어도 **첫머리를 남긴다** (2026-10-11) ───────────────────────────
#
# 규칙 3(「근거는 오래 남긴다」)은 창이 넉넉할 때만 지켜졌다. 16GB 조건(창 49,152)에서는 고정 앞부분이 창의 57% 라
# 페이지 하나를 읽으면 앞서 읽은 페이지가 접힌다. 접힌 줄에는 「읽었다」만 있고 읽은 값이 없었다:
#
#     가격 조사 판 dea4dec2 — 세 가게의 상품 페이지를 차례로 열어 읽고, 엑셀을 쓸 때는 두 가게 줄을 「확인 불가」로 적었다
#
# 게다가 긴 결과는 접히기 전에 먼저 잘려서(닫는 괄호가 없어 풀리지 않는다) 제목 · 주소도 안 남았다.
#
# 본문을 읽는 도구의 결과는 접을 때 본문 첫머리를 같이 남긴다. 크기는 줄↔페이지 대조가 「그 페이지의 주 항목이 있는 자리」로
# 보는 앞자리(`answer_claims._ROW_BODY_HEAD_CHARS`)와 **쌍이다** — 상품 이름과 값은 거기 있다(교보 실측 09-28: 제목 33자째 ·
# 값 260~680자째). 잘린 결과에서도 꺼낸다. 길 찾기 결과는 예전처럼 한 줄이다.
#
# ※ 값이 첫머리 밖에 있는 페이지에서는 여전히 사라진다. 그때는 접힌 줄이 「다시 읽어라」고 말한다.
FOLDED_READ_HEAD_CHARS = 1_200
#: 본문을 읽는 도구 — `transcript_policy._PAGE_READ_TOOLS` 와 같은 목록이다(시험이 지킨다).
PAGE_READ_TOOLS = frozenset({"browser_extract", "browser_read"})
# ★ 주소도 남긴다 (같은 날 · 같은 조건의 판 46f45f17 · b24a0b1e). 접힌 줄에 제목만 있으니 표의 「읽은 페이지 주소」 칸에
#   모델이 **기억으로 지은 주소**(`prod.danawa.com/info/111145485` — 404)를 적었다. 같은 과제 두 판에서 두 번 다였다.
#   주소가 길면(G마켓은 검색 추적 값이 붙어 900자) 뒤에 붙은 값을 떼고 앞쪽만 남긴다 — 상품을 가리키는 것은 앞쪽이다.
FOLDED_READ_ADDRESS_CHARS = 300
#: 도구가 뽑아 둔 「이 페이지의 주 항목 값」 한 줄을 접힌 줄에 남길 때의 상한(글자).
FOLDED_READ_MAIN_VALUES_CHARS = 400
# ★ 접힌 **목록**에는 앞쪽 몇 건의 주소를 남긴다 (2026-10-13 · 밖에서 받은 가설을 코드로 확인).
#   「검색 결과 페이지가 버려질 때 한 줄 요약에 상품 링크가 없으면 에이전트는 상품으로 돌아갈 길이 없다.」 접힌 길 찾기 결과는
#   「결과 N자는 뺐다. 다시 찍어라」 한 줄이었고 받아 둔 목록은 통째로 사라졌다. 가게 셋을 먼저 다 검색하고 나중에 상품을 여는
#   판에서는 첫 가게의 목록이 접힌 뒤 검색부터 다시 해야 했다 — 창 32K 의 틀린 29칸 중 19칸이 「상품 페이지까지 못 감」.
#   순위가 아니라 **주소**를 남긴다: `browser_open_result` 의 순위는 도구가 마지막으로 받은 목록의 것이라, 그 뒤에 다른 곳을
#   검색했으면 옛 순위는 엉뚱한 것을 연다. `JARVIS_FOLD_KEEPS_RESULT_LINKS=0` 으로 끈다(넣기 전후를 나란히 재려고).
FOLDED_LIST_KEEP = 5
FOLDED_LIST_TITLE_CHARS = 44
FOLDED_LIST_ADDRESS_CHARS = 120


def _keeps_result_links() -> bool:
    try:
        from .config import setting

        return str(setting("JARVIS_FOLD_KEEPS_RESULT_LINKS", "1")).strip().lower() not in {"0", "false", "off", "no"}
    except Exception:  # noqa: BLE001 — 스위치를 못 읽으면 켠 것으로
        return True


def _top_links(results: Any) -> list[str]:
    """목록의 앞쪽 몇 건을 「제목 — 주소」 줄로. 주소가 없는 줄은 건너뛴다."""
    lines: list[str] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        address = _short_address(_text(item.get("url")) or _text(item.get("href")), FOLDED_LIST_ADDRESS_CHARS)
        if not address.startswith("http"):
            continue
        lines.append(f"- {_text(item.get('title')).strip()[:FOLDED_LIST_TITLE_CHARS]} — {address}")
        if len(lines) >= FOLDED_LIST_KEEP:
            break
    return lines


def _short_address(url: str, limit: int = FOLDED_READ_ADDRESS_CHARS) -> str:
    """주소가 `limit` 자를 넘으면 그 안의 마지막 `&` 앞까지만. 물음표 뒤에 `&` 가 없으면 `limit` 자에서 끊는다."""
    url = str(url or "").strip()
    if len(url) <= limit:
        return url
    query = url.find("?")
    cut = url.rfind("&", 0, limit)
    return url[:cut] if 0 < query < cut else url[:limit]

_JSON_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


def _json_string_after(raw: str, key: str, limit: int) -> str:
    """JSON 글에서 `"key": "` 뒤의 문자열을 앞에서부터 `limit` 자까지 꺼낸다 — 글이 잘려 풀리지 않을 때 쓴다."""
    start = raw.find(f'"{key}": "')
    if start < 0:
        return ""
    index = start + len(key) + 5
    out: list[str] = []
    while index < len(raw) and len(out) < limit:
        char = raw[index]
        if char == '"':
            break
        if char != "\\":
            out.append(char)
            index += 1
            continue
        following = raw[index + 1:index + 2]
        if not following:
            break
        if following == "u":
            try:
                out.append(chr(int(raw[index + 2:index + 6], 16)))
            except ValueError:
                break
            index += 6
            continue
        out.append(_JSON_ESCAPES.get(following, following))
        index += 2
    return "".join(out)


def _top_links_from_cut(raw: str) -> tuple[list[str], int]:
    """길어서 **잘린** 결과 글에서 목록의 앞쪽 몇 건을 꺼낸다 — (줄들, 글에 보이는 결과 수). 풀리지 않는 JSON 이라 글로 훑는다.

    결과는 접히기 전에 길이 한도로 먼저 잘린다(`tool_result_max`). 작은 창에서는 그 한도가 낮아 검색 결과가 자주 잘리고,
    잘린 글은 통째로 풀리지 않는다 — 그대로 두면 링크를 남기는 일이 정작 작은 창에서 안 돈다.
    """
    start = raw.find('"results": [')
    if start < 0:
        return [], 0
    items: list[dict[str, Any]] = []
    at = start
    while len(items) < 60:
        title_at = raw.find('"title": "', at)
        if title_at < 0:
            break
        url_at = raw.find('"url": "', title_at)
        next_title = raw.find('"title": "', title_at + 10)
        if url_at < 0 or (0 <= next_title < url_at):
            at = title_at + 10
            continue
        items.append({"title": _json_string_after(raw[title_at:], "title", FOLDED_LIST_TITLE_CHARS),
                      "url": _json_string_after(raw[url_at:], "url", 600)})
        at = url_at + 8
    return _top_links(items), len(items)


def fold(message: dict[str, Any]) -> dict[str, Any]:
    """도구 결과 하나를 **접는다.** 무엇을 했는지는 남기고 본문을 뺀다 — 읽은 페이지는 첫머리를 남긴다(위의 설명).

    접었다는 사실을 적는 이유: 안 적으면 모델은 그 걸음이 **없었다고** 여긴다.
    다시 찍으라고 알려 주는 것까지가 이 줄의 일이다.
    """
    name = _text(message.get("tool_name")) or "도구"
    raw = _text(message.get("content"))
    where = head = address = main_values = ""
    links: list[str] = []
    listed = 0
    keeps_head = name in PAGE_READ_TOOLS
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        # ★ 도구 결과는 칸이 **한 겹**이다(`{"ok": …, "url": …, "title": …, "text": …}` — `agent` 가 그대로 싣는다).
        #   예전 코드는 `result` 안만 봐서 제목이 한 번도 안 남았고, 첫머리 남기기도 첫 판에서는 같은 자리만 봤다
        #   (시험 표본을 두 겹으로 지어 통과했다 — 같은 날 저녁에 실제 모양으로 바로잡음). 두 모양을 다 본다.
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else parsed
        where = _text(result.get("title")) or _text(result.get("url")) or _text(result.get("path"))
        if keeps_head:
            head = _text(result.get("text"))[:FOLDED_READ_HEAD_CHARS]
            address = _text(result.get("url"))
            main_values = _text(parsed.get("page_main_values")) or _text(result.get("page_main_values"))
        elif _keeps_result_links():
            links = _top_links(result.get("results"))
            listed = len(result.get("results")) if isinstance(result.get("results"), list) else 0
    elif not keeps_head and _keeps_result_links():
        links, listed = _top_links_from_cut(raw)
        where = _json_string_after(raw, "title", 60)
    elif keeps_head:
        # 길어서 잘린 결과 — 풀리지 않아도 제목과 본문 첫머리는 꺼낸다.
        address = _json_string_after(raw, "url", FOLDED_READ_ADDRESS_CHARS + 1)
        where = _json_string_after(raw, "title", 60) or address
        head = _json_string_after(raw, "text", FOLDED_READ_HEAD_CHARS)
        main_values = _json_string_after(raw, "page_main_values", FOLDED_READ_MAIN_VALUES_CHARS)
    tail = f" · {where[:60]}" if where else ""
    address = _short_address(address)
    if address and address != where:
        tail += f" · {address}"
    folded = {key: value for key, value in message.items() if key != "content"}
    if head.strip():
        # 도구가 그 페이지 첫머리에서 뽑아 둔 주 항목 값(판매가 · 적립 — `page_values`)이 있으면 본문보다 앞에 둔다.
        values = f"\n[이 페이지의 주 항목 값] {main_values.strip()[:FOLDED_READ_MAIN_VALUES_CHARS]}" if main_values.strip() else ""
        folded["content"] = (
            f"[접음] {name}{tail} — 본문 {len(raw):,}자 가운데 첫머리 {len(head):,}자만 남겼다(창을 비우려고). "
            f"아래에 없는 것이 필요하면 그 페이지를 다시 읽어라.{values}\n{head.strip()}"
        )
        return folded
    if links:
        folded["content"] = (
            f"[접음] {name}{tail} — 결과 {len(raw):,}자는 창을 비우려고 뺐다. 받은 목록{f' {listed}건' if parsed is not None else ''} 가운데 "
            f"앞 {len(links)}건의 주소는 남긴다 — "
            "이 항목으로 가려면 다시 검색하지 말고 그 주소를 browser_open 으로 열어라"
            "(순위로 여는 browser_open_result 는 **마지막으로 받은 목록**에만 맞는다).\n" + "\n".join(links)
        )
        return folded
    folded["content"] = (
        f"[접음] {name}{tail} — 결과 {len(raw):,}자는 창을 비우려고 뺐다. "
        "지금 화면이 필요하면 다시 찍어라."
    )
    return folded


# ── 버리기 전에 한 줄 (2026-10-12) ────────────────────────────────────────────────
#
# 접기는 「버리는 대신 접는다」였는데, **접어도 안 들어가면 그보다 오래된 것은 통째로 버렸다**(`bounded` 의 `stop`).
# 창이 넉넉하면 거기까지 갈 일이 없다. 창 32,768 에서는 고정 앞부분이 1만 3천여 토큰이라 걸음에 쓸 자리가 1만 4천 자쯤이고,
# 읽은 화면 하나에 8,600자를 줬다. 가격 조사 세 판(공식 9B · 그날 광고 카드 규칙을 넣은 뒤):
#
#     3fe1a676  다나와 → 11번가 → 다나와 → 11번가 ×5 → 「파일 만들 차례」 → 엑셀에 11번가 한 줄
#     2630b50f  11번가 상품 화면을 읽고도 마지막 답이 「11번가와 G마켓에서도 검색을 진행할 수 있지만」
#     세 판 모두 G마켓에는 가 보지도 못했다
#
# 3fe1a676 의 걸음을 다시 쌓아 마지막 호출을 재생하니 걸음 1~17 이 통째로 없었다 — 읽은 화면 넷(다나와 둘 · 11번가 둘)이
# 그 안에 있었다. 모델은 다나와를 읽은 적이 없는 것으로 알고 엑셀을 썼다. 「작은 모델이 가게를 헷갈린다」가 아니라
# 우리가 지웠다.
#
# 버리게 된 **읽은 화면**은 한 줄(제목 · 주소 · 도구가 뽑아 둔 주 항목 값)로 줄여 이번 판 맥락(요청 메시지 앞)에 모아 둔다.
# 그 자리는 예산에 밀려나지 않는다. 길 찾기 걸음(검색 · 열기)은 예전처럼 버린다 — 남길 값이 없다.
# 같은 주소는 마지막 한 줄만 남긴다. 줄 묶음의 크기만큼 걸음에 줄 자리를 먼저 뺀다(넘치지 않게).
#
# ※ 값이 화면 첫머리 밖에 있고 도구가 값을 못 뽑는 사이트에서는 그 줄에 제목 · 주소 · 본문 첫 160자만 남는다 —
#   「읽은 적이 있다」는 것은 알지만 값은 다시 읽어야 한다.
READ_LEDGER_OPEN = "<앞서-읽은-화면>"
READ_LEDGER_CLOSE = "</앞서-읽은-화면>"
READ_LEDGER_LEAD = (
    "이 일에서 **이미 읽은** 화면이다 — 창을 비우려고 본문을 뺐다. 여기 값이 있으면 그 화면을 다시 열지 말고 이 값을 써라."
)
# ★ 작은 창에서는 **늘** 보인다 (같은 날 밤). 방을 넓힌 뒤(지침을 손에 맞춤) 읽은 화면이 밀려나지 않았는데도 공식 9B ·
#   창 32K 세 판 중 둘이 다나와 → 11번가를 읽고 **다나와로 되돌아갔다**(ea9fec69 · 64f9f86f). 한 판은 다섯 걸음 전에 읽은
#   가게를 두고 「다나와와 G마켓은 아직 못 봤습니다」라고 답했다. 화면 글 8천 자 두 덩이가 눈앞에 있어도 「어디까지 했나」를
#   스스로 추리지 못했다. 하네스는 무엇을 읽었는지 안다(그래서 되돌아가는 손은 막았다) — 막기만 하고 알려 주지는 않았다.
#   부르는 쪽이 `pin_reads` 를 주면 담긴 화면까지 다 적는다. 큰 창은 예전대로 밀려난 것만 적는다(그 모델들은 놓치지 않았다).
READ_LEDGER_PINNED_LEAD = (
    "이 일에서 **지금까지 읽은** 화면이다(아래로 갈수록 나중). 여기 있는 화면은 다시 열지 마라 — 값이 여기 있으면 이 값을 써라. "
    "읽어야 할 곳이 남았으면 아직 여기 없는 곳으로 가고, 다 읽었으면 결과를 정리해라."
)
#: 한 줄 묶음 전체의 상한(글자) — 묶음이 걸음에 줄 자리를 도로 채우면 줄인 뜻이 없다.
READ_LEDGER_MAX_CHARS = 3_000
READ_LEDGER_HEAD_CHARS = 160
READ_LEDGER_VALUES_CHARS = 300
_FOLDED_VALUES_MARK = "[이 페이지의 주 항목 값] "


def read_line(message: dict[str, Any]) -> tuple[str, str]:
    """읽은 화면 하나의 한 줄과, 같은 화면을 가리는 열쇠(주소). 남길 것이 없으면(못 읽은 걸음) 빈 글 둘."""
    raw = _text(message.get("content"))
    title = address = values = head = ""
    if raw.startswith("[접음]"):
        # 계단식 접기가 대화에 남긴 접힌 줄 — 그 줄의 앞머리(도구 · 제목 · 주소)와 값 줄을 다시 쓴다.
        first, _, rest_text = raw.partition("\n")
        pieces = first.split(" — ", 1)[0].split(" · ")[1:]
        title = pieces[0] if pieces else ""
        address = pieces[-1] if len(pieces) > 1 else ""
        if rest_text.startswith(_FOLDED_VALUES_MARK):
            values = rest_text[len(_FOLDED_VALUES_MARK):].split("\n", 1)[0]
    else:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            result = parsed.get("result") if isinstance(parsed.get("result"), dict) else parsed
            if result.get("ok") is False or parsed.get("ok") is False:
                return "", ""
            title, address = _text(result.get("title")), _text(result.get("url"))
            values = _text(parsed.get("page_main_values")) or _text(result.get("page_main_values"))
            head = _text(result.get("text"))[:READ_LEDGER_HEAD_CHARS]
        else:
            # 길어서 잘린 결과 — 풀리지 않아도 꺼낸다(`fold` 와 같은 길).
            address = _json_string_after(raw, "url", FOLDED_READ_ADDRESS_CHARS + 1)
            title = _json_string_after(raw, "title", 60)
            values = _json_string_after(raw, "page_main_values", READ_LEDGER_VALUES_CHARS)
            head = _json_string_after(raw, "text", READ_LEDGER_HEAD_CHARS)
    title, address = " ".join(title.split())[:60], _short_address(address)
    if not (title or address):
        return "", ""
    parts = [part for part in (title, address) if part]
    if values.strip():
        # 값 뒤에 붙은 풀이(「(도구가 이 페이지 첫머리에서 읽은 …)」)는 줄마다 되풀이하지 않는다 — 묶음 첫 줄이 말한다.
        values = values.split(" (도구가 이 페이지", 1)[0]
        parts.append("값: " + " ".join(values.split())[:READ_LEDGER_VALUES_CHARS])
    elif head.strip():
        parts.append("첫머리: " + " ".join(head.split()))
    return "- " + " · ".join(parts), address or title


def read_ledger(rest: list[dict[str, Any]], tool_positions: list[int], chosen: set[int], *, pin_all: bool = False) -> str:
    """담기지 못한 읽은 화면들의 한 줄 묶음(오래된 것부터). 버려진 것이 없으면 빈 글. `pin_all` 이면 담긴 화면도 적는다."""
    lines: list[str] = []
    seen: set[str] = set()
    size = 0
    for index in reversed(tool_positions):  # 새 것부터 고르고(상한에 걸리면 오래된 쪽이 빠진다), 적을 때는 뒤집는다.
        if index in chosen and not pin_all:
            continue
        item = rest[index]
        if _text(item.get("tool_name")) not in PAGE_READ_TOOLS:
            continue
        line, key = read_line(item)
        if not line or key in seen:
            continue
        if size + len(line) + 1 > READ_LEDGER_MAX_CHARS:
            break
        seen.add(key)
        lines.append(line)
        size += len(line) + 1
    if not lines:
        return ""
    lead = READ_LEDGER_PINNED_LEAD if pin_all else READ_LEDGER_LEAD
    return "\n".join([READ_LEDGER_OPEN, lead, *reversed(lines), READ_LEDGER_CLOSE])


# ── 바로 앞 판의 답도 버리지 않는다 (2026-10-12 저녁) ─────────────────────────────────
#
# 작은 카드(4B · 창 32K)로 쓰는 사람의 말: 「한 판은 잘한다. 그다음 질문에서 무너진다」. 이 모듈이 지키는 것은 맨 처음
# 요청과 이번 요청뿐이고, **그 사이의 대화(바로 앞 판의 답)** 는 오래된 것이라 걸음이 쌓이면 제일 먼저 버려진다.
# 창별로 흉내 내니(앞 답 3,000자 · 이번 판이 가게를 하나씩 읽음) 앞 답이 사라지는 때가 이랬다:
#
#     9B · 창 32K   화면 하나를 읽으면     4B · 창 32K   둘     27B 압축판 · 48K   셋     64K 이상   안 사라짐
#
# 「그중에 둘째 것만 더 찾아 줘」의 「그중」이 화면 한두 장 만에 지워진다. 버리게 되면 앞 질문과 앞 답의 머리 · 꼬리를
# 이번 판 맥락에 남긴다(꼬리를 남기는 까닭: 만든 파일의 경로가 보통 답의 끝에 있고, 다음 질문은 「그 파일에 …」다).
# 앞 답이 대화에 그대로 담겼으면 아무것도 하지 않는다 — 넉넉한 창에서는 일하지 않는다.
PRIOR_TURN_OPEN = "<바로-앞-대화>"
PRIOR_TURN_CLOSE = "</바로-앞-대화>"
PRIOR_TURN_LEAD = (
    "창을 비우려고 바로 앞 대화의 원문을 뺐다. 지금 요청이 「그것 · 그중 · 아까 · 그 파일」처럼 앞을 가리키면 아래를 본다."
)
PRIOR_TURN_ASK_CHARS = 400
PRIOR_TURN_ANSWER_HEAD_CHARS = 1_400
PRIOR_TURN_ANSWER_TAIL_CHARS = 600
# ★ 같은 날 밤, 작은 카드로 쓰는 사람의 실제 순서를 들었다(4B · 창 32K):
#     ① 어떤 회사의 홍보 전략을 깊이 알려 달라 → 잘 답함   ② 내 전략과 견주어 달라 → 같은 말을 되풀이
#     ③ 그것을 문서 파일로 → 백지 파일             ④ 하얗다, 다시 → 「그 홍보 전략을 다시 설명해 주시겠어요?」
#   ④에 필요했던 것은 바로 앞 판(③ 「저장했습니다」)이 아니라 **세 판 앞**(①의 답)이었다. 바로 앞 판만 지켜서는 같은
#   되물음이 난다. 그 앞의 두 판도 질문과 답의 첫머리를 짧게 남긴다 — 무엇을 이미 말했는지는 알게.
#   ※ 짧게 남긴 첫머리로 그 답 전체를 다시 쓸 수는 없다. 「이미 답한 적이 있다」는 것과 그 방향까지다.
PRIOR_TURNS_OLDER_MAX = 2
PRIOR_TURN_OLDER_ASK_CHARS = 160
PRIOR_TURN_OLDER_ANSWER_CHARS = 400


def _prior_ask_before(rest: list[dict[str, Any]], answer_at: int) -> str:
    """그 답을 부른 질문의 글(판 맥락은 뗀다). 대화의 맨 처음 요청이면 `rest` 에 없다(따로 지킨다) — 빈 글."""
    for index in range(answer_at - 1, -1, -1):
        item = rest[index]
        if item.get("role") == "assistant" and not item.get("tool_calls") and _text(item.get("content")).strip():
            return ""  # 앞 판의 답에 닿았다 — 이 답의 질문은 `rest` 밖(맨 처음 요청)이다
        if item.get("role") == "user" and not _text(item.get("content")).startswith(SYSTEM_NOTE_PREFIX):
            ask = _text(item.get("content"))
            return ask[_job_context_chars(item):].strip()
    return ""


def prior_turn_block(rest: list[dict[str, Any]], job_index: int | None, chosen: set[int]) -> str:
    """이번 요청 앞의 답들 가운데 담기지 못한 것 — 바로 앞 판은 머리 · 꼬리, 그 앞의 두 판은 첫머리만. 없으면 빈 글."""
    if job_index is None:
        return ""
    answers = [
        index for index in range(job_index - 1, -1, -1)
        if rest[index].get("role") == "assistant" and not rest[index].get("tool_calls") and _text(rest[index].get("content")).strip()
    ][: 1 + PRIOR_TURNS_OLDER_MAX]
    if not answers or all(index in chosen for index in answers):
        return ""
    older: list[str] = []
    latest: list[str] = []
    for order, answer_at in enumerate(answers):
        if answer_at in chosen:
            continue
        answer = _text(rest[answer_at].get("content")).strip()
        ask = _prior_ask_before(rest, answer_at)
        if order == 0:
            limit = PRIOR_TURN_ANSWER_HEAD_CHARS + PRIOR_TURN_ANSWER_TAIL_CHARS
            if len(answer) > limit:
                answer = (
                    answer[:PRIOR_TURN_ANSWER_HEAD_CHARS].rstrip()
                    + f"\n(…가운데 {len(answer) - limit:,}자 줄임…)\n"
                    + answer[-PRIOR_TURN_ANSWER_TAIL_CHARS:].lstrip()
                )
            if ask:
                latest.append("[앞 질문] " + ask[:PRIOR_TURN_ASK_CHARS])
            latest.append("[앞 답] " + answer)
        else:
            cut = answer[:PRIOR_TURN_OLDER_ANSWER_CHARS].rstrip()
            if len(answer) > PRIOR_TURN_OLDER_ANSWER_CHARS:
                cut += f" (…뒤 {len(answer) - PRIOR_TURN_OLDER_ANSWER_CHARS:,}자 줄임)"
            pair = (["[그 앞 질문] " + ask[:PRIOR_TURN_OLDER_ASK_CHARS]] if ask else []) + ["[그 앞 답] " + cut]
            older.insert(0, "\n".join(pair))  # 오래된 것이 위로
    return "\n".join([PRIOR_TURN_OPEN, PRIOR_TURN_LEAD, *older, *latest, PRIOR_TURN_CLOSE])


def _attach_read_ledger(messages: list[dict[str, Any]], block: str) -> bool:
    """한 줄 묶음을 이번 판 맥락에 싣는다 — 맥락을 실은 요청 메시지가 있으면 그 안에, 없으면 첫 요청 앞에 맥락 칸을 만들어."""
    for item in messages:
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str) and _job_context_chars(item):
            head, _, tail = content.partition(JOB_CONTEXT_CLOSE)
            item["content"] = f"{head.rstrip()}\n\n{block}\n{JOB_CONTEXT_CLOSE}{tail}"
            return True
    for item in messages:
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str) and not content.startswith(SYSTEM_NOTE_PREFIX):
            item["content"] = with_job_context(block, content)
            return True
    return False


def compact_code_result(message: dict[str, Any]) -> dict[str, Any]:
    """오래된 코드 도구 원문을 다음 판단에 필요한 구조로 압축한다.

    일반 ``fold``처럼 "다시 불러라"만 남기면 실패 원인과 이미 읽은 파일을 잊어
    같은 명령을 반복한다. 경로·줄·검증 결과·실패 지문은 작아도 계속 남긴다.
    """
    name = _text(message.get("tool_name")) or "code_tool"
    raw = _text(message.get("content"))
    summary: dict[str, Any] = {"compacted": True, "tool": name}
    try:
        payload = json.loads(raw)
        summary["ok"] = bool(payload.get("ok")) if isinstance(payload, dict) else False
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            result = {}
        for key in (
            "path", "output_path", "line_start", "line_end", "truncated",
            "command", "exit_code", "verified", "timed_out", "elapsed_sec",
            "failure_kind", "failure_fingerprint", "failed_targets", "instruction",
            "decision", "remaining_todo", "changed_paths", "files_changed",
        ):
            value = result.get(key)
            if value not in (None, "", [], {}):
                summary[key] = value
        if name == "local_index_codebase":
            repo_map = result.get("repo_map")
            if isinstance(repo_map, dict):
                summary["selected_paths"] = [
                    str(row.get("path") or "")
                    for row in (repo_map.get("matches") or [])[:12]
                    if isinstance(row, dict) and row.get("path")
                ]
        elif name == "local_read_text_file":
            content = _text(result.get("content"))
            if content:
                summary["excerpt"] = content[:800]
        elif name == "local_run_project_command":
            stdout = _text(result.get("stdout"))
            stderr = _text(result.get("stderr"))
            diagnostic = stderr or stdout
            if diagnostic:
                summary["diagnostic_tail"] = diagnostic[-1600:]
    except (ValueError, TypeError, AttributeError):
        summary["parse_error"] = True
    saved = {key: value for key, value in message.items() if key != "content"}
    saved["content"] = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    return saved


def fit_system(
    sections: list[tuple[str, str, bool]], *, budget: int
) -> tuple[str, list[str]]:
    """시스템 메시지를 **반쪽으로 자르지 않고** 예산에 맞춘다.

    ## 왜 (2026-08-31, 하루에 두 번 당하고 나서)

    예전에는 다 이어 붙인 뒤 ``[:system_max]`` 로 뭉텅 잘랐다. 자르는 자리가 **글의
    한가운데**라 이런 일이 났다:

        7,000 일 때   RECON→PLAN→PATCH→VERIFY 가 통째로 사라짐 (계약이 안 도착)
        16,000 일 때  저장소 지도가 잘림 + 맨 끝의 **시각 줄까지** 날아감

    둘 다 에러가 아니라 **침묵**으로 나타나서 「모델이 계약을 안 지킨다」로 오해했다.
    그리고 상한을 올려 봐야 프롬프트가 자라면 또 걸린다 — 두더지잡기다.

    이 저장소가 이미 아는 답을 시스템 메시지에만 안 쓰고 있었다:
    **자를 땐 글자 말고 목록을 자른다.**

    - 못 버리는 것(계약·말투·시각)은 **무슨 일이 있어도 통째로 남는다**
    - 버려도 되는 것(카탈로그·지도)은 **통째로 빠진다**. 반쪽은 없다
    - 무엇이 빠졌는지 **모델에게 말해 준다** — 조용히 사라지는 것이 제일 나쁘다

    ``sections`` 는 (라벨, 본문, 버려도 되는가). 순서가 곧 우선순위이고, 버릴 때는
    **뒤에서부터** 버린다. 돌려주는 것은 (완성된 글, 버린 라벨들).
    """
    merged, dropped = _fit_sections(sections, budget=budget)
    return "\n\n".join(text for _, text in merged), dropped


def _fit_sections(
    sections: list[tuple[str, str, bool]], *, budget: int
) -> tuple[list[tuple[str, str]], list[str]]:
    """`fit_system` 의 고르기 — 남길 칸을 (라벨, 본문) 순서대로, 그리고 버린 라벨들."""
    keep = [(label, text) for label, text, droppable in sections if text and not droppable]
    optional = [(label, text) for label, text, droppable in sections if text and droppable]
    fixed = sum(len(text) + 2 for _, text in keep)
    dropped: list[str] = []
    chosen: list[tuple[str, str]] = []
    used = fixed
    for label, text in optional:
        if used + len(text) + 2 <= budget:
            chosen.append((label, text))
            used += len(text) + 2
        else:
            dropped.append(label)
    if dropped:
        # 빠졌다는 사실 자체가 정보다. 모델이 "지도가 없네"를 알아야 도구로 가져온다.
        chosen.append(
            ("_note", "(자리가 모자라 뺀 것: " + ", ".join(dropped) + " — 필요하면 도구로 가져와라)")
        )
    order = {label: index for index, (label, _, _) in enumerate(sections)}
    merged = keep + chosen
    merged.sort(key=lambda row: order.get(row[0], len(order)))
    return merged, dropped


#: 이번 판에만 맞는 맥락(스킬 메모·저장소 지도·시각)을 요청 메시지 앞에 붙일 때 감싸는 표시.
JOB_CONTEXT_OPEN = "<이번-판-맥락>"
JOB_CONTEXT_CLOSE = "</이번-판-맥락>"


def fit_system_split(
    sections: list[tuple[str, str, bool]], *, budget: int, per_job: frozenset[str]
) -> tuple[str, str, list[str]]:
    """`fit_system` 과 같은 고르기를 하되, **판마다 바뀌는 칸**(``per_job``)을 따로 돌려준다 (2026-10-07).

    ## 왜 — 새 판의 첫 호출이 프롬프트 전체를 다시 읽었다 (코딩 사다리 L6 · 3판 모두 17,121토큰 · 6.3~6.5초)

    시각·목표가 시스템 글의 **끝**에 있었다. 앞 14,146토큰이 글자까지 같아도 못 살렸다 — 운영 모델(Ornith 35B)은
    서버가 캐시를 아무 자리로나 되감지 못하고 **체크포인트 자리로만** 되돌리는데, 서버는 체크포인트를
    「마지막 사용자 메시지가 시작하는 자리」와 「프롬프트 끝 근처」에만 만든다. 갈라진 자리(시각 줄)보다 앞에는
    하나도 없어 「전체 다시 읽기」가 됐다(서버 기록 `forcing full prompt re-processing`).

    같은 서버에 직접 잰 값(시스템 글 1만 토큰 · 새 판):

        시각 줄이 시스템 끝 + 뒤에 도구 결과가 붙은 실제 판     17,121토큰 다시 읽음 · 6.4초
        시각 줄을 요청 메시지 앞으로                            83토큰 · 0.12초
        사이에 전혀 다른 짧은 호출(기억 뽑기)이 끼어도          83토큰 · 0.13초  (서버가 예전 상태를 되살린다)
        둘째 시스템 메시지로                                    이 모델의 대화 틀이 거절(500)

    그래서 시스템 메시지에는 **판이 바뀌어도 안 바뀌는 것만** 남기고, 나머지는 요청 메시지 앞(`with_job_context`)에 둔다.
    메시지 경계를 새로 만들지 않는다 — 사용자 메시지가 연달아 오면 거절하는 대화 틀이 있다.

    돌려주는 것은 (고정 글, 이번 판 글, 버린 라벨들). 버릴 것을 고르는 우선순위는 `fit_system` 과 같다(목록 순서).
    「자리가 모자라 뺀 것」 알림은 판마다 달라질 수 있어 이번 판 글에 싣는다.
    """
    merged, dropped = _fit_sections(sections, budget=budget)
    stable = "\n\n".join(text for label, text in merged if label not in per_job and label != "_note")
    job = "\n\n".join(text for label, text in merged if label in per_job or label == "_note")
    return stable, job, dropped


def with_job_context(job_text: str, request: str) -> str:
    """요청 메시지의 글 — 이번 판 맥락을 앞에, 요청을 뒤에. 맥락이 비면 요청 그대로."""
    if not str(job_text or "").strip():
        return request
    return f"{JOB_CONTEXT_OPEN}\n{job_text.strip()}\n{JOB_CONTEXT_CLOSE}\n\n{request}"


def add_job_context(messages: list[dict[str, Any]], note: str) -> bool:
    """이번 판 맥락에 한 대목을 더한다. 맥락을 실은 메시지가 없으면 False — 부른 쪽이 예전 자리에 붙인다."""
    for item in reversed(messages):
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str) and _job_context_chars(item):
            head, _, tail = content.partition(JOB_CONTEXT_CLOSE)
            item["content"] = f"{head.rstrip()}\n\n{note.strip()}\n{JOB_CONTEXT_CLOSE}{tail}"
            return True
    return False


def _job_context_chars(item: dict[str, Any]) -> int:
    """이 메시지 앞에 붙은 이번 판 맥락의 글자 수(닫는 표시까지). 없으면 0."""
    content = item.get("content")
    if not isinstance(content, str) or not content.startswith(JOB_CONTEXT_OPEN):
        return 0
    close = content.find(JOB_CONTEXT_CLOSE)
    return close + len(JOB_CONTEXT_CLOSE) if close >= 0 else 0


# ── 전사는 뒤에 붙기만 한다 (2026-10-24 · 전략안 §55-43) ─────────────────────────────────────────────
#
# 본 것(운영 판 셋 · 27B · 창 131,072 · `data/model_calls.jsonl` 의 `prefix_kept` 와 `jarvis.db` 의 보낸 글자 수):
#
#     판         전체     지난 기록 그대로        중간부터 바뀜
#     f6b60f9c   1,274초  23번 · 앞부분 154초     15번 · 552초 (한 번 25~44초)
#     e9098192     700초  46번 · 164초             6번 · 124초
#     bf69599d     428초  20번 · 161초             1번 · 14초
#
# 까닭은 둘이었다. 둘 다 **이번에 보낼 것을 처음부터 다시 고르는** 규칙이라, 지난번에 원문이던 것이 이번엔 접힌다:
#   ① 넘침 묶어 접기(위 `pick`) — 「다 들어가는 가장 작은 묶음」을 매번 새로 찾는데, 마지막 묶음이 「최근 4개 빼고 전부」라
#      그 경계가 결과 하나마다 한 칸씩 미끄러졌다. f6b60f9c 의 15번이 전부 이것이다(보낸 글자 15만 자 → 9만~12만 자로 줄어듦).
#   ② 길 찾기 묶어 접기(`nav_fold_step`) — 예산이 남아도 결과 8개마다 오래된 스냅샷 · 요소 찾기를 접었다. e9098192 · bf69599d.
#
# 그래서 접기를 **상태로** 든다: 한 번 접은 메시지는 다음 부르기에도 똑같이 접고(`fold_state`), 새로 접는 것은 예산을 넘었을
# 때뿐이며 그때는 예산의 이 비율까지 **한꺼번에** 내린다. 그 사이 부르기는 앞이 글자까지 같고 뒤에 붙기만 한다.
# 길 찾기도 그때 같이 접는다(개수로 접지 않는다).
#
# 함께 견준 안(본문은 따로 두고 처음부터 짧은 요약만): 본문을 처음부터 안 보이면 모델이 그 페이지를 한 번은 다시 열어
# 읽어야 하고(걸음이 는다), 바뀐 자리를 센 결과 앞이 바뀐 까닭은 본문의 길이가 아니라 「다시 고르기」 규칙이었다. 원본은 지금도
# `messages` 에 그대로 있고(근거 장부 · 숫자 대조는 그쪽을 본다) 바뀌는 것은 모델에게 보내는 사본뿐이다.
#
# 시킨 일 · 이번 판 요청은 예전처럼 따로 지킨다(2026-08-20 쿠팡 판). 접어도 안 들어가면 예전 규칙으로 떨어진다.
# 되돌리기: 설정 `JARVIS_APPEND_ONLY_TRANSCRIPT=0`(`append_only_enabled`).
#: 넘쳤을 때 이 비율까지 한꺼번에 내린다. 낮을수록 다음 접기까지 오래 가지만 옛 걸음의 원문을 더 잃는다(계단식 접기와 같은 값).
APPEND_ONLY_FOLD_TARGET = 0.5


def append_only_enabled() -> bool:
    try:
        from .config import setting

        return str(setting("JARVIS_APPEND_ONLY_TRANSCRIPT", "1")).strip().lower() not in {"0", "false", "off", "no"}
    except Exception:  # noqa: BLE001 — 스위치를 못 읽으면 켠 것으로
        return True


def message_sig(item: dict[str, Any]) -> str:
    """메시지 하나의 서명 — 안쪽 표식(`_` 로 시작하는 칸)은 뺀다. 같은 글이면 같은 서명."""
    payload = {key: value for key, value in item.items() if not str(key).startswith("_")}
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def bounded(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
    tool_result_max: int,
    keep_recent_tools: int = 4,
    # ★ 7,000 이었다. 근거 주석이 없는 기본값이었는데, 그 값이 **코드 계약을
    # 통째로 잘라 내고 있었다** (2026-08-30).
    #
    # 조립된 시스템 메시지가 14,305자다:
    #   _VOICE_AND_MANNER 429 + AGENT_SYSTEM_PROMPT 12,109 + _QWEN_CODE_PROMPT 1,767
    # 7,000 에서 자르면 뒤쪽 7,305자(51%)가 조용히 사라진다. 그 안에 있던 것:
    #   RECON -> PLAN -> PATCH -> VERIFY 상태기계 · "테스트 파일은 수정하지 마"
    #   · "같은 지문 두 번이면 가설을 바꿔라" · 그리고 `skill_note`.
    # 즉 **코드 계약이 모델에 한 번도 도착한 적이 없다.** 벤치에서 "32걸음·편집
    # 5회·검증 0회" 로 죽던 판이 VERIFY 규칙 없이 돈 판이었다.
    #
    # 올려도 되는 이유는 **재 봤기 때문이다.** 시스템 메시지는 판 안에서 안 바뀌는
    # 접두사라 첫 걸음에만 씹히고 그 뒤로는 캐시에 걸린다:
    #   7,000자(3,309토큰)  첫 3.2초 / 이후 0.6초
    #  14,305자(6,295토큰)  첫 3.3초 / 이후 0.6초   ← 토큰 두 배, 시간 +0.1초
    # 한 판이 200~400초인데 0.1초를 아끼려고 계약 전체를 버리고 있었다.
    #
    # ★ 16,000 도 모자랐다 (2026-08-31). 위의 14,305 는 **프롬프트 상수 셋만** 센
    # 값이었다. 실제 조립은 이렇다:
    #
    #     말투/사고        429     공통 계약     12,109
    #     Qwen 코드계약  1,767     자사데이터 절    376
    #     사고 도구 카드  2,531     저장소 지도    2,936
    #     ────────────────────────────────  합계 20,148
    #
    # 사고 카드를 넣기 전에도 17,617 자라 **저장소 지도가 조용히 잘리고 있었다.**
    # 같은 병을 하루에 두 번 만난 셈이다 — 분모를 반만 세고 상한을 정했기 때문이다.
    #
    # 26,000 은 지금(20,148)에서 29% 여유다. 저장소 지도는 저장소·질문에 따라
    # 커지므로 여유가 필요하다. 비용은 여전히 접두사 캐시가 먹는다.
    #
    # ⚠ 이 값을 다시 정할 땐 **상수만 세지 말고 실제 조립을 재라.**
    #   `tests/test_must_observe.py::test_the_system_message_actually_fits` 가 지킨다.
    system_max: int = 26_000,
    preserve_recent_thinking: int = 0,
    thinking_max_chars: int = 8_000,
    # ★ 길 찾기 결과는 **묶어서** 접는다 (2026-09-29 저녁, 「걸음마다 다시 읽기 6~15초」).
    #
    # 예전엔 최근 4개만 원문으로 두고 5번째부터 접었다. 그 창은 도구 결과가 하나 늘 때마다
    # 한 칸 미끄러져, 직전 호출에서 원문이던 스냅샷이 이번엔 한 줄이 된다 — 전사 **중간**이
    # 바뀌어 거기서부터 끝까지(원문 3개 + 새 결과) **매 걸음** 다시 읽었다. 코드 도구가
    # 08-27 에 똑같이 당해서 「예산 모자랄 때만」으로 고쳤고, 길 찾기는 품질 규칙이라 뒀었다.
    #
    # 묶으면: 접히는 수를 ``step`` 단위로만 올린다. 그 사이 걸음은 전사가 뒤에 붙기만 해서
    # 캐시가 온전히 산다. 깨질 때 다시 읽는 양은 예전 한 걸음과 같고(원문 keep 개), 깨지는
    # 횟수가 1/step 이 된다. 대가: 원문 스냅샷이 최대 keep+step-1 개까지 남는다(창이 커짐).
    # 예산을 넘기면 아래 build 의 넘침 규칙이 예전처럼 하나씩 접는다 — 품질·예산 규칙은 그대로다.
    # ★ 2026-09-30: 4 → 8. 운영 기록(`data/prefix_breaks.jsonl`)에서 판 중간 앞머리 깨짐이 메시지 16→18·24→26·…·56→58, 곧 **길 찾기
    #   4걸음마다** 이 접기였고, 한 번에 1~2만 토큰을 다시 읽었다(21초). 8 이면 멈칫이 절반, 다시 읽는 총량은 약 20% 준다.
    #   대가: 원문 화면이 최대 keep+7 개(11개). 예산을 넘으면 아래 넘침 규칙이 그대로 접는다.
    #   ※ 처음엔 저장된 체크포인트 전사 17개로 흉내 내 「접기는 원인 아님」이라 잘못 봤다 — 길 찾기가 적은 짧은 판뿐이었다.
    nav_fold_step: int = 8,
    # 읽은 화면의 한 줄 묶음을 밀려난 것만이 아니라 **전부** 적는다 — 작은 창의 판(`READ_LEDGER_PINNED_LEAD` 의 설명).
    pin_reads: bool = False,
    # 뒤에 붙기만 하는 전사(`APPEND_ONLY_FOLD_TARGET` 의 설명 · 2026-10-24). 부르는 쪽이 판마다 하나씩 들고 있는 빈 사전을 넘긴다 —
    # 이번에 접은 메시지를 거기 적어 두고 다음 부르기에도 똑같이 접는다. None 이면 예전 규칙(시험 · 체크포인트).
    fold_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """모델에게 보낼 전사. 예산 안에서 **버리는 대신 접는다.**

    돌려주는 순서는 원래 순서다. 맨 앞은 시스템, 그 다음이 시킨 일.
    """
    if not messages:
        return []

    system: dict[str, Any] | None = None
    body = list(messages)
    if body and body[0].get("role") == "system":
        system = dict(body[0])
        whole = _text(system.get("content"))
        if len(whole) > system_max:
            # ★ 잘림은 **소리를 내야 한다** (2026-08-31).
            #
            # 두 번 다 조용히 잘렸다. 처음엔 코드 계약(RECON→PLAN→PATCH→VERIFY)이,
            # 두 번째엔 저장소 지도가. 둘 다 에러가 아니라 **침묵**으로 나타나서
            # 「모델이 계약을 안 지킨다」로 몇 판을 오해했다.
            #
            # 여기서 막으면 판이 죽으니 자르기는 그대로 하되, 잘랐다는 사실을 남긴다.
            _LOG.warning(
                "system_message_truncated chars=%d max=%d lost=%d",
                len(whole),
                system_max,
                len(whole) - system_max,
            )
        system["content"] = whole[:system_max]
        body = body[1:]

    # 시킨 일 — 첫 사용자 메시지. 이것이 없으면 답할 대상이 없다.
    task_index = next(
        (i for i, item in enumerate(body) if item.get("role") == "user"), None
    )
    task = dict(body[task_index]) if task_index is not None else None
    rest = [item for i, item in enumerate(body) if i != task_index]

    budget = max_chars
    if system:
        budget -= len(_text(system.get("content")))
    if task:
        # 시킨 일도 상한은 둔다(첨부가 긴 경우). 다만 **접지도 버리지도 않는다.**
        # 앞에 붙은 이번 판 맥락(`with_job_context`)은 상한에서 뺀다 — 맥락이 길다고 요청의 뒤가 잘리면 안 된다.
        task["content"] = _text(task.get("content"))[: tool_result_max + _job_context_chars(task)]
        budget -= len(_text(task.get("content")))
    # ★ 이번 판 맥락을 실은 요청 메시지는 **첫 사용자 메시지가 아니어도**(앞에 지난 대화가 있을 때) 버리지 않는다 (2026-10-07).
    #   목표가 시스템 글에 있던 때는 요청 메시지가 예산에 밀려나도 목표가 남았다. 이제 목표는 그 메시지에만 있다.
    #   자리를 미리 빼 두고, 아래 담기에서는 예산을 묻지 않고 넣는다.
    job_index = next(
        (i for i, item in enumerate(rest) if item.get("role") == "user" and _job_context_chars(item)), None
    )
    if job_index is not None:
        budget -= len(json.dumps(
            {key: value for key, value in rest[job_index].items() if key != "_metrics"}, ensure_ascii=False
        ))

    # 최근 도구 결과 몇 개는 원문으로 둔다 — 방금 본 것이 제일 쓸모 있다.
    tool_positions = [i for i, item in enumerate(rest) if item.get("role") == "tool"]
    keep_full = set(tool_positions[-keep_recent_tools:]) if keep_recent_tools else set()
    # 길 찾기를 접는 경계 — 앞에서부터 ``step`` 개씩만 움직인다(위 nav_fold_step 주석).
    overflow = max(0, len(tool_positions) - keep_recent_tools)
    step = max(1, nav_fold_step)
    nav_fold = set(tool_positions[: (overflow // step) * step])
    if fold_state is not None:
        # 뒤에 붙기만 하는 전사에서는 길 찾기도 개수로 접지 않는다 — 넘칠 때 한꺼번에 접는다(`_pick_append_only`).
        nav_fold = set()

    assistant_positions = [
        i for i, item in enumerate(rest)
        if item.get("role") == "assistant" and _text(item.get("thinking"))
    ]
    keep_thinking = set(assistant_positions[-preserve_recent_thinking:]) if preserve_recent_thinking else set()

    #: 마지막 `build` 가 담은 메시지 자리 — 담기지 못한 읽은 화면을 한 줄로 남길 때 본다(`read_ledger`).
    chosen: set[int] = set()

    def build(
        *, compact_code: bool, prefold: frozenset[int] = frozenset(), fold_on_overflow: bool = True, cut: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """전사를 담는다. 두 번째 값은 **하나도 안 잘렸는가**이다. ``prefold`` 는 미리 접어 둘 도구 결과 자리.

        ``cut`` 앞의 메시지는 담지 않는다(뒤에 붙기만 하는 전사가 한꺼번에 덜어 낸 자리 — 이번 판 요청은 그래도 남긴다).

        ``fold_on_overflow=False`` 면 담다가 안 들어가는 것을 그 자리에서 접지 않고 「넘쳤다」(False)를 돌려준다 —
        그 자리 접기가 한 칸씩 미끄러지는 창이었다(아래 묶음 접기 주석).
        """
        remaining = budget
        selected: list[dict[str, Any]] = []
        chosen.clear()

        def stop(at: int, complete: bool) -> tuple[list[dict[str, Any]], bool]:
            # 예산에 막혀 여기서 멈춘다 — 아직 못 간(더 오래된) 이번 판 요청은 넣고 멈춘다. 자리는 위에서 미리 뺐다.
            if job_index is not None and job_index < at:
                selected.append({key: value for key, value in rest[job_index].items() if key not in {"_metrics", "thinking"}})
            return selected, complete

        for index in range(len(rest) - 1, -1, -1):
            if index < cut:
                return stop(cut, True)
            item = rest[index]
            saved = {key: value for key, value in item.items() if key != "_metrics"}
            if index in keep_thinking:
                saved["thinking"] = _text(saved.get("thinking"))[-thinking_max_chars:]
            else:
                saved.pop("thinking", None)
            if saved.get("role") == "tool":
                saved["content"] = _text(saved.get("content"))[:tool_result_max]
                name = _text(saved.get("tool_name"))
                # 길 찾기 결과는 예산이 남아도 접는다 — 정리 단계에서 스냅샷
                # 30,000자가 근거인 척 앉아 있는 것이 문제였다(2026-08-20).
                if index in nav_fold and name in NAVIGATION_TOOLS:
                    saved = fold(saved)
                elif index in prefold:
                    saved = compact_code_result(saved) if name in CODE_TOOLS else fold(saved)
                elif index not in keep_full and compact_code and name in CODE_TOOLS:
                    saved = compact_code_result(saved)
            size = len(json.dumps(saved, ensure_ascii=False))
            if index == job_index:
                selected.append(saved)
                continue
            if size > remaining:
                if not fold_on_overflow:
                    return stop(index, False)
                # 안 들어가면 접어서 한 번 더 시도한다. 접어도 안 되면 거기서 멈춘다.
                if saved.get("role") == "tool":
                    saved = (
                        compact_code_result(saved)
                        if _text(saved.get("tool_name")) in CODE_TOOLS
                        else fold(saved)
                    )
                    size = len(json.dumps(saved, ensure_ascii=False))
                if size > remaining:
                    return stop(index, False)
            selected.append(saved)
            chosen.add(index)
            remaining -= size
            if remaining <= 0:
                return stop(index, index == 0)
        return selected, True

    # ★ 코드 도구 결과는 **예산이 모자랄 때만** 압축한다.
    #
    # 예전에는 예산이 남아도 최근 4개만 원문으로 두고 나머지를 매번 압축했다.
    # 그 창은 한 걸음씩 미끄러지므로, 직전 호출에서 원문이던 메시지가 이번엔
    # 압축본이 된다 — 전사 **중간**이 바뀌어 프리픽스 캐시가 그 지점부터 통째로
    # 무효가 됐다. 실측(2026-08-27, 24과제): 2번째 호출은 5,756토큰을 0.79초에
    # 처리했는데(캐시 적중) 3번째부터는 매번 8.5초씩 전부 다시 읽었다. 판당 약
    # 60초, 72판이면 한 시간이 여기로 샜다. 128,000자 예산 중 25,000자만 쓰면서.
    #
    # 길 찾기(NAVIGATION_TOOLS)는 위 규칙 그대로 둔다 — 그쪽은 창을 아끼려는
    # 것이 아니라 **오래된 화면이 근거인 척하는 것**을 막는 품질 규칙이다.
    def pick_append_only() -> list[dict[str, Any]] | None:
        """뒤에 붙기만 하는 담기 — 지난번에 접은 것만 접고, 넘칠 때만 **한꺼번에** 크게 접어 그 결정을 `fold_state` 에 남긴다.

        접어도 과녁에 못 미치면(접힌 줄이 쌓인 긴 판) 오래된 걸음을 **한꺼번에** 덜어 낸다 — 덜어 낸 읽은 화면은 예전처럼
        한 줄 묶음으로 이번 판 맥락에 남는다(`read_ledger`). 최근 원문(keep_full)까지 덜어야 하면 None — 예전 규칙으로 떨어진다.
        """
        nonlocal budget
        assert fold_state is not None
        sticky: set[str] = fold_state.setdefault("folded", set())
        sigs = {index: message_sig(rest[index]) for index in tool_positions}
        held = frozenset(index for index in tool_positions if sigs[index] in sticky)
        # 덜어 낸 자리는 (자리, 서명) 둘로 든다 — 빈 걸음 메시지는 서명이 서로 같을 수 있어 서명만으로는 자리를 못 찾는다.
        cut = 0
        if fold_state.get("cut_sig"):
            remembered = int(fold_state.get("cut_at", 0))
            matches = [index for index, item in enumerate(rest) if message_sig(item) == fold_state["cut_sig"]]
            cut = min(matches, key=lambda index: abs(index - remembered)) if matches else 0
        selected, complete = build(compact_code=False, prefold=held, fold_on_overflow=False, cut=cut)
        if complete:
            return selected
        # 넘쳤다 — 예산의 `APPEND_ONLY_FOLD_TARGET` 까지 내려가게 한 번에 접는다. 오래된 길 찾기는 다 접고,
        # 근거(읽은 본문 등)는 **오래된 것부터** 들어갈 때까지만. 최근 원문(keep_full)은 안 접는다.
        candidates = [index for index in tool_positions if index not in keep_full and index not in held and index >= cut]
        base = set(held) | {index for index in candidates if _text(rest[index].get("tool_name")) in NAVIGATION_TOOLS}
        others = [index for index in candidates if index not in base]
        every = frozenset(base | set(others))
        # 덜어 낼 수 있는 자리 — 도구 결과가 짝(부른 걸음)을 잃지 않게 도구 결과가 아닌 메시지에서만 자르고, 최근 원문 앞까지만.
        oldest_kept = min(keep_full) if keep_full else len(rest)
        cuts = [index for index in range(cut + 1, oldest_kept + 1) if index == oldest_kept or rest[index].get("role") != "tool"]
        full = budget
        budget = int(full * APPEND_ONLY_FOLD_TARGET)
        try:
            count, new_cut = len(others), cut
            if build(compact_code=False, prefold=every, fold_on_overflow=False, cut=cut)[1]:
                low, high = 0, len(others)
                while low < high:  # 과녁에 들어가는 가장 작은 수(접는 수가 늘면 줄기만 한다)
                    middle = (low + high) // 2
                    if build(compact_code=False, prefold=frozenset(base | set(others[:middle])), fold_on_overflow=False, cut=cut)[1]:
                        high = middle
                    else:
                        low = middle + 1
                count = low
            elif cuts:
                low, high = 0, len(cuts) - 1
                while low < high:  # 다 접고도 넘치면 과녁에 들어가는 가장 앞의 자르는 자리
                    middle = (low + high) // 2
                    if build(compact_code=False, prefold=every, fold_on_overflow=False, cut=cuts[middle])[1]:
                        high = middle
                    else:
                        low = middle + 1
                new_cut = cuts[low]
        finally:
            budget = full
        folded = frozenset(base | set(others[:count]))
        selected, complete = build(compact_code=False, prefold=folded, fold_on_overflow=False, cut=new_cut)
        if not complete:
            return None
        sticky.update(sigs[index] for index in folded)
        if new_cut != cut:
            fold_state["cut_sig"] = message_sig(rest[new_cut]) if new_cut < len(rest) else ""
            fold_state["cut_at"] = new_cut
        fold_state["folds"] = int(fold_state.get("folds", 0)) + 1
        fold_state["just_folded"] = True
        return selected

    def pick() -> list[dict[str, Any]]:
        """예산 안에 담는다 — 묶어 접기 → 그 자리 접기 → 코드 결과 압축의 차례로."""
        if fold_state is not None:
            kept = pick_append_only()
            if kept is not None:
                return kept
        selected, complete = build(compact_code=False, fold_on_overflow=False)
        if not complete:
            # ★ 넘칠 때도 **묶어서** 접는다 (2026-09-29 저녁, 64K 로 줄인 뒤 MS 스토어 판에서 잡음).
            #
            # 예전 넘침 규칙은 새 것부터 담다가 안 들어가는 것을 그 자리에서 하나 접었다. 예산을 넘은 뒤로는
            # 새 결과가 붙을 때마다 **가장 오래된 결과가 하나씩** 접혔고, 그 자리가 전사 맨 앞(3번·5번 메시지)이라
            # 거의 전부를 다시 읽었다 — 판 끝 무렵 걸음마다 2.3만 토큰, 15~20초(`prefix_breaks.jsonl` 19:19·19:20).
            # 128K 예산(17만 자)에선 드물었고, 64K 예산(8만 자 — 그중 시스템 2.1만 자)에서 페이지 몇 개면 넘었다.
            #
            # 이제 오래된 쪽부터 ``nav_fold_step`` 개씩 늘려 가며 **다 들어가는 가장 작은 묶음**을 미리 접는다.
            # 접힌 수는 대화가 자랄수록 늘기만 하고 묶음 단위로만 바뀌어, 그 사이 걸음은 뒤에 붙기만 한다.
            # 최근 원문(keep_full)은 여기서 안 접는다. 그래도 안 들어가면 예전 규칙으로 떨어진다.
            foldable = [i for i in tool_positions if i not in keep_full]
            for count in range(step, len(foldable) + step, step):
                selected, complete = build(compact_code=False, prefold=frozenset(foldable[:count]), fold_on_overflow=False)
                if complete:
                    break
        if not complete:
            # 묶음으로도 안 되면(최근 원문 넷만으로도 넘치는 등) 예전 규칙 — 담다가 접고, 그래도 안 되면 코드 결과 압축.
            selected, complete = build(compact_code=False)
        if not complete:
            selected, _ = build(compact_code=True)
        return selected

    selected = pick()
    # ★ 버리기 전에 한 줄 (2026-10-12 · `read_ledger` 위의 설명). 담기지 못한 읽은 화면을 한 줄씩 모으고, 그 묶음의
    #   크기만큼 자리를 빼고 다시 담는다. 다시 담으면 버려지는 것이 하나 더 생길 수 있어 두 번까지 맞춘다.
    ledger = ""
    whole_budget = budget
    for _ in range(3):
        # 바로 앞 판의 답이 담기지 못했으면 그것도 같이 남긴다(`prior_turn_block` 위의 설명) — 앞 대화가 먼저, 읽은 화면이 뒤.
        block = "\n\n".join(
            part for part in (
                prior_turn_block(rest, job_index, chosen), read_ledger(rest, tool_positions, chosen, pin_all=pin_reads),
            ) if part
        )
        if block == ledger:
            break
        ledger = block
        budget = whole_budget - len(block)
        selected = pick()

    result = list(reversed(selected))
    if task:
        result.insert(0, task)
    if system:
        result.insert(0, system)
    if ledger:
        _attach_read_ledger(result, ledger)
    return result


#: 하네스가 판 도중에 끼워 넣는 안내의 머리말. 사람이 쓴 말(덧붙인 말)은 이걸로 시작하지 않는다.
# ── 계단식 접기 (2026-10-09 낮) ────────────────────────────────────────────────
#
# 본 것(맡긴 코드 판 85fc599b · 13,795줄 파일을 줄이는 일 · 27B · 창 131,072): 대화가 **10만 토큰**을 넘자 걸음마다
# 서버가 `forcing full prompt re-processing due to lack of cache data` 를 찍고 전체를 처음부터 다시 읽었다(한 걸음 150초 ·
# 걸음 사이 4~6분). 대표: 「컨텍스트 눌려서 그런 거 아니가 — 접는 방식으로 방법 있지 않나」.
#
# ★ 처음 진단은 틀렸다 — 지우지 않고 적어 둔다. 「넘친 만큼만 접어서 걸음마다 앞쪽이 바뀐다」고 봤는데, 앞머리 깨짐 기록
#   (`data/prefix_breaks.jsonl`)에서 바뀐 자리는 매번 **맨 끝의 메시지 하나**였다(생각이 되풀이돼 끊고 다시 부른 자리).
#   그 자리는 판 내내 바뀌었고, 대화가 작을 때는 서버가 바로 앞 체크포인트로 되돌아가 끝만 다시 읽었다. 달라진 것은 크기다:
#   102,399 토큰에서는 되돌리기에 성공했고, 104,288 에서는 7천 토큰 뒤(96,957)로 물러났고, 105,269 부터는 매번 전체였다.
#   이 서버는 체크포인트로만 되돌리는데(2026-10-07), 대화가 이만큼 크면 쓸 체크포인트가 남아 있지 않다. 까닭은 서버 안쪽이라
#   확인하지 못했다(체크포인트 하나가 550MB 였다).
#
# 그래서 그 크기에 닿기 **전에** 한 번에 크게 접어 대화를 작게 둔다. 접은 결과는 그 판의 대화에 그대로 남긴다 — 다음 걸음마다
# 다시 접지 않게. 접는 순간 한 번은 전체를 다시 읽는다. 무엇을 어떻게 접는지는 `bounded` 의 규칙 그대로다.
#
# ※ 아래 두 값은 **한 판에서 본 자리**로 정한 것이다(이 PC · 이 모델 · 창 131,072). 다른 모델 · 다른 창에서는 재지 않았다.
#   코드 판의 예산은 창의 약 82%(토큰으로 약 10만 7천)다 — 0.75 면 약 8만 토큰에서 접고, 0.5 면 약 5만 4천 토큰이 남는다.

# ★ 2026-10-10 — 접기 시작하는 자리를 **비율 하나**에서 **까닭 둘**로 바꿨다.
#   0.75 는 큰 창(131,072)에서 「서버의 되돌리기가 실패하기 시작하는 약 10만 토큰」을 피하려고 잡은 값이었다. 그 비율을
#   작은 창에도 그대로 썼다. 16GB 조건(창 49,152)으로 같은 일을 돌린 판(569e0929)이 200걸음 동안 **30번** 접혔다(128K 는
#   60걸음에 2번) — 읽기 · 찾기가 161걸음, 고치기 6걸음. 그 판에서 모델에게 간 프롬프트는 가장 클 때 32,684토큰이었다:
#   창의 3분의 1(약 16,000토큰)을 **한 번도 안 쓰고** 접고 있었다. 작은 창에는 10만 토큰 걱정이 없다.
#   그래서: 창이 거의 찰 때(`STEP_FOLD_FULLNESS`) 접되, 큰 창에서는 예전 그 자리(`STEP_FOLD_CEILING_CHARS`)를 넘기지 않는다.
#   큰 창(131,072)에서는 접는 자리가 예전과 같다(257,195자 → 256,000자). 사고 Q 와 같은 꼴이었다 — 상한이 여럿이면 낮은 쪽만 일한다.
#   ※ 작은 창에서 이 값으로 같은 일을 다시 돌려 봐야 한다(전수조사 §7-20).
#: 예산이 이만큼 차면 접는다(작은 창의 기준).
STEP_FOLD_FULLNESS = 0.95
#: 그래도 이 크기는 넘기지 않는다(큰 창의 기준) — 약 8만 토큰. 서버의 되돌리기가 실패하기 시작한 자리(약 10만 토큰)보다 넉넉히 앞이다.
STEP_FOLD_CEILING_CHARS = 256_000
#: 접을 때 예산의 이만큼까지 내린다. 낮출수록 다음 접기까지 오래 가지만 옛 걸음의 원문을 더 많이 잃는다.
STEP_FOLD_TARGET = 0.5


# ── 접기 전 정리 한 장 (2026-10-10) ─────────────────────────────────────────────
#
# 계단식 접기는 옛 걸음의 원문을 **줄이기만** 한다. 그래서 접을 때마다 예전에 읽은 것을 잊고 다시 읽는 걸음이 보였다
# (10-09 `agent.py` 줄이기 판 — 읽기 27번). Pi(`compaction.ts`)는 접는 순간 모델에게 **틀을 준 요약**을 쓰게 해서 그 자리에
# 둔다. 그 틀을 가져온다. 다른 점 하나: 요약을 대화 가운데가 아니라 **요청 메시지 앞**(이번 판 맥락)에 둔다 — 우리 서버는
# 체크포인트 자리로만 되돌려서, 가운데에 메시지를 끼우면 그 뒤를 매번 다시 읽는다(`fit_system_split` 의 설명).
# 접는 순간에는 어차피 앞머리가 바뀌니 그때 한 번 같이 바꾼다. 다음 접기 때는 새 정리가 옛 정리를 **갈아 끼운다**.
#
# ※ 재지 않았다. 설정(`fold_summary_enabled`)으로 끄고 켠다. 볼 것: 접은 뒤 「이미 읽은 파일을 다시 읽는 걸음」이 줄었나,
#   정리를 쓰는 데 걸린 시간(접을 때마다 모델 한 번).
FOLD_SHEET_OPEN = "<접기-전-정리>"
FOLD_SHEET_CLOSE = "</접기-전-정리>"
#: 정리 한 장의 상한(글자). 넘으면 뒤를 자른다 — 정리가 접은 만큼을 도로 채우면 접은 뜻이 없다.
FOLD_SHEET_MAX_CHARS = 6_000
FOLD_SHEET_REQUEST = (
    "[시스템] 대화가 길어져 곧 앞쪽 걸음의 원문을 줄인다. 줄이기 전에, 네가 이 일을 이어 가는 데 필요한 것을 정리해 적어라. "
    "**도구를 부르지 마라 — 글로만 답해라.** 아래 소제목을 그대로 쓰고, 지금까지의 대화에 실제로 있는 것만 적어라(모르면 「없음」).\n\n"
    "## 목표\n(무엇을 끝내야 하는가 · 끝을 가르는 확인 명령이 있으면 그것)\n"
    "## 지킬 것\n(과제 글의 제약 · 건드리면 안 되는 것)\n"
    "## 끝난 것\n(만들거나 고친 파일과 무엇을 했는지 · 통과한 확인)\n"
    "## 하는 중\n(지금 손대고 있는 것)\n"
    "## 막힌 것\n(실패한 확인과 그 까닭 · 아직 못 푼 것)\n"
    "## 정한 것\n(고른 방법과 그 까닭 · 버린 방법)\n"
    "## 다음 걸음\n(바로 다음에 할 일 하나에서 셋)\n"
    "## 다시 읽지 않아도 되게\n(읽은 파일에서 알아낸 것 — 경로 · 함수와 상수 이름 · 줄 번호 · 서로 무엇을 부르는지. 값은 원문 그대로)"
)


def set_fold_sheet(messages: list[dict[str, Any]], sheet: str) -> bool:
    """접기 전 정리를 이번 판 맥락(요청 메시지 앞)에 싣는다. 옛 정리가 있으면 갈아 끼운다. 실을 자리가 없으면 False.

    요청 메시지는 대화의 **첫** 사용자 메시지다. 맥락 칸이 아직 없으면 만든다(`with_job_context`).
    """
    text = str(sheet or "").strip()
    if not text:
        return False
    if len(text) > FOLD_SHEET_MAX_CHARS:
        text = text[:FOLD_SHEET_MAX_CHARS].rstrip() + "\n(…정리가 길어 여기서 잘랐다)"
    block = f"{FOLD_SHEET_OPEN}\n{text}\n{FOLD_SHEET_CLOSE}"
    for item in messages:
        content = item.get("content")
        if item.get("role") != "user" or not isinstance(content, str):
            continue
        if content.startswith(SYSTEM_NOTE_PREFIX):
            continue
        opened = content.find(FOLD_SHEET_OPEN)
        closed = content.find(FOLD_SHEET_CLOSE, opened + 1) if opened >= 0 else -1
        if opened >= 0 and opened < closed < _job_context_chars(item):
            item["content"] = content[:opened] + block + content[closed + len(FOLD_SHEET_CLOSE):]
        elif _job_context_chars(item):
            head, _, tail = content.partition(JOB_CONTEXT_CLOSE)
            item["content"] = f"{head.rstrip()}\n\n{block}\n{JOB_CONTEXT_CLOSE}{tail}"
        else:
            item["content"] = with_job_context(block, content)
        return True
    return False


def transcript_chars(messages: list[dict[str, Any]]) -> int:
    """대화가 모델에게 가는 크기(글자). 안쪽 표식(`_metrics` 처럼 밑줄로 시작하는 칸)은 모델에게 안 가니 세지 않는다."""
    return sum(
        len(json.dumps({key: value for key, value in item.items() if not str(key).startswith("_")}, ensure_ascii=False, default=str))
        for item in messages
    )


def step_fold_trigger_chars(max_chars: int) -> int:
    """이 예산에서 접기 시작하는 크기(글자) — 거의 찼을 때와 큰 창의 천장 가운데 **먼저 오는 쪽**."""
    return min(int(max_chars * STEP_FOLD_FULLNESS), STEP_FOLD_CEILING_CHARS)


def needs_step_fold(messages: list[dict[str, Any]], max_chars: int) -> bool:
    """계단식 접기를 할 때인가 — `step_fold_trigger_chars` 를 넘었다."""
    return max_chars > 0 and transcript_chars(messages) >= step_fold_trigger_chars(max_chars)


SYSTEM_NOTE_PREFIX = "[시스템]"


def attach_system_notes(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """판 도중의 `[시스템]` 안내를 **바로 앞 도구 결과 끝에 이어 붙인다** (2026-09-29 실측).

    ## 왜

    안내를 사용자 메시지로 따로 붙이면, Qwen 렌더러가 **마지막 사용자 메시지를 기준으로** 그 앞의 어시스턴트
    걸음을 다르게 그린다. 메시지 JSON 은 그대로인데 모델이 받는 글의 중간이 바뀌어, 거기서부터 전부 다시 읽었다.

        같은 요청 다시            겹친 토큰 7,244 / 7,244   0.75초
        도구 결과를 뒤에 붙임     7,243 / 7,298            0.96초
        [시스템] 사용자 메시지    5,902 / 7,251            4.01초   ← 중간부터 다시 읽음

    운영 판(09-29 16:51)은 「22,195번째 토큰에서 갈라짐」으로 1만 4천 토큰을 다시 읽었다. 메시지 비교 계측
    (`ollama._note_prefix_break`)에 안 잡힌 이유가 이것이다 — 메시지는 안 바뀌었다.

    ## 규칙

    - `[시스템]` 으로 시작하는 사용자 메시지가 **도구 결과 바로 뒤**면 그 도구 결과에 붙인다(여럿이면 차례로).
    - **늘 같은 규칙**이다 — 어떤 걸음에선 붙이고 어떤 걸음에선 안 붙이면 그게 또 중간을 바꾼다.
    - 어시스턴트 답 바로 뒤의 안내(되받기)·첫 사용자 메시지(시킨 일)·사람이 덧붙인 말은 그대로 둔다.
    - 모델에 보내는 **사본만** 바꾼다. 원래 전사는 여러 곳이 `[시스템]` 표시를 찾아 세므로 건드리지 않는다.
    """
    out: list[dict[str, Any]] = []
    for item in messages:
        content = item.get("content")
        if (
            item.get("role") == "user"
            and isinstance(content, str)
            and content.startswith(SYSTEM_NOTE_PREFIX)
            and not item.get("images")
            and out
            and out[-1].get("role") == "tool"
        ):
            host = dict(out[-1])
            host["content"] = f"{_text(host.get('content'))}\n\n{content}"
            out[-1] = host
            continue
        out.append(item)
    return out


# ── 하네스 안내는 사람 말이 아니다 (2026-10-19 판 8b90144f) ─────────────────────────────────────────────────
#
# 마무리 대조(`_answer_trace_conflict`)가 「사용자가 지정한 조건과 충돌하는 항목이 섞였습니다(무료≠유료)」를 사용자 차례로
# 돌려보냈고, 모델은 다시 쓴 답을 「(사용자 호칭), **지적하신 대로** 가격 표기가 근거 없이 "유료"라고 적힌 항목이 있었습니다」로
# 시작했다. 아무도 지적하지 않았다. 하네스가 사용자 차례에 넣는 안내는 53곳이고 앞머리도 제각각이다(「[시스템]」 ·
# 「[System]」 · 「[손자리 안내]」 · 「[system context]」 · 앞머리 없음). 시스템 차례로 옮기는 길은 막혀 있다 — Qwen 템플릿은
# 맨 앞이 아닌 시스템 메시지를 거절하고, 거절되면 `ollama.fold_late_system_messages` 가 어차피 사용자 차례로 접는다.
#
# 그래서 **자리로 가른다.** 사람의 말은 둘뿐이다 — 이번 판의 시킨 일(그 앞의 지난 대화 포함)과, 작업 도중 사람이 덧붙인 말.
# 둘 다 만드는 자리에서 `PERSON_KEY` 표시를 단다. 시킨 일 **뒤의** 사용자 차례 가운데 표시가 없는 것은 전부 하네스 안내다 —
# 새 안내 자리가 생겨도 앞머리를 기억할 필요가 없다. 모델에 보내는 사본에서 그 안내 앞에 공통 머리 한 줄을 단다.
# 표시가 없는 옛 전사(배포 전 체크포인트 · 시험)는 앞머리(`HARNESS_NOTE_PREFIXES`)로만 가른다.

#: 사람이 한 말인 사용자 차례에 다는 표시(값 "person"). 모델에 보내는 사본에서는 뗀다.
PERSON_KEY = "said_by"

#: 표시가 없는 전사에서 하네스 안내로 치는 앞머리 — `agent.said_by_the_person` 이 쓰던 것과 같다.
HARNESS_NOTE_PREFIXES = ("[시스템]", "[System]", "★", "[도구가 보낸 안내]")

HARNESS_NOTE_HEAD = (
    "[자동 점검 · 사용자가 한 말 아님] 아래는 손자리가 자동으로 붙인 점검·안내다. 사용자는 이 말을 하지 않았고 보지도 못한다 — "
    "답에서 사용자가 지적하거나 요청한 것처럼 옮기지 말고(「지적하신 대로」 금지), 이 안내 자체를 답에 언급하지 마라."
)
HARNESS_NOTE_HEAD_EN = (
    "[Automatic check · not from the user] The note below was added automatically by Sonjari. The user did not say it "
    "and cannot see it — do not present it as the user's remark or request (no \"as you pointed out\"), and do not "
    "mention this note in the answer."
)


def person_message(content: Any) -> dict[str, Any]:
    """사람이 한 말인 사용자 차례. 시킨 일 · 작업 도중 덧붙인 말을 넣는 자리가 이것으로 만든다."""
    return {"role": "user", "content": content, PERSON_KEY: "person"}


def harness_note_positions(messages: list[dict[str, Any]]) -> set[int]:
    """사용자 차례 가운데 **하네스가 넣은 안내**의 자리.

    시킨 일(`PERSON_KEY` 표시가 붙은 **첫** 사용자 차례) 뒤의 사용자 차례는 표시가 없으면 하네스 안내다. 첫 것이어야 한다 —
    작업 도중 덧붙인 말에도 같은 표시가 붙으므로, 마지막 것을 기준으로 삼으면 그 사이의 안내가 사람 말로 빠진다.
    그 앞(지난 대화)은 사람 말이다. 표시가 하나도 없으면 앞머리로만 가른다.
    """
    anchor = min(
        (index for index, item in enumerate(messages)
         if item.get("role") == "user" and item.get(PERSON_KEY) == "person"),
        default=None,
    )
    found: set[int] = set()
    for index, item in enumerate(messages):
        if item.get("role") != "user" or item.get(PERSON_KEY) == "person":
            continue
        content = item.get("content")
        if anchor is not None:
            if index > anchor:
                found.add(index)
        elif isinstance(content, str) and content.lstrip().startswith(HARNESS_NOTE_PREFIXES):
            found.add(index)
    return found


def frame_harness_notes(messages: list[dict[str, Any]], *, english: bool = False) -> list[dict[str, Any]]:
    """모델에 보내는 사본에서 **하네스 안내 앞에 공통 머리를 단다** — 사람 말로 읽히지 않게.

    - `attach_system_notes` **뒤에** 부른다. 도구 결과에 붙은 안내는 이미 도구 결과 자리라 건드리지 않는다.
    - 늘 같은 규칙이라 앞 걸음의 글이 호출마다 같다(캐시가 안 깨진다).
    - `PERSON_KEY` 표시는 여기서 뗀다 — 서버로 가는 글에 우리 표시를 싣지 않는다.
    """
    positions = harness_note_positions(messages)
    head = HARNESS_NOTE_HEAD_EN if english else HARNESS_NOTE_HEAD
    out: list[dict[str, Any]] = []
    for index, item in enumerate(messages):
        if PERSON_KEY in item:
            item = {key: value for key, value in item.items() if key != PERSON_KEY}
        content = item.get("content")
        if index in positions and isinstance(content, str) and not content.startswith(head):
            item = {**item, "content": f"{head}\n{content}"}
        out.append(item)
    return out


#: 영어로 시킨 판의 도구 결과 끝에 붙이는 한 줄. 모델이 **마지막으로 읽는 글**이 이 줄이 되게 한다.
REPLY_IN_ENGLISH_LINE = (
    "[Language] The user reads English. Write your thinking, the one-sentence note before each tool call, "
    "and the final answer in English."
)


def pin_reply_language(messages: list[dict[str, Any]], line: str = REPLY_IN_ENGLISH_LINE) -> list[dict[str, Any]]:
    """영어로 시킨 판에서 **모든 도구 결과 끝에** 답 언어 한 줄을 붙인다 (2026-10-05 AWS 영어 윈도우 첫 실행).

    ## 왜

    영어 지시는 시스템 글 맨 앞 한 줄과 맨 끝 한 줄뿐이었다. 그 사이 1만 자와 판 도중의 도구 안내는 한국어다.
    운영 모델(35B)은 버텼지만, 16GB 카드에 깔리는 9B 는 영어 질문·영어 화면에서 두 번째 걸음부터 생각과 중계를
    한국어로 냈다(「Google 검색이 GitHub 트렌딩 리포지토리를 직접 제공하지 않습니다…」). 영어 사용자는 못 읽는다.
    모델은 **마지막에 읽은 글의 언어**를 따라간다 — 그 자리가 늘 도구 결과다.

    ## 규칙

    - **모든** 도구 결과에 붙인다. 마지막 것에만 붙이면 다음 걸음에 그 줄이 사라져 전사 중간이 바뀌고
      캐시가 거기서부터 깨진다(`attach_system_notes` 와 같은 이유).
    - 모델에 보내는 **사본만** 바꾼다. `attach_system_notes` 뒤에 불러 `[시스템]` 안내보다도 뒤에 오게 한다.
    """
    out: list[dict[str, Any]] = []
    for item in messages:
        if item.get("role") == "tool" and not _text(item.get("content")).endswith(line):
            item = {**item, "content": f"{_text(item.get('content'))}\n\n{line}"}
        out.append(item)
    return out


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """이 전사가 대략 몇 토큰인가. 창에 얼마나 남았는지 말할 때 쓴다."""
    chars = sum(len(json.dumps(item, ensure_ascii=False)) for item in messages)
    return chars // CHARS_PER_TOKEN
