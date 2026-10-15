"""사람이 검토한 절차는 **가로채지 않는다.**

## 내가 낸 회귀 (2026-08-13)

모델이 검색 주소를 손으로 조립하는 버릇을 잡으려고 `browser_open` 에 가로채기를
넣었다 — 검색 입구처럼 생긴 주소면 사이트로 들어가 검색칸에 쳐 넣는다.

그런데 `recipes/saramin.json` 의 주소가 이렇게 생겼다:

    https://www.saramin.co.kr/zf_user/search/recruit?searchword={query}

경로에 `/search`, 인자에 `searchword=` — **판정 조건에 정확히 걸린다.** 그래서
사람이 검토해 확정한 경로를 두고 홈으로 돌아가 검색칸을 찾기 시작했다.
벤치에서 사람인이 **150초 성공 → 204초 미달(⚠)** 로 뒤집혔다.

## 규칙: 신뢰는 인자가 아니라 문에서 온다

`{"trusted": true}` 같은 인자로 표시하면 모델이 그걸 얹어서 통과할 수 있다.
이 저장소는 그 구멍을 이미 한 번 뚫려 봤다(`_approved` 로 L2 승인 우회).
그래서 **호출 방식**으로 표시한다 — `execute(..., trusted=True)`. 모델이 부르는 문은
그 값을 안 넘기므로 스스로 켤 수 없고, 밑줄 인자는 애초에 떨어져 나간다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.browser import BrowserWorker

SARAMIN = "https://www.saramin.co.kr/zf_user/search/recruit?searchword=여수%20회계"


class _Worker:
    _handmade_search_query = BrowserWorker._handmade_search_query
    _HANDMADE_SEARCH = BrowserWorker._HANDMADE_SEARCH
    _SEARCH_ENTRY_PATH = BrowserWorker._SEARCH_ENTRY_PATH
    _SEARCH_ENGINE_HOSTS = BrowserWorker._SEARCH_ENGINE_HOSTS
    _QUERY_KEYS = BrowserWorker._QUERY_KEYS

    def __init__(self) -> None:
        self.typed: list[str] = []
        self.went: list[str] = []

    def _goto_checked(self, page: Any, url: str) -> None:
        self.went.append(url)

    _wait_until_operable = staticmethod(lambda page: {"count": 9, "ms": 1, "polls": 1})
    _mark_visited = staticmethod(lambda url: None)
    _evidence = staticmethod(lambda action, **kw: {"action": action, **kw})

    def _site_search(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        self.typed.append(str(arguments.get("query") or ""))
        return {"action": "site_searched"}


def test_the_recipe_url_looks_exactly_like_a_handmade_one() -> None:
    """왜 걸렸는지를 시험이 직접 보여 준다 — 판정만 봐서는 구별이 안 된다."""
    assert _Worker()._handmade_search_query(SARAMIN) == "여수 회계"


def test_an_untrusted_open_is_intercepted() -> None:
    """모델이 같은 주소를 지어내 오면 여전히 칸에 쳐 넣는다."""
    worker = _Worker()
    handed = BrowserWorker._search_like_a_person(worker, page=None, url=SARAMIN)

    assert handed is not None
    assert worker.typed == ["여수 회계"]


def test_the_recipe_runner_uses_the_trusted_door() -> None:
    """★ 문은 **이미 있었다** — `execute_trusted`.

    레시피의 press·click 은 진작 그 문으로 들어오고 있었는데 `open` 만 평범한 문을
    쓰고 있었다. 그래서 가로채기를 넣자마자 거기서 새어 나갔다. 새 장치를 만들 게
    아니라 있는 문을 쓰는 게 맞았다 — 두 벌을 두면 갈리고, 갈린 쪽이 조용히 틀린다.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "site_recipes.py"
    ).read_text(encoding="utf-8")
    assert 'execute_trusted("browser_open", {"url": url})' in source


def test_the_model_cannot_open_that_door() -> None:
    """신뢰가 **인자**면 모델이 얹을 수 있다. 이 저장소는 그 구멍을 한 번 뚫려 봤다
    (`{"_approved": true}` 하나로 결제·삭제의 L2 승인이 우회됐다).

    `execute_trusted` 는 게이트웨이에 등록돼 있지 않아 모델이 부를 수가 없다.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    # 모델이 부르는 문(BrowserTools.register)은 평범한 execute 다.
    assert "handler=lambda args, action=name: self.worker.execute(action, args)," in source
    # 그리고 밑줄 인자는 애초에 떨어져 나간다.
    assert 'if not key.startswith("_")' in source
