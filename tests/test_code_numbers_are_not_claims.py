"""파일을 만든 **코드 속 숫자**는 「근거 없는 숫자」가 아니다 (2026-10-02 분업 실험, 클로드 → 손자리 판 7f437150).

손자리가 엑셀을 계산 상자(sandbox_run)의 파이썬으로 만들었는데, 코드 문자열을 통째로 「쓴 내용」으로 세어
열 너비 `[6, 22, 42, 12, 26, 90]` 이 「출처에서 확인되지 않은 숫자(26, 42, 90)」로 찍혔다. 클로드는 그 경고를 사용자에게
「급여·마감일 숫자가 정확한지 다시 확인하라」로 옮겼다. 표에 들어간 값(따옴표 안 글자)은 그대로 검사해야 한다.
"""

from __future__ import annotations

from alture_jarvis.delegation import _strings

CODE = '''from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(["순위", "회사명", "급여"])
ws.append([3, "한빛화학(주)", "연봉 2,762만원 (주 40시간)"])
for col, width in zip("ABCDEF", [6, 22, 42, 12, 26, 90]):
    ws.column_dimensions[col].width = width  # 열 너비 90
wb.save("여수_회계_채용공고.xlsx")
'''


def test_only_the_quoted_values_of_the_code_are_written_text() -> None:
    out: list[str] = []
    _strings({"code": CODE, "timeout_sec": 60}, out)
    joined = " ".join(out)
    assert "연봉 2,762만원 (주 40시간)" in out, "표에 들어간 값은 그대로 검사한다"
    assert "42" not in joined and "90" not in joined, "열 너비·주석 숫자는 쓴 내용이 아니다"


def test_broken_code_still_gives_its_quoted_text() -> None:
    out: list[str] = []
    _strings({"code": 'ws.append(["연봉 2,762만원"]\nwidths = [26, 42'}, out)
    assert out == ["연봉 2,762만원"]


def test_ordinary_write_arguments_are_unchanged() -> None:
    out: list[str] = []
    _strings({"path": "a.xlsx", "rows": [["한빛화학", "연봉 2,762만원"]], "width": 90}, out)
    assert out == ["a.xlsx", "한빛화학", "연봉 2,762만원"]
