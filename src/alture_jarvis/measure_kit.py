"""이 PC 에서 재 보기 — 같은 과제를 이 PC 의 손자리로 돌리고 **숫자만 든 결과 파일** 하나를 남긴다 (2026-10-13).

왜 있나: 작은 그래픽카드의 숫자를 우리는 큰 카드에서 창만 줄여 쟀다. 그렇게 낸 권고를 한 번 거둬야 했다(10-12 — 실제 8GB
노트북의 기록과 맞지 않았다). 메모리가 넘치는 것 · 화면이 쓰는 몫 · 느려지는 것은 그 카드에서만 보인다. 그래서 재는 일을
**그 PC 의 주인이 명령 한 줄로** 할 수 있게 한다 — 우리 집의 다른 PC 도, 나중에 밖에서 도와주는 사람도 같은 것을 돌린다.

    sonjari-mcp -X utf8 -m alture_jarvis.measure_kit            (스토어판 — 실행 별칭이 손자리에 든 파이썬이다)
    python -m alture_jarvis.measure_kit --only price --rounds 1  (개발 폴더)

지키는 것
- **쓰는 중이면 기다린다.** 손자리가 다른 일을 하고 있거나, 사람이 방금 키보드 · 마우스를 썼으면 시작하지 않는다(`--now` 로 끈다).
- **한 과제를 재고 쉰다**(`--rest`, 기본 60초) — 노트북은 연달아 돌리면 뜨거워진다.
- **결과에는 숫자와 예 · 아니오만 싣는다.** 답 글 · 읽은 화면 글 · 주소 · 파일 이름은 채점에만 쓰고 버린다. `--with-steps` 를 주면
  걸음의 도구 이름과 오류 이름까지만 더 싣는다(인자 · 글은 여전히 안 싣는다).
- **무엇을 얼마나 돌렸는지 이 PC 에 남긴다**(`measure_log.jsonl`).
- 과제는 로그인이 필요 없는 공개 가게 세 곳의 가격 찾기와, 지어낸 주제로 네 번 이어 묻기다. 모델 · 창은 **지금 이 PC 에 맞춰진 그대로** 잰다.

이 자가 **못** 재는 것: 답이 좋은가. 줄이 채워졌는지 · 값이 읽은 화면에 있는지 · 파일에 글이 들었는지까지다.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

KIT_VERSION = 3  # 2: 판 사이 흔들림 요약 · 3: 틀린 까닭(causes) · 속도 · 가운데 값과 범위 · 닫은 탭 수

#: 가게 이름 → 그 가게의 **상품 화면** 주소에 들어 있어야 하는 토막.
SHOPS: dict[str, tuple[str, ...]] = {
    "다나와": ("prod.danawa.com/info",),
    "11번가": ("11st.co.kr/products",),
    "G마켓": ("item.gmarket.co.kr",),
}
_SHOP_ALIASES = {"다나와": ("danawa",), "11번가": ("11st", "11번가"), "G마켓": ("gmarket", "지마켓")}
#: 가게 이름 → (그 가게의 호스트, 걸음의 인자에서 그 가게를 겨눈 것으로 볼 낱말…). 첫째가 호스트다.
_SHOP_HOSTS = {"다나와": ("danawa.com", "다나와"), "11번가": ("11st.co.kr", "11번가"), "G마켓": ("gmarket.co.kr", "g마켓", "지마켓")}
#: 가게 한 칸의 까닭 — 결과 파일에 실리는 낱말은 이것뿐이다. 앞의 넷이 「상품 페이지까지 못 감」이다.
CAUSES = ("온전", "안 감", "가려다 막힘", "목록에서 못 엶", "열고 안 읽음", "잘못 읽음", "읽고 잃음", "표 없이 끝남", "주소만 틀림")
_CAUSE_GROUP = {"안 감": "못 찾음", "가려다 막힘": "못 찾음", "목록에서 못 엶": "못 찾음", "열고 안 읽음": "못 찾음"}
_PAGE_READS = ("browser_extract", "browser_read", "browser_page_data")

#: 가격 과제 — 스킬팩 없이도 같은 일이 되게, 가게와 칸을 문장에 다 적는다.
_PRICE_ASK = (
    "다나와, 11번가, G마켓에서 「{item}」을 찾아 가게 · 상품 이름 · 판매 가격 · 배송비 · 읽은 페이지 주소를 "
    "가게마다 한 줄씩 엑셀 파일로 정리해 줘"
)
PRICE_TASKS: dict[str, str] = {
    "mouse": _PRICE_ASK.format(item="로지텍 MX Master 3S"),
    "buds": _PRICE_ASK.format(item="삼성 갤럭시 버즈3 프로"),
    "switch": _PRICE_ASK.format(item="닌텐도 스위치 2 본체"),
}
#: 네 번 이어 묻기 — 조사 → 견주어 적용 → 문서로 → 다시. 주제는 누구나 찾을 수 있는 공개 이야기다.
CHAIN_TASKS: dict[str, dict[str, Any]] = {
    "trail": {
        "names": ("올레",),
        "turns": (
            "제주 올레길이 어떻게 만들어지고 운영되는지 조사해서 정리해 줘",
            "그 방식이 동네 둘레길을 만드는 일과는 구체적으로 어디가 다른지, 작은 마을이 따라 하려면 어떻게 하면 좋을지 알려줘",
            "방금 내용을 워드 파일로 정리해 줘",
            "다시 해 줘. 이번에는 따라 하는 방법을 더 구체적으로 적어 줘",
        ),
    },
}
_READS = ("browser_extract", "browser_read")
_DONE = ("completed", "failed", "cancelled")
_DOC_ENDINGS = (".docx", ".hwpx", ".md", ".txt")
TASK_LIMIT_SEC = 25 * 60


# ── 채점 (글을 받아 숫자와 예 · 아니오만 돌려준다) ─────────────────────────────────────


def shop_of(cell: Any) -> str:
    low = str(cell or "").casefold().replace(" ", "")
    for shop, aliases in _SHOP_ALIASES.items():
        if shop.casefold() in low or any(alias in low for alias in aliases):
            return shop
    return ""


#: 값 칸의 머리 이름. ★ 2026-10-15 눈금 거짓말: 「가격」이 든 머리만 찾아서, 머리가 「판매가」인 표(세 줄 다 맞음)는
#: 셋째 칸(상품명)을 값으로 읽어 0/3 「값 없음」이 됐다. 「정가」는 값 칸이 아니다.
_PRICE_HEAD = re.compile(r"가격|판매가|최저가|price", re.IGNORECASE)


def is_price_head(name: Any) -> bool:
    return bool(_PRICE_HEAD.search(str(name or "")))


def price_column(head: list[Any]) -> int:
    return next((index for index, name in enumerate(head) if is_price_head(name)), 2)


#: 주소 칸. ★ 2026-10-15 눈금 거짓말 여섯째: `http` 로 시작하는 칸만 주소로 봐서, `prod.danawa.com/info/?pcode=…` 처럼
#: 앞을 뗀 주소를 적은 표(세 줄 다 맞음)가 0/3 「주소 틀림」이 됐다. 「이름.이름/…」 으로 **시작하면** 주소다(뒤에 붙은 메모는 둔다 —
#: 「https://… (정가 319,000원 → 할인)」 칸을 처음 고침이 놓쳐 옛·새 대조에서 점수가 내려간 줄로 드러났다).
_ADDRESS = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?/", re.IGNORECASE)


def is_address(cell: Any) -> bool:
    return bool(_ADDRESS.match(str(cell or "").strip()))


def row_shop(cells: list[Any]) -> str:
    """이 줄이 어느 가게의 줄인가 — 가게 이름이 처음 나오는 칸(주소 칸은 빼고).

    ★ 2026-10-15 눈금 거짓말: 첫 칸만 봤다. 「가게(판매처) | 사이트 | 상품 | 가격 …」처럼 첫 칸이 판매처 이름(Y SHOP)이고
      가게 이름이 둘째 칸에 있는 표가 세 줄 다 있는데도 「줄 없음」 0/3 으로 찍혔다. 주소 칸으로 가게를 정하면 「주소 틀림」을
      못 잡으니 주소는 빼고 본다.
    """
    for cell in cells:
        text = str(cell if cell is not None else "")
        if is_address(text):
            continue
        found = shop_of(text)
        if found:
            return found
    return ""


def grade_price_rows(rows: list[list[Any]], pages: list[dict[str, Any]]) -> dict[str, str]:
    """가게마다 한 낱말: 온전 · 줄 없음 · 값 없음 · 주소 틀림 · 값이 글에 없음.

    「온전」= 그 가게의 줄이 있고, 값이 있고, 주소가 그 가게의 상품 화면이고, 그 값이 **그 가게에서 읽은 글에 실제로 있다.**
    """
    head = [str(cell or "") for cell in (rows[0] if rows else [])]
    price_col = price_column(head)
    text_of = {
        shop: "\n".join(str(page.get("text") or "") for page in pages if any(mark in str(page.get("url") or "") for mark in marks))
        for shop, marks in SHOPS.items()
    }
    out: dict[str, str] = {}
    for row in rows[1:]:
        cells = [str(cell if cell is not None else "") for cell in row]
        shop = row_shop(cells)
        if not shop or shop in out:
            continue
        price = cells[price_col] if len(cells) > price_col else ""
        numbers = [found.replace(",", "") for found in re.findall(r"\d{1,3}(?:,\d{3})+|\d{5,}", price)]
        address = next((cell.strip() for cell in cells if is_address(cell)), "")
        if not numbers:
            out[shop] = "값 없음"
        elif not any(mark in address for mark in SHOPS[shop]):
            out[shop] = "주소 틀림"
        elif f"{int(numbers[0]):,}" in text_of[shop] or numbers[0] in text_of[shop]:
            out[shop] = "온전"
        else:
            out[shop] = "값이 글에 없음"
    for shop in SHOPS:
        out.setdefault(shop, "줄 없음")
    return out


def price_causes(rows: list[list[Any]], pages: list[dict[str, Any]], steps: list[dict[str, Any]]) -> dict[str, str]:
    """가게마다 **왜** 그 칸이 온전하지 않은가 — `CAUSES` 의 한 낱말.

    ★ 밖에서 받은 지적(2026-10-13): 「줄이 틀렸다」를 까닭별로 나눠라 — 페이지를 못 찾았나 · 값을 잘못 읽었나 · 읽고 잃었나.
      셋은 고침이 다르다. 개발 PC 에서 그렇게 갈라 보니 창 32K 의 틀린 29칸 중 19칸이 「상품 페이지까지 못 감」이었다
      (`bench/skillpack_price/by_cause.py` — 같은 규칙이다). 실제 카드에서도 같은 낱말로 가른다.

    `steps` 는 걸음마다 `{tool, ok, url(닿은 주소), aim(인자 글)}`. 주소와 인자는 여기서만 쓰고 결과에는 싣지 않는다.
      - 브라우저 걸음만 본다 — 문서를 쓰는 걸음에 가게 이름이 적혀 있다고 그 가게에 간 것이 아니다.
      - 검색 엔진에 가게 이름을 넣어 찾은 것은 겨눈 것이지 들어간 것이 아니다.
    """
    head = [str(cell or "") for cell in (rows[0] if rows else [])]
    price_col = price_column(head)
    out: dict[str, str] = {}
    for shop, marks in SHOPS.items():
        names = _SHOP_HOSTS[shop]
        aimed = entered = opened = read = False
        for step in steps:
            if not str(step.get("tool") or "").startswith("browser_"):
                continue
            landed = str(step.get("url") or "").lower()
            if not any(name in landed + " " + str(step.get("aim") or "").lower() for name in names):
                continue
            aimed = True
            if not step.get("ok") or names[0] not in landed:
                continue
            entered = True
            if any(mark in landed for mark in marks):
                opened = True
                read = read or step.get("tool") in _PAGE_READS
        if not read:
            out[shop] = "열고 안 읽음" if opened else "목록에서 못 엶" if entered else "가려다 막힘" if aimed else "안 감"
            continue
        row = next((line for line in rows[1:] if line and row_shop(line) == shop), None)
        cells = [str(cell if cell is not None else "") for cell in row or []]
        price = cells[price_col] if len(cells) > price_col else ""
        numbers = [found.replace(",", "") for found in re.findall(r"\d{1,3}(?:,\d{3})+|\d{5,}", price)]
        address = next((cell.strip() for cell in cells if is_address(cell)), "")
        text = "\n".join(str(page.get("text") or "") for page in pages if any(mark in str(page.get("url") or "") for mark in marks))
        if len(rows) < 2:
            out[shop] = "표 없이 끝남"
        elif not numbers:
            out[shop] = "읽고 잃음"
        elif text and not (f"{int(numbers[0]):,}" in text or numbers[0] in text):
            out[shop] = "잘못 읽음"
        elif not any(mark in address for mark in marks):
            out[shop] = "주소만 틀림"
        else:
            out[shop] = "온전"
    return out


def speed_of(model_time: Any) -> dict[str, float]:
    """그 판에서 모델이 쓴 속도(초당 토큰) — 쓰기와 읽기. 손자리가 적어 둔 `model_time` 에서 나눈다. 없으면 빈 것."""
    found: dict[str, float] = {}
    if not isinstance(model_time, dict):
        return found
    for name, tokens, seconds in (("gen_tokens_per_sec", "generated_tokens", "generate_sec"),
                                  ("prefill_tokens_per_sec", "prompt_tokens", "prefill_sec")):
        try:
            count, took = float(model_time.get(tokens) or 0), float(model_time.get(seconds) or 0)
        except (TypeError, ValueError):
            continue
        if count > 0 and took > 0:
            found[name] = round(count / took, 1)
    return found


# ── 과제가 끝나면 자기가 연 탭을 닫는다 ───────────────────────────────────────────────


def tabs_now(chrome: Callable[..., Any]) -> dict[str, str] | None:
    """손자리 크롬의 탭들(번호 → 주소). 크롬이 답하지 않으면 None — 그때는 아무것도 닫지 않는다."""
    try:
        return {str(tab["id"]): str(tab.get("url") or "") for tab in chrome("/json/list") if isinstance(tab, dict) and tab.get("type") == "page"}
    except Exception:  # noqa: BLE001
        return None


def close_tabs_the_task_left(chrome: Callable[..., Any], before: dict[str, str] | None) -> int:
    """과제가 **새로 열었거나 다른 사이트로 옮겨 놓은** 탭만 닫는다. 닫은 수를 돌려준다.

    ★ 2026-10-13: 손자리는 일하는 동안 크롬을 화면 밖에 펴 둔다. 재는 판이 연 가게 페이지가 그대로 남아 소리를 냈고
      (광고), PC 주인은 어디서 나는 소리인지 몰라 놀랐다. 남의 PC 에서 밤새 도는 도구가 그러면 안 된다.
    과제 전에 있던 탭이 같은 사이트에 그대로 있으면 사람의 탭으로 보고 건드리지 않는다. 마지막 탭까지 닫으면 창이
    닫히므로, 그 전에 빈 탭을 하나 만든다.
    """
    if before is None:
        return 0
    after = tabs_now(chrome)
    if after is None:
        return 0

    def host(url: str) -> str:
        return urllib.parse.urlparse(url).netloc.lower()

    mine = [tab for tab, url in after.items() if tab not in before or host(before[tab]) != host(url)]
    if not mine:
        return 0
    closed = 0
    try:
        if len(mine) >= len(after):
            chrome("/json/new?about:blank", "PUT")
        for tab in mine:
            chrome(f"/json/close/{tab}")
            closed += 1
    except Exception:  # noqa: BLE001
        pass
    return closed


def squash(text: Any) -> str:
    return "".join(urllib.parse.unquote_plus(str(text or "")).casefold().split())


def looks_looped(answer: str) -> bool:
    """같은 토막이 네 번 이어지거나 답이 6천 자를 넘는다 — 「같은 말을 되풀이했다」의 거친 자."""
    from .ollama import content_is_stuttering

    return bool(content_is_stuttering(answer)) or len(answer) > 6000


def grade_chain(names: tuple[str, ...], turns: list[dict[str, Any]]) -> dict[str, Any]:
    """네 판의 기록 → 판마다 예 · 아니오. 글은 여기서 읽고 버린다."""
    wanted = [squash(name) for name in names]

    def has(text: Any) -> bool:
        return any(name in squash(text) for name in wanted)

    first, second, third, fourth = (turns + [{}] * 4)[:4]
    doc3 = max((str(text) for text in third.get("doc_texts") or []), key=len, default="")
    doc4 = max((str(text) for text in fourth.get("doc_texts") or []), key=len, default="")
    return {
        "first_answered": has(first.get("answer")) and not first.get("asked"),
        "second": {"kept_topic": has(second.get("answer")), "no_loop": not looks_looped(str(second.get("answer") or "")),
                   "did_not_ask_back": not second.get("asked")},
        "third": {"made_file": bool(third.get("doc_texts")), "file_chars": len(doc3.strip()),
                  "file_has_text": len(doc3.strip()) >= 300, "file_kept_topic": has(doc3)},
        "fourth": {"did_not_ask_back": not fourth.get("asked"), "did_not_ask_another_ai": not fourth.get("asked_another_ai"),
                   "kept_topic": has(fourth.get("answer")) or has(doc4)},
    }


def document_text(path: Any) -> str:
    """만든 문서의 글자. 못 읽으면 빈 글 — 그것도 결과다(빈 파일이면 0자)."""
    target = Path(str(path or ""))
    if not target.is_file():
        return ""
    try:
        ending = target.suffix.lower()
        if ending == ".docx":
            import docx  # 문서 쓰기가 쓰는 그 묶음이다

            document = docx.Document(str(target))
            cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
            return "\n".join([paragraph.text for paragraph in document.paragraphs] + cells)
        if ending == ".hwpx":
            import zipfile

            with zipfile.ZipFile(target) as archive:
                parts = [archive.read(name).decode("utf-8", "replace") for name in archive.namelist() if name.startswith("Contents/section")]
            return "\n".join(re.sub(r"<[^>]+>", " ", part) for part in parts)
        if ending in {".md", ".txt"}:
            return target.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — 못 읽은 것은 0자로 센다
        return ""
    return ""


def sheet_rows(path: Any) -> list[list[str]]:
    try:
        import openpyxl

        book = openpyxl.load_workbook(str(path), data_only=True)
    except Exception:  # noqa: BLE001
        return []
    return [["" if cell is None else str(cell) for cell in row] for sheet in book.worksheets for row in sheet.iter_rows(values_only=True)]


# ── 이 PC ───────────────────────────────────────────────────────────────────


def graphics_cards() -> list[dict[str, Any]]:
    """카드마다 이름 · 전체 · 지금 쓰는 메모리(MB). 엔비디아 도구가 없으면 빈 목록."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return []
    cards = []
    for line in (done.stdout or "").strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            cards.append({"name": parts[0], "total_mb": int(parts[1]), "used_mb": int(parts[2])})
    return cards


def screen_share_mb(cards: list[dict[str, Any]], model_vram_bytes: int) -> int | None:
    """모델을 올린 카드에서 **모델 말고 쓰이는 메모리** — 화면과 다른 프로그램의 몫. 카드가 하나일 때만 말한다."""
    if len(cards) != 1:
        return None
    return max(0, int(cards[0]["used_mb"]) - int(model_vram_bytes) // (1024 * 1024))


# ── 손자리와 말하기 ──────────────────────────────────────────────────────────────


class Sonjari:
    def __init__(self, base_url: str, token: str, ollama_url: str = "http://127.0.0.1:11434", chrome_port: int = 0) -> None:
        self.base_url, self.token, self.ollama_url = base_url.rstrip("/"), token, ollama_url.rstrip("/")
        self.chrome_port = int(chrome_port or 0)

    def chrome(self, path: str, method: str = "GET") -> Any:
        """손자리가 쓰는 크롬의 탭 목록 · 닫기(이 PC 안에서만 열린 문). 문이 없으면 예외 — 부른 쪽이 넘어간다."""
        if not self.chrome_port:
            raise OSError("no chrome port")
        request = urllib.request.Request(f"http://127.0.0.1:{self.chrome_port}{path}", method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except ValueError:
            return body

    def call(self, path: str, body: dict[str, Any] | None = None, *, timeout: float = 60) -> Any:
        request = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"X-JARVIS-TOKEN": self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def health(self) -> dict[str, Any]:
        return self.call("/health", timeout=20) or {}

    def busy(self) -> bool:
        jobs = self.call("/v1/jobs?limit=30&view=summary", timeout=20)
        rows = jobs if isinstance(jobs, list) else (jobs or {}).get("jobs") or []
        return any(str(row.get("status")) in {"running", "queued", "waiting_approval"} for row in rows if isinstance(row, dict))

    def loaded_model(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(self.ollama_url + "/api/ps", timeout=10) as response:
                models = (json.loads(response.read().decode("utf-8")) or {}).get("models") or []
        except Exception:  # noqa: BLE001
            return {}
        return dict(models[0]) if models else {}

    def run(self, prompt: str, session: str, *, limit: float = TASK_LIMIT_SEC, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
        """한 판을 돌리고 채점에 쓸 것을 모아 돌려준다. 여기서 모은 글은 부른 쪽이 채점한 뒤 버린다."""
        tabs_before = tabs_now(self.chrome)
        job = self.call("/v1/chat", {"prompt": prompt, "origin": "mcp", "open_results": False, "session_id": session})
        job_id = str(job.get("job_id") or job.get("id") or "")
        started, info, asked = time.time(), {}, False
        while time.time() - started < limit:
            try:
                info = self.call(f"/v1/jobs/{job_id}") or {}
            except Exception:  # noqa: BLE001
                sleep(5)
                continue
            status = str(info.get("status"))
            if status in _DONE:
                break
            if status == "waiting_approval":
                # 물으며 선 판 — 여기에는 답할 사람이 없다. 닫고 그렇게 적는다.
                asked = True
                self._cancel(job_id)
                break
            sleep(5)
        else:
            self._cancel(job_id)
        result = info.get("result") if isinstance(info.get("result"), dict) else {}
        trace = result.get("agent_trace") if isinstance(result.get("agent_trace"), dict) else {}
        steps = [step for step in trace.get("steps") or [] if isinstance(step, dict)]
        check = trace.get("verification") if isinstance(trace.get("verification"), dict) else {}
        pages, sheets, docs = [], [], []
        for number, step in enumerate(steps, 1):
            evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
            if step.get("ok") and step.get("tool") in _READS:
                try:
                    payload = (self.call(f"/v1/jobs/{job_id}/steps/{number}") or {}).get("payload") or {}
                except Exception:  # noqa: BLE001
                    payload = {}
                pages.append({"url": payload.get("url") or evidence.get("url"), "text": str(payload.get("text") or "")})
            if step.get("ok") and step.get("tool") == "local_write_document":
                made = str(evidence.get("output_path") or "")
                if made.lower().endswith(".xlsx"):
                    sheets.append(made)
                elif made.lower().endswith(_DOC_ENDINGS):
                    docs.append(made)
        prompts = [int((seen.get("telemetry") or {}).get("prompt_eval_count") or 0) for seen in check.get("inference_observations") or [] if isinstance(seen, dict)]
        graded = []
        for step in steps:
            evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
            graded.append({"tool": str(step.get("tool")), "ok": bool(step.get("ok")), "url": str(evidence.get("url") or ""),
                           "aim": json.dumps(step.get("arguments") or {}, ensure_ascii=False)[:2000]})
        return {
            **speed_of(check.get("model_time")),
            "closed_tabs": close_tabs_the_task_left(self.chrome, tabs_before),
            "status": str(info.get("status") or "timed_out"), "state": str(result.get("completion_state") or ""),
            "asked": asked, "sec": round(time.time() - started), "steps": len(steps),
            "stop_reason": str(check.get("stop_reason") or ""), "pushbacks": int(check.get("plan_pushbacks") or 0),
            "largest_prompt_tokens": max(prompts, default=0),
            # ★ 창이 꽉 차 모델의 말이 잘린 호출 수 (2026-10-15 · 레딧에서 받은 물음 「표 없이 끝난 판은 창에 잘린 것 아니냐」).
            #   이 PC 기록으로는 10-11 고침 뒤 0건이었지만 남의 PC 결과 파일에는 이 칸이 없어 가를 수가 없었다.
            "length_cuts": sum(1 for cut in check.get("content_cuts") or [] if isinstance(cut, dict) and cut.get("why") == "length_limit"),
            "refused_steps": sum(1 for step in steps if not step.get("ok")),
            "asked_another_ai": any(str(step.get("error") or "").startswith("asks_another_ai") for step in steps),
            "tools": [{"tool": str(step.get("tool")), "ok": bool(step.get("ok")), "error": str(step.get("error") or "").split(" ")[0][:40]} for step in steps],
            # 아래는 채점에만 쓰고 결과 파일에는 싣지 않는다.
            "answer": str(result.get("answer") or ""), "pages": pages, "sheet_paths": sheets, "doc_paths": docs,
            "steps_for_grading": graded,
        }

    def _cancel(self, job_id: str) -> None:
        try:
            self.call(f"/v1/jobs/{job_id}/cancel", {})
        except Exception:  # noqa: BLE001
            pass


_KEEP = ("status", "state", "asked", "sec", "steps", "stop_reason", "pushbacks", "largest_prompt_tokens", "length_cuts",
         "refused_steps", "gen_tokens_per_sec", "prefill_tokens_per_sec", "closed_tabs")


def numbers_only(run: dict[str, Any], *, with_steps: bool) -> dict[str, Any]:
    """한 판의 기록에서 **결과 파일에 실어도 되는 것만** 남긴다 — 글 · 주소 · 파일 이름은 여기서 떨어진다."""
    kept = {key: run.get(key) for key in _KEEP if key in run}
    if with_steps:
        kept["tools"] = [{"tool": item["tool"], "ok": item["ok"], "error": item["error"]} for item in run.get("tools") or []]
    return kept


def _input_idle_seconds() -> float | None:
    """사람이 마지막으로 키보드 · 마우스를 쓴 뒤 지난 초(윈도우). 잴 수 없으면 None — 그때는 비어 있다고 본다."""
    try:
        from .user_presence import idle_seconds

        return idle_seconds()
    except Exception:  # noqa: BLE001
        return None


def wait_until_free(sonjari: Sonjari, *, idle_sec: int, patience_sec: int, say: Callable[[str], None],
                    sleep: Callable[[float], None] = time.sleep,
                    input_idle: Callable[[], float | None] = _input_idle_seconds) -> bool:
    """손자리가 쉬고 사람도 손을 뗀 뒤에 돌려준다. 끝내 안 비면 False — 그 과제는 건너뛴다."""
    waited = 0
    while True:
        try:
            busy = sonjari.busy()
        except Exception:  # noqa: BLE001
            busy = True
        seen = input_idle()
        idle = float(idle_sec) if seen is None else float(seen)
        if not busy and idle >= idle_sec:
            return True
        if waited >= patience_sec:
            return False
        say("  쓰는 중이라 기다립니다" + (" (손자리가 다른 일을 하는 중)" if busy else f" (마지막 입력 {int(idle)}초 전)"))
        sleep(30)
        waited += 30


def measure(sonjari: Sonjari, *, only: str, rounds: int, rest_sec: int, idle_sec: int, patience_sec: int,
            with_steps: bool, say: Callable[[str], None], sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    cards_before = graphics_cards()
    health = sonjari.health()
    out: dict[str, Any] = {"kit": KIT_VERSION, "started": time.strftime("%Y-%m-%d %H:%M"), "price": [], "chain": [], "skipped": 0}
    wants_price, wants_chain = only in {"all", "price"}, only in {"all", "chain"}
    for round_no in range(1, rounds + 1):
        for key, prompt in (PRICE_TASKS.items() if wants_price else ()):
            if idle_sec >= 0 and not wait_until_free(sonjari, idle_sec=idle_sec, patience_sec=patience_sec, say=say, sleep=sleep):
                out["skipped"] += 1
                continue
            say(f"[{round_no}/{rounds}] 가격 · {key} …")
            run = sonjari.run(prompt, "measure-price-" + uuid.uuid4().hex[:8], sleep=sleep)
            rows = sheet_rows(run["sheet_paths"][-1]) if run["sheet_paths"] else []
            shops = grade_price_rows(rows, run["pages"])
            out["price"].append({"task": key, "round": round_no, "made_sheet": bool(run["sheet_paths"]),
                                 "rows": max(0, len(rows) - 1), "shops": shops,
                                 "causes": price_causes(rows, run["pages"], run.get("steps_for_grading") or []),
                                 "whole_rows": sum(1 for state in shops.values() if state == "온전"),
                                 **numbers_only(run, with_steps=with_steps)})
            say(f"    {run['sec']}초 · 걸음 {run['steps']} · 온전한 줄 {out['price'][-1]['whole_rows']}/3" + (" · 물으며 섬" if run["asked"] else ""))
            sleep(rest_sec)
        for key, chain in (CHAIN_TASKS.items() if wants_chain else ()):
            if idle_sec >= 0 and not wait_until_free(sonjari, idle_sec=idle_sec, patience_sec=patience_sec, say=say, sleep=sleep):
                out["skipped"] += 1
                continue
            say(f"[{round_no}/{rounds}] 이어 묻기 · {key} …")
            session = "measure-chain-" + uuid.uuid4().hex[:8]
            turns = []
            for prompt in chain["turns"]:
                run = sonjari.run(prompt, session, limit=15 * 60, sleep=sleep)
                run["doc_texts"] = [document_text(path) for path in run["doc_paths"]]
                turns.append(run)
            verdict = grade_chain(tuple(chain["names"]), turns)
            out["chain"].append({"chain": key, "round": round_no, "verdict": verdict,
                                 "turns": [numbers_only(run, with_steps=with_steps) for run in turns]})
            say("    둘째 " + _marks(verdict["second"]) + " · 셋째 " + _marks({k: v for k, v in verdict["third"].items() if k != "file_chars"})
                + f"(파일 글 {verdict['third']['file_chars']}자) · 넷째 " + _marks(verdict["fourth"]))
            sleep(rest_sec)
    out["price_summary"] = price_summary(out["price"])
    model = sonjari.loaded_model()
    cards_after = graphics_cards()
    vram = int(model.get("size_vram") or 0)
    out["pc"] = {
        "windows": platform.platform(), "cards": cards_after or cards_before,
        "cards_before_start": cards_before,
        "model": str(model.get("name") or (health.get("ollama") or {}).get("model") or "")[-60:],
        "window": int(model.get("context_length") or (health.get("ollama") or {}).get("num_ctx") or 0),
        "model_on_card_mb": vram // (1024 * 1024), "model_total_mb": int(model.get("size") or 0) // (1024 * 1024),
        "on_card_share": round(vram / int(model["size"]), 3) if model.get("size") else None,
        "screen_and_others_mb": screen_share_mb(cards_after, vram),
        "sonjari_build": str(health.get("build") or ""),
    }
    out["finished"] = time.strftime("%Y-%m-%d %H:%M")
    return out


# 「이 차이를 가려내려면 조건마다 몇 판」을 말해 줄 차이들(온전한 줄 수).
_TELL_APART = (2, 3)
_FEWEST_ROUNDS = 3


def price_summary(price_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """가격 조사 판들을 **판 사이의 흔들림**까지 요약한다 — 숫자와 정해진 낱말뿐이다.

    ★ 밖에서 받은 지적(2026-10-13): 한 조건을 세 번 재고 두 조건을 견줬는데, 같은 조건 여덟 판이 평균 4.6줄 · 흔들림 2.2줄로
      오르내렸다. 합계 한 줄만 적으면 그 숫자를 믿을 만한지 읽는 사람이 알 길이 없다.

    - `per_round` 판마다 온전한 줄의 합(과제가 다 돈 판만 — 빠진 판의 합은 다른 판과 견줄 수 없다)
    - `spread` 그 합들의 표본 표준편차. **세 판부터** 말한다(두 판의 차이로 흔들림을 말하면 그 숫자가 다시 우연이다)
    - `rounds_to_tell` 두 조건의 차이가 이만큼일 때 조건마다 필요한 판 수 ≈ 16 × (흔들림 ÷ 차이)². 세 판보다 적게 말하지 않는다
    - `short_rows` 온전하지 못한 줄을 까닭별로(`grade_price_rows` 의 낱말)
    """
    if not price_runs:
        return {}
    by_round: dict[int, list[dict[str, Any]]] = {}
    for run in price_runs:
        by_round.setdefault(int(run.get("round") or 0), []).append(run)
    tasks = max(len(runs) for runs in by_round.values())
    whole = [sum(int(run.get("whole_rows") or 0) for run in runs) for _number, runs in sorted(by_round.items()) if len(runs) == tasks]
    short: dict[str, int] = {}
    for run in price_runs:
        for state in (run.get("shops") or {}).values():
            if state != "온전":
                short[str(state)] = short.get(str(state), 0) + 1
    mean = round(sum(whole) / len(whole), 1) if whole else None
    causes: dict[str, int] = {}
    for run in price_runs:
        for cause in (run.get("causes") or {}).values():
            if cause != "온전":
                causes[str(cause)] = causes.get(str(cause), 0) + 1
    groups: dict[str, int] = {}
    for cause, count in causes.items():
        groups[_CAUSE_GROUP.get(cause, cause)] = groups.get(_CAUSE_GROUP.get(cause, cause), 0) + count

    def middle(values: list[float]) -> float | None:
        ordered = sorted(values)
        if not ordered:
            return None
        half = len(ordered) // 2
        return ordered[half] if len(ordered) % 2 else round((ordered[half - 1] + ordered[half]) / 2, 1)

    def middle_of(key: str) -> float | None:
        return middle([float(run[key]) for run in price_runs if isinstance(run.get(key), (int, float)) and not isinstance(run.get(key), bool)])

    spread = None
    if len(whole) >= _FEWEST_ROUNDS:
        centre = sum(whole) / len(whole)
        spread = round(math.sqrt(sum((value - centre) ** 2 for value in whole) / (len(whole) - 1)), 1)
    return {
        "per_round": whole, "out_of": len(SHOPS) * tasks, "incomplete_rounds": len(by_round) - len(whole),
        "mean": mean, "spread": spread,
        # 2와 9가 같이 나오는 일에서는 평균보다 가운데 값과 범위가 덜 속인다(밖에서 받은 지적).
        "median": middle([float(value) for value in whole]), "low": min(whole) if whole else None, "high": max(whole) if whole else None,
        "causes": dict(sorted(causes.items(), key=lambda item: (-item[1], item[0]))),
        "cause_groups": dict(sorted(groups.items(), key=lambda item: (-item[1], item[0]))),
        "sec_median": middle_of("sec"), "gen_tokens_per_sec_median": middle_of("gen_tokens_per_sec"),
        "prefill_tokens_per_sec_median": middle_of("prefill_tokens_per_sec"),
        "rounds_to_tell": None if spread is None else {
            str(gap): max(_FEWEST_ROUNDS, math.ceil(16 * (spread / gap) ** 2)) for gap in _TELL_APART
        },
        "short_rows": dict(sorted(short.items(), key=lambda item: (-item[1], item[0]))),
    }


def summary_lines(summary: dict[str, Any]) -> list[str]:
    """끝 인사에 붙일 줄들 — 합계 옆에 그 숫자가 얼마나 흔들리는지."""
    if not summary or not summary.get("per_round"):
        return []
    rounds = summary["per_round"]
    def whole_number(value: Any) -> Any:
        return int(value) if isinstance(value, float) and value.is_integer() else value

    lines = [f"판마다 온전한 줄(/{summary['out_of']}): " + " · ".join(str(value) for value in rounds) + f" — 평균 {summary['mean']}"
             + (f" · 가운데 값 {whole_number(summary['median'])} · 범위 {summary['low']}~{summary['high']}" if summary.get("median") is not None else "")]
    if summary.get("spread") is None:
        lines.append(f"판 사이의 흔들림은 {_FEWEST_ROUNDS}판부터 말할 수 있습니다(--rounds {_FEWEST_ROUNDS}). 지금 숫자는 「이 PC 에서 한 번 이랬다」까지입니다.")
    else:
        tell = summary["rounds_to_tell"]
        lines.append(f"판 사이의 흔들림 {summary['spread']}줄. 다른 조건과 견줄 때 " + " · ".join(
            f"{gap}줄 차이는 조건마다 {tell[str(gap)]}판" for gap in _TELL_APART) + "쯤 재야 우연과 가려집니다.")
    if summary.get("cause_groups"):
        lines.append("온전하지 못한 칸의 까닭: " + " · ".join(f"{name} {count}" for name, count in summary["cause_groups"].items())
                     + " (자세히: " + " · ".join(f"{name} {count}" for name, count in summary["causes"].items()) + ")")
    elif summary.get("short_rows"):
        lines.append("온전하지 못한 줄: " + " · ".join(f"{name} {count}" for name, count in summary["short_rows"].items()))
    if summary.get("sec_median") is not None:
        speed = summary.get("gen_tokens_per_sec_median")
        lines.append(f"과제 하나에 걸린 시간(가운데 값) {whole_number(summary['sec_median'])}초"
                     + (f" · 쓰는 속도 초당 {speed}토큰" if speed is not None else ""))
    return lines


def _marks(flags: dict[str, Any]) -> str:
    return "".join("O" if value else "X" for value in flags.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alture_jarvis.measure_kit", description="이 PC 의 손자리로 같은 과제를 돌려 숫자만 든 결과 파일을 남깁니다.")
    parser.add_argument("--only", choices=("all", "price", "chain"), default="all")
    parser.add_argument("--rounds", type=int, default=1, help="같은 과제 묶음을 몇 번 돌릴지(「이 카드에서는 이렇다」를 말하려면 3 · 두 조건을 견주려면 7 이상)")
    parser.add_argument("--rest", type=int, default=60, help="과제 사이에 쉬는 초")
    parser.add_argument("--idle", type=int, default=120, help="마지막 키보드 · 마우스 입력 뒤 이만큼 지나야 시작")
    parser.add_argument("--patience", type=int, default=30 * 60, help="쓰는 중일 때 과제마다 기다릴 최대 초")
    parser.add_argument("--now", action="store_true", help="쓰는 중인지 보지 않고 바로 시작")
    parser.add_argument("--with-steps", action="store_true", help="걸음의 도구 이름 · 오류 이름까지 싣기(글 · 인자는 안 싣는다)")
    parser.add_argument("--out", default="", help="결과를 둘 폴더(기본: 문서\\Sonjari-measure)")
    parser.add_argument("--token-file", default="", help="손자리의 연결 토큰 파일(보통은 알아서 찾는다)")
    parser.add_argument("--base-url", default="", help="손자리의 주소(보통은 알아서 찾는다)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

    from .config import JarvisConfig, setting

    config = JarvisConfig.from_env()
    # 주소와 토큰은 연결 진입점(`mcp_server`)과 같은 차례로 찾는다 — 인자, 환경(`JARVIS_TOKEN_FILE` · `JARVIS_BASE_URL`), 설정의 기본 자리.
    # ★ 첫 실제 실행(2026-10-13 개발 PC)에서 기본 자리의 **옛 토큰**을 집어 401 이 났다 — 이 PC 의 손자리는 다른 폴더에서 돈다.
    token_path = Path(args.token_file or setting("JARVIS_TOKEN_FILE") or Path(config.data_dir) / "control.token")
    if not token_path.is_file():
        print("손자리의 연결 토큰을 찾지 못했습니다 — 손자리를 한 번 켠 뒤 다시 해 주세요.")
        return 2
    host = str(getattr(config, "host", "127.0.0.1") or "127.0.0.1")
    host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    base_url = args.base_url or setting("JARVIS_BASE_URL") or f"http://{host}:{int(config.port)}"
    sonjari = Sonjari(base_url, token_path.read_text(encoding="utf-8").strip(), str(config.ollama_base_url),
                      chrome_port=int(getattr(config, "browser_cdp_port", 0) or 0))
    try:
        sonjari.health()
        sonjari.busy()  # 토큰이 맞는지 — 과제를 돌리기 전에 안다
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            print("손자리가 이 연결을 받지 않았습니다(토큰이 맞지 않습니다). 손자리가 다른 폴더에서 돌고 있다면 "
                  "--token-file 로 그 폴더의 control.token 을 알려 주세요.")
        else:
            print(f"손자리가 답하지 못했습니다(HTTP {error.code}). 손자리를 다시 켠 뒤 해 주세요.")
        return 2
    except (urllib.error.URLError, OSError) as error:
        print(f"손자리에 연결하지 못했습니다 — 손자리가 켜져 있는지 확인해 주세요. ({type(error).__name__})")
        return 2
    folder = Path(args.out) if args.out else Path.home() / "Documents" / "Sonjari-measure"
    folder.mkdir(parents=True, exist_ok=True)
    print("이 PC 의 손자리로 재 봅니다. 크롬이 혼자 열렸다 닫힙니다 — 끝날 때까지 손자리로 다른 일을 시키지 말아 주세요.")
    result = measure(
        sonjari, only=args.only, rounds=max(1, args.rounds), rest_sec=max(0, args.rest), idle_sec=-1 if args.now else max(0, args.idle),
        patience_sec=max(0, args.patience), with_steps=bool(args.with_steps), say=print,
    )
    stamp = time.strftime("%Y%m%d-%H%M")
    target = folder / f"measure_{stamp}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (folder / "measure_log.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"finished": result["finished"], "started": result["started"], "only": args.only, "rounds": args.rounds,
                              "price_runs": len(result["price"]), "chain_runs": len(result["chain"]), "skipped": result["skipped"],
                              "file": target.name}, ensure_ascii=False) + "\n")
    whole = sum(run["whole_rows"] for run in result["price"])
    print(f"끝났습니다. 가격 조사 온전한 줄 {whole}/{3 * len(result['price'])} · 이어 묻기 {len(result['chain'])}줄기")
    for line in summary_lines(result.get("price_summary") or {}):
        print("  " + line)
    print(f"결과 파일: {target}")
    print("이 파일에는 숫자와 예 · 아니오만 들어 있습니다(읽은 글 · 주소 · 답은 없습니다).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
