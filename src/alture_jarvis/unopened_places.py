"""열어 보지 않은 곳의 줄 — 표의 줄이 가리키는 곳을 **이 판에서 한 번도 열지 않았는데** 그 줄의 칸이 채워져 있나 (2026-10-24).

★ 운영 판 bf69599d(10-24 01시 · MCP). 「AI 큐레이션 사이트를 찾아 **곳마다 직접 열어 보고** 이름 · 주소 · 얼마나 자주 · 대상 ·
  로그인 없이 목록 · 최근 글 제목을 엑셀로」. 엑셀 「영어」 시트의 세 줄(TLDR AI · Superhuman · The Batch)은
  `최근 글 제목 = 확인 불가 (직접 열지 못함)` 인데 같은 줄의 `얼마나 자주 = 매일/매주` · `대상` · `로그인 없이 목록 = 예` 는 채워져 있었다.
  판 기록에서 그 세 주소는 한 번도 열리지 않았다(tldr.tech 는 `not_this_stage` 로 막힘 · 나머지 둘은 열기조차 없음). 값은 네이버 블로그
  소개 글에서 옮긴 것인데, 그 글에는 주소도 「로그인 없이 목록」도 없고 주기는 TLDR 의 「매일 아침」뿐이었다 — 「매주」 · 「예」는 지은 값이다.
  한국어 시트의 Pickool 줄도 같다: 답은 「직접 열어 확인한 곳」이라 했지만 `contents.premium.naver.com` 은 검색 결과에서만 봤다.

왜 안 잡혔나(확인함):
  - 근거 검사는 **숫자**만 원문과 댄다(`unsupported_numbers` · `ungrounded_write_numbers`). 「매주」 · 「예」 · 「일반인·직장인」은 숫자가 아니다.
  - 이름 검사(「읽지 않고 적은 것」)는 이름이 읽은 글 **어딘가에** 있으면 통과다 — 블로그 글에 이름이 있었다.
  - 줄 ↔ 페이지 대조(`_row_page_binding_check`)의 「이번에 열지 않은 주소」는 **이번 판에 연 사이트의** 엉뚱한 주소만 본다
    (09-28 T1 O6 — 연 사이트에 지은 상품 번호). 사이트 자체를 한 번도 안 연 줄은 처음부터 보지 않았다.

어떻게 가르나 — 낱말이 아니라 **판 기록**으로:
  0. 이 판이 웹 페이지에 **하나도** 닿지 않았으면 보지 않는다 — 앞 판에서 정리한 것을 파일로 옮기는 판(「방금 정리한 것을 엑셀로」)이다.
     첫 규칙 대조에서 그런 판 6개가 전부 헛걸림이었다(뉴스 줄의 주소는 앞 판이 연 것).
  1. 줄 = 답의 표 줄과 만든 파일의 줄(`_rows_with_urls` 그대로). 그 줄의 **주소 칸** = 칸 전체가 주소 **하나**인 칸(「[바로가기](주소)」 꼴 포함).
     문장 · 인용 속에 든 주소(「… CLI-Hub: https://clianything.cc/」 · 「(for example, https://example.com/photo.jpg)」)와
     주소 여럿을 늘어놓은 출처 칸 · 「(연결 실패)」를 붙인 칸은 그 줄의 곳이 아니다 — 첫 규칙 대조에서 깃허브 저장소 줄 · ChatGPT 답 정리 · 레딧 댓글 · 문서 인용 · 접속 실패 줄(7판)이 이 모양으로 걸렸다.
  2. 그 줄의 곳(호스트) = 주소의 호스트(`www.` · `m.` 은 같은 곳). 이 판에서 **성공한 걸음**이 그 호스트, 또는 그 호스트의 위 · 아래 호스트
     (`gmarket.co.kr` ↔ `item.gmarket.co.kr`)에 한 번이라도 닿았으면 연 곳이다(목록 화면 · 열기를 부탁한 주소가 넘겨진 곳 포함 — 넉넉한 쪽).
     가게 검색 화면에서 옮긴 상품 줄은 그 가게에서 본 값이다(첫 규칙 대조: 가격 판 24개가 이 모양). 옆 호스트(`blog.naver.com` ↔
     `contents.premium.naver.com`)는 다른 곳이다. 같은 호스트의 엉뚱한 주소는 옛 검사가 맡는다.
  3. 그 줄에 **채운 값 칸**이 하나라도 있으면 걸린다 — 주소 칸 · 이름 칸(줄의 첫 이름) · 빈 칸 · 「확인 불가」류 칸(문서 쓰기가 이미 쓰는
     `documents._UNVERIFIED_CELL` · 뒤의 괄호 설명은 떼고 본다)은 값이 아니다. 이름과 주소만 적은 줄(「후보」 목록)은 걸리지 않는다.
  같은 줄에 「확인 불가」 칸과 채운 칸이 **같이** 있으면 따로 센다(`mixed`) — 모델 스스로 「못 열었다」고 적은 줄에 값이 있는 모순이다.

무엇을 하나: 답 끝에 사실 한 줄(판 언어로)과 판 기록(`verification.unopened_place_rows`). 판의 완료 판정은 바꾸지 않는다 —
값이 틀렸다는 뜻이 아니라 **그 곳에서 확인한 값이 아니라는** 사실을 밝힌다. 파일은 고치지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from .documents import _UNVERIFIED_CELL

#: 줄에 적힌 주소 — `BrowserAgent._ROW_URL` 과 같은 모양.
_ROW_URL = re.compile(r"https?://[^\s|)\]>\"']+")
#: 숫자 · 단위뿐인 칸 — `BrowserAgent._ROW_VALUE_CELL` 과 같다. 이름 칸을 고를 때만 쓴다(값 칸으로는 센다).
_NUMBER_ONLY_CELL = re.compile(r"^[\s\d,.:/%~\-+()원P점개명권쪽위₩$]*$")
#: 칸 끝의 괄호 설명 — 「확인 불가 (직접 열지 못함)」의 「(직접 열지 못함)」.
_TRAILING_NOTE = re.compile(r"\s*[\(\[（][^()\[\]（）]*[\)\]）]\s*$")
#: 같은 곳의 다른 이름 — 모바일 · www 머리.
_SAME_PLACE_PREFIX = re.compile(r"^(?:www\d?|m)\.")


def place_of(url: str) -> str:
    """주소의 곳(호스트) — 소문자 · `www.` · `m.` 머리를 뗀다. 주소가 아니면 빈 글."""
    text = str(url or "").strip()
    if not re.match(r"(?i)https?://", text):
        return ""
    host = re.sub(r"(?i)^https?://", "", text).split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0].lower().strip(".")
    while _SAME_PLACE_PREFIX.match(host):
        host = _SAME_PLACE_PREFIX.sub("", host, count=1)
    return host


def visited_places(steps: Iterable[dict[str, Any]]) -> set[str]:
    """이 판에서 **성공한 걸음**이 닿은 곳(호스트)들. 실패한 걸음(막힘 · 인증서 오류 · 없는 주소)은 닿은 것이 아니다."""
    places: set[str] = set()
    for step in steps or []:
        if not isinstance(step, dict) or not step.get("ok") or step.get("error"):
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        record = step.get("evidence_record") if isinstance(step.get("evidence_record"), dict) else {}
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        candidates = [record.get("source_id"), evidence.get("url"), evidence.get("shot_url"), evidence.get("final_url")]
        if str(step.get("tool") or "") == "browser_open":
            candidates.append(arguments.get("url"))  # 열어 달라고 한 주소가 넘겨져 다른 곳에 닿아도, 그 곳을 열려다 성공한 것이다
        for candidate in candidates:
            place = place_of(str(candidate or ""))
            if place:
                places.add(place)
    return places


def _is_unverified(cell: str) -> bool:
    text = str(cell or "").replace("*", "").strip()
    if not text:
        return False
    return bool(_UNVERIFIED_CELL.match(text) or _UNVERIFIED_CELL.match(_TRAILING_NOTE.sub("", text)))


def _label_of(cells: list[str]) -> str:
    """줄의 이름 — 주소가 없고 글자가 든 첫 칸(옛 검사와 같은 고르기)."""
    return next(
        (cell for cell in cells
         if not _ROW_URL.search(cell) and not _NUMBER_ONLY_CELL.match(cell) and re.search(r"[가-힣A-Za-z]", cell)),
        "",
    )


#: 칸 전체가 링크 하나인 모양 — 「[바로가기](https://…)」.
_MARKDOWN_LINK = re.compile(r"^\[[^\]]*\]\((https?://[^\s)]+)\)$")


def address_cell(cell: str) -> str:
    """칸 **전체가 주소 하나**면 그 주소, 아니면 빈 글. 꾸밈(굵게 · 코드 · 꺾쇠)과 끝 문장부호는 뗀다."""
    text = re.sub(r"[*`<>]", "", str(cell or "")).strip().rstrip(".,;")
    link = _MARKDOWN_LINK.match(text)
    if link:
        return link.group(1)
    return text if re.fullmatch(r"(?i)https?://[^\s,]+", text) else ""


def _same_site(place: str, visited: set[str]) -> bool:
    """그 곳 · 그 곳의 위 호스트 · 아래 호스트 가운데 하나라도 이 판에서 닿았나."""
    if place in visited:
        return True
    return any(place.endswith("." + other) or other.endswith("." + place) for other in visited)


def rows_about_unopened_places(rows: list[list[str]], visited: set[str]) -> dict[str, Any]:
    """주소를 단 줄 가운데 **그 곳을 이 판에서 안 열었는데 값 칸이 채워진** 줄들.

    돌려주는 것: `rows` — [{name, url, place, values, unknown}] (이름 · 곳으로 한 번만 · 답 표와 파일에 같은 줄이 한 번씩 나온다),
    `opened_rows` — 주소를 단 줄 가운데 그 곳을 연 줄의 수(같은 표에 연 줄과 안 연 줄이 섞였나를 재려고).
    """
    found: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    opened_keys: set[tuple[str, str]] = set()
    if not visited:
        return {"rows": found, "opened_rows": 0}
    for cells in rows or []:
        cells = [str(cell) for cell in cells if cell is not None]
        if len(cells) < 3:
            continue  # 「항목 | 값」 줄은 이름 줄이 아니다(옛 검사와 같은 문턱)
        urls = [address_cell(cell) for cell in cells if address_cell(cell)]
        places = [place_of(url) for url in urls if place_of(url)]
        if not places:
            continue
        label = _label_of(cells)
        key = (re.sub(r"\W+", "", label.replace("*", "")).casefold(), places[0])
        if any(_same_site(place, visited) for place in places):
            opened_keys.add(key)
            continue
        if not label:
            continue
        values = [
            cell.strip() for cell in cells
            if cell.strip() and cell is not label and not _ROW_URL.search(cell) and not _is_unverified(cell)
        ]
        unknown = sum(1 for cell in cells if _is_unverified(cell))
        if not values or key in seen_keys:
            continue
        seen_keys.add(key)
        found.append({
            "name": label.replace("*", "").strip(), "url": urls[0], "place": places[0],
            "values": values[:8], "unknown": unknown,
        })
    return {"rows": found, "opened_rows": len(opened_keys)}


def unopened_rows_note(found: list[dict[str, Any]], say: Callable[[str, str], str]) -> str:
    """답 끝에 붙일 사실 한 줄(판 언어로 — `say(ko, en)`). 걸린 줄이 없으면 빈 글."""
    if not found:
        return ""
    shown = found[:4]
    more = len(found) - len(shown)
    mixed = sum(1 for row in found if row.get("unknown"))
    names_ko = " · ".join(f"「{row['name']}」({row['place']})" for row in shown) + (f" 외 {more}줄" if more > 0 else "")
    names_en = " · ".join(f"\"{row['name']}\" ({row['place']})" for row in shown) + (f" and {more} more" if more > 0 else "")
    ko = (
        f"\n\n⚠ **이번에 열어 보지 않은 곳의 줄 {len(found)}개에 값이 채워져 있습니다: {names_ko}.** "
        "이 판에서 그 주소를 한 번도 열지 않았습니다 — 그 줄의 값은 그 곳에서 확인한 것이 아니라 다른 글(소개 글 · 검색 결과)에서 "
        "옮겼거나 짐작한 것입니다."
        + (f" 그중 {mixed}줄은 같은 줄에 「확인 불가」 칸과 채운 칸이 함께 있습니다." if mixed else "")
        + " 쓰시기 전에 그 곳을 직접 열어 확인해 달라고 시켜 주세요."
    )
    en = (
        f"\n\n⚠ **{len(found)} rows describe places that were never opened in this run: {names_en}.** "
        "Their values were not checked on those sites — they were copied from another page (an article or search results) or guessed."
        + (f" {mixed} of them mark one cell as unverified while filling the others." if mixed else "")
        + " Ask me to open those sites and check before relying on them."
    )
    return say(ko, en)
