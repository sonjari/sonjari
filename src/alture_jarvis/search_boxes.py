"""사이트 검색칸의 버릇 — **확인한 사이트만** 자료로 둔다.

★ 2026-10-12 운영 기록(10-02 ~ 10-12 · 켜진 것 24번):
    「여러 낱말 검색 결과에 첫 낱말이 안 보이면 그 낱말 하나로 다시 찾는다」(`browser._retry_with_head_word`)는
    K-Startup 한 곳에서 본 것으로 **모든 사이트**에 걸려 있었다. 그 뒤 켜진 24번 가운데 모델이 다시 찾은 결과를
    그대로 연 것은 1번, 바로 다시 검색한 것이 13번, 다른 주소를 직접 연 것이 7번이었다.
    가게에서는 첫 낱말이 **상표**다 — 상품 제목에 상표가 안 적힌 가게에서 상표 하나로 다시 찾으면 모델 번호가 사라진다.
    11번가에서 6번 · 네이버 가격비교에서 2번(모델은 세 낱말을 넣었는데 도구가 첫 낱말만 남겼다) · 다나와에서 1번.

그래서 이 버릇은 규칙이 아니라 **사이트 지식**이다. `result_links` · `page_values` 와 같은 꼴로, 그 사이트의 검색칸을
직접 써 보고 확인한 것만 `recipes/search_boxes/*.json` 에 적는다(`checked`). 모르는 사이트에서는 아무것도 안 한다 —
모델이 넣은 검색어를 말없이 바꾸지 않는다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BOXES_DIR = Path(__file__).resolve().parents[2] / "recipes" / "search_boxes"


@lru_cache(maxsize=4)
def load(directory: str = "") -> tuple[tuple[tuple[str, ...], frozenset[str]], ...]:
    """(호스트들, 버릇들) 묶음. 깨진 파일은 건너뛴다 — 자료 하나 때문에 판을 죽이지 않는다."""
    folder = Path(directory) if directory else BOXES_DIR
    found: list[tuple[tuple[str, ...], frozenset[str]]] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            hosts = tuple(str(host).casefold().removeprefix("www.") for host in raw.get("hosts") or [] if str(host).strip())
            habits = frozenset(key for key in ("needs_every_word",) if raw.get(key) is True)
        except Exception:  # noqa: BLE001
            continue
        if hosts and habits:
            found.append((hosts, habits))
    return tuple(found)


def needs_every_word(host: str, directory: str = "") -> bool:
    """이 사이트 검색칸은 넣은 낱말이 **다 맞아야** 결과가 나오는가. 모르는 사이트면 False."""
    name = str(host or "").casefold().removeprefix("www.")
    if not name:
        return False
    for hosts, habits in load(directory):
        if "needs_every_word" in habits and any(name == item or name.endswith("." + item) for item in hosts):
            return True
    return False
