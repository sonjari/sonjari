"""한 가게에서 막혀 「진전 없음」이 되어도, **아직 안 간 가게가 남았으면** 한 번은 거기로 보낸다 (2026-10-15).

10-15 05:50 가격 판(e62004b5): Claude 가 「가게」를 「판매처(가게) 이름」으로 바꿔 맡겼고, 손자리는 다나와 한 곳에서 판매처 이름을
찾느라 22걸음 · 10분을 쓰고 `wrapped_up:no_progress` 로 끝났다 — 11번가 · G마켓은 「거기서 아무것도 안 함」. 이어 맡긴 둘째 판은
세 곳을 다 채웠지만 Claude 쪽 20분 시한을 2분 넘겼다. 운영 기록에서 같은 모양(여러 사이트 중 안 간 곳을 남긴 채 진전 없음)이
66판 중 3판, 전부 가격 비교였다.

지키는 약속(`BrowserAgent._autonomous_extension`):
- 헛돌아 접을 자리에서, 「○○에서 하기」 요구가 둘 이상이고 그중 하나 이상은 했고 **아무것도 안 한 곳**이 남았으면,
  한 구간을 더 주고 이유를 `stuck_moved_on_to_untouched_sites` 로 돌려준다(반복문이 「막힌 칸은 『확인 못 함』으로 두고
  남은 곳으로 가라」를 붙인다).
- 한 판에 한 번 — 이미 옮겨 보냈으면 지금처럼 접는다.
- 안 간 곳이 없거나 사이트 요구가 하나뿐이면 지금처럼 접는다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent, untouched_sites
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.plan import Requirement

FAILED = [{"tool": "browser_find", "ok": False, "error": "not_found"} for _ in range(3)]


def _plan(*rows: tuple[str, bool, str]) -> list[tuple[Requirement, bool, str]]:
    return [(Requirement("site", label, label.split("에서")[0]), met, saw) for label, met, saw in rows]


THREE_SHOPS = _plan(("다나와에서 하기", True, "1건"), ("11번가에서 하기", False, "거기서 아무것도 안 함"),
                    ("G마켓에서 하기", False, "거기서 아무것도 안 함"))


def _agent(tmp_path) -> BrowserAgent:
    from test_agent import FakeBrowser, FakeGateway, FakeTools

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True)
    return BrowserAgent(config, object(), FakeGateway(), FakeBrowser(), FakeTools(), JobStore(tmp_path / "j.db"), EventBus())


def test_untouched_sites_are_named() -> None:
    assert untouched_sites(THREE_SHOPS) == ["11번가에서 하기", "G마켓에서 하기"]
    assert untouched_sites(_plan(("다나와에서 하기", False, "거기서 아무것도 안 함"))) == []


def test_a_stuck_run_with_untouched_shops_gets_one_more_round(tmp_path) -> None:
    extra, why = _agent(tmp_path)._autonomous_extension(steps=FAILED, elapsed=10, plan_results=THREE_SHOPS, plan_told=True)
    assert extra > 0 and why == "stuck_moved_on_to_untouched_sites"


def test_only_once(tmp_path) -> None:
    extra, why = _agent(tmp_path)._autonomous_extension(steps=FAILED, elapsed=10, plan_results=THREE_SHOPS, plan_told=True,
                                                         sites_moved_on=True)
    assert extra == 0 and why == "no_progress"


def test_nothing_untouched_wraps_up_as_before(tmp_path) -> None:
    done = _plan(("다나와에서 하기", True, "1건"), ("11번가에서 하기", True, "1건"), ("G마켓에서 하기", False, "열었으나 못 읽음"))
    extra, why = _agent(tmp_path)._autonomous_extension(steps=FAILED, elapsed=10, plan_results=done, plan_told=True)
    assert extra == 0 and why == "no_progress"
