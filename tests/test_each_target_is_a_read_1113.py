"""동그라미 번호로 늘어놓은 대상 + 「각 곳마다 읽어」 = 대상 수만큼 읽을 몫 (2026-11-13 맥 판 14c76267).

그 판은 개수 낱말이 없어 읽을 몫이 0 → 깃허브 한 번 열자 「파일 차례」로 넘어가 나머지 다섯 곳 열기가 not_this_stage 로 막혔고,
「…서버 목록 화면으로 간다.」 예고로 끝났다. 역검증(운영 요청 3,380): 처음 판은 4건 헛걸림(번호가 조건 · 칸 · 목차) → 장소 낱말 ·
앞쪽 번호로 좁혀 바뀐 것 3건(전부 맞음).
"""
from __future__ import annotations

from alture_jarvis import plan

TASK_1113 = (
    "MCP 서버 「sonjari」(깃허브 github.com/sonjari/sonjari · 파이썬 · 로컬 stdio · 윈도우/맥)를 올릴 수 있는 공개 목록·디렉터리를 "
    "조사해 엑셀 표로 정리해 줘. 대상: ① 공식 MCP 레지스트리(registry.modelcontextprotocol.io) ② Smithery ③ mcp.so ④ PulseMCP "
    "⑤ 깃허브의 다른 awesome MCP 목록들 ⑥ 앤트로픽 공식 경로. 각 곳마다 공식 문서·제출 페이지를 직접 읽고: 등록 방법, 요구 조건, "
    "비용, 근거 주소를 칸으로."
)


def _labels(text: str) -> set[str]:
    return {r.label for r in plan.extract(text)}


def test_listed_targets_with_each_place_read_become_a_read_count() -> None:
    assert "6개 이상 직접 열어 읽기" in _labels(TASK_1113)


def test_numbered_fields_conditions_and_sections_are_not_places_to_read() -> None:
    fields = ("긱뉴스의 Show GN 규칙과 해커뉴스의 Show HN 규칙을 각 사이트의 공식 안내 페이지에서 직접 읽어 정리해 줘. "
              "사이트마다 ① 올릴 수 있는 조건 ② 금지되는 것 ③ 제목 규칙 ④ 링크 규칙을 칸으로.")
    sections = ("inline AI 를 조사해 워드 문서로 정리해 줘. 공식 사이트의 제품 페이지를 직접 열어 읽고, 문서에 ① 개요 ② 기능 ③ 요금 "
                "④ 보안 ⑤ 다운로드 ⑥ 후기 ⑦ 우리와 비교를 넣어 줘.")
    conditions = "AI 도구를 찾아 줘. 찾는 조건은 셋이다: ① 한국에서 만들었다 ② 브라우저를 조작한다 ③ PC 에 설치한다. 각각 확인해서 표로."
    for text in (fields, sections, conditions):
        assert not any(label.endswith("직접 열어 읽기") and label.startswith(("4", "7", "3")) for label in _labels(text)), text


def test_the_count_only_counts_numbers_listed_before_each_place() -> None:
    assert plan._each_target_read_count("대상: ① 가 ② 나 ③ 다. 각 곳마다 직접 읽고 정리해.") == 3
    assert plan._each_target_read_count("각 사이트마다 직접 읽고 ① 조건 ② 금지 를 적어.") == 0
    assert plan._each_target_read_count("① 가 ② 나. 표로 만들어.") == 0
