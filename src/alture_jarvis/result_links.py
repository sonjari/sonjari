"""목록 화면에서 **항목으로 가는 주소**가 어떻게 생겼는지 — 사이트 지식을 자료로 둔다.

★ 2026-10-05 9B 판 둘:
    arXiv 목록    `browser_open_result` 1·2·3 이 「본문으로 건너뛰기」·날짜 넘김 링크를 열었다 — 같은 목록을 세 번 읽음
    네이버 뉴스   순위 2번이 「24개의 관련뉴스 더보기」였다

목록 판정기(`browser._RESULT_LIST_JS`)를 고쳐 보려 했으나(부모가 다른 묶음은 합치지 않기) 얼린 표본에서 다나와 74→9 ·
잡코리아 20→0 · 교보 20→7 로 깨져 되돌렸다. arXiv 는 제목이 링크가 아니고 항목 링크가 「arXiv:번호」 16자라, 구조만으로는
저자 링크 묶음과 못 가른다(표본 `arxiv_list` 가 그 자리를 빨간불로 들고 있다).

그래서 판정기가 못 가르는 사이트는 **상세 주소의 표식**을 적어 둔다. 검토한 레시피(`site_recipes`)의 `result_url_contains` 와
같은 것인데, 검색 절차 없이 표식만 있는 가벼운 꼴이다. 파일은 `recipes/result_links/*.json`. 레시피에 표식이 있으면 그것이 먼저다.
표식은 그 사이트의 화면을 직접 열어 확인한 것만 적는다(`checked`).

★ 2026-10-12 G마켓: 광고 카드가 상품과 **같은 주소 꼴**이다(`item.gmarket.co.kr/Item?goodscode=…`) — 꼬리에
  `buyboxtype=ad` 하나가 더 붙을 뿐이다. 「이 꼴만 센다」로는 못 가른다. 파일에 `not_url_contains` 를 적으면 그 글이 든
  주소는 뺀다. 표식 목록은 글자 목록 그대로 흐르므로(`browser._filter_reviewed_results` 까지 네 군데) 빼는 표식은
  앞에 `!` 를 붙여 같은 목록에 싣는다(`EXCLUDE`).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LINKS_DIR = Path(__file__).resolve().parents[2] / "recipes" / "result_links"
# 표식 앞에 붙으면 「이 글이 든 주소는 뺀다」.
EXCLUDE = "!"


@lru_cache(maxsize=4)
def load(directory: str = "") -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """(호스트들, 표식들) 묶음. 깨진 파일은 건너뛴다 — 표식 하나 때문에 판을 죽이지 않는다."""
    folder = Path(directory) if directory else LINKS_DIR
    found: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            hosts = tuple(str(host).casefold().removeprefix("www.") for host in raw.get("hosts") or [] if str(host).strip())
            marks = tuple(str(mark) for mark in raw.get("detail_url_contains") or [] if str(mark).strip())
            marks += tuple(EXCLUDE + str(mark) for mark in raw.get("not_url_contains") or [] if str(mark).strip())
        except Exception:  # noqa: BLE001
            continue
        if hosts and marks:
            found.append((hosts, marks))
    return tuple(found)


def markers_for(host: str, directory: str = "") -> list[str]:
    """이 호스트의 화면에서 항목 주소가 품는 표식들. 모르는 사이트면 빈 목록 — 그러면 아무것도 거르지 않는다."""
    name = str(host or "").casefold().removeprefix("www.")
    if not name:
        return []
    for hosts, marks in load(directory):
        if any(name == item or name.endswith("." + item) for item in hosts):
            return list(marks)
    return []
