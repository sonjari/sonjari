"""사람인 레시피가 **첫 화면 변형까지** 덮는가 (2026-09-16 이어받기 3판).

포장본으로 돌린 이어받기 판이 사람인에서 `site_search_box_not_found` 로 멈췄다. 화면 제목은
「사람인 커리어 매칭 에이전트 - 나만의 AI 취업 비서」였다 — 우리가 아는 첫 화면이 아니었다.

처음엔 「그 변형에 맞는 레시피를 새로 쓰자」로 읽었다. **틀렸다.** 레시피는 이미 있었고 그 주소도
덮고 있었다(`hosts` 로 거는 구조라 경로가 달라도 걸린다). 진짜 원인은 **포장본에 `recipes/` 폴더가
통째로 없던 것**이다 — 검토된 절차가 거기 없으니 `_auto_search_recipe` 가 빈손으로 돌아갔고,
모델이 손으로 검색칸을 더듬다 끝났다(playwright 가 빠졌던 것과 같은 모양).

그래서 이 시험은 두 가지를 잡는다:
1. 레시피가 그 화면들을 계속 덮는가 (누가 `hosts` 를 좁히면 여기서 걸린다)
2. 검색 절차가 `query` 하나로 도는 L0 인가 — 그래야 `browser_site_search` 가 **자동으로** 그 길로 샌다
   (사고 R: 안내문은 안 먹는다. 결정론으로 박을 수 있으면 코드로)
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.models import RiskLevel
from alture_jarvis.site_recipes import load_recipes

RECIPES = Path(__file__).resolve().parents[1] / "recipes"

# 라이브에서 실제로 열렸던 주소들. 두 번째가 이어받기 3판이 멈춘 그 화면이다.
LANDINGS = (
    "https://www.saramin.co.kr/zf_user/",
    "https://www.saramin.co.kr/zf_user/ai-agent/career",
    "https://saramin.co.kr/",
)


def test_reviewed_saramin_recipe_covers_the_landing_variants() -> None:
    recipe = load_recipes(RECIPES)["saramin"]
    for url in LANDINGS:
        assert recipe.allows(url), f"{url} 가 레시피 밖으로 샜다 — 그 화면에서 손으로 더듬게 된다"


def test_the_search_procedure_is_the_kind_that_auto_replaces_site_search() -> None:
    """`_auto_search_recipe` 가 대신 실행해 주는 조건: L0 이고 필요한 값이 query 하나."""
    from alture_jarvis.site_recipes import SiteRecipeTools

    recipe = load_recipes(RECIPES)["saramin"]
    assert recipe.risk_of("search_jobs") == RiskLevel.L0
    needed = SiteRecipeTools._params_of(recipe, "search_jobs")
    assert needed == {"query"}, f"검색에 {needed} 가 필요하면 자동 연결이 안 된다"
