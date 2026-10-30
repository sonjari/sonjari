"""파이썬 파일을 고친 결과가 **문법을 깨면 저장하지 않는다** (2026-10-29).

사고: 손자리 코드 판 1093e4a1(needs 「No」 고치기). 24번째 걸음의 `local_apply_edit` 가 「성공」했는데, 모델이 새로 쓴 줄에
`lstrip("-*•>|\\")`처럼 닫는 따옴표 앞에 역슬래시가 끼어 파일이 문법상 깨졌다. 도구는 그대로 저장했고, 이어서 모델은
자기가 깨뜨린 줄(역슬래시가 겹겹이 보이는 줄)을 글자 맞추기로 5번 · 줄 번호로 1번 못 고쳐 13분을 헛돌다 멈췄다(대표가 「계속」 2번).

고친 것: `.py` 파일에서 **고치기 전엔 컴파일되고 고친 뒤엔 안 되면** 쓰지 않고 `syntax_broken` 으로 거절한다 — 몇 번째 줄이
왜 깨졌는지와 그 줄을 그대로 돌려준다. 원래부터 깨진 파일은 막지 않는다(그걸 고치는 편집이어야 하니까). 글자 모드 · 줄 범위 모드 둘 다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

SOURCE = (
    "def clean(after):\n"
    '    body = after.strip().lstrip("-*•>|").strip()\n'
    "    return body\n"
)


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "ws"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def _call(tools: LocalComputerTools, path: Path, **args) -> dict:
    return tools.apply_edit({"path": str(path), "__job_id": "code-job", **args})


def test_text_edit_that_breaks_syntax_is_refused_and_file_untouched(tmp_path):
    tools, work = _tools(tmp_path)
    target = work / "outbound.py"
    target.write_text(SOURCE, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        _call(tools, target, old='lstrip("-*•>|")', new='lstrip("-*•>|\\")')
    message = str(caught.value)
    assert message.startswith("syntax_broken")
    assert "2" in message, "깨진 줄 번호를 알려 준다"
    assert target.read_text(encoding="utf-8") == SOURCE, "거절이면 파일은 그대로"


def test_line_range_edit_that_breaks_syntax_is_refused(tmp_path):
    tools, work = _tools(tmp_path)
    target = work / "outbound.py"
    target.write_text(SOURCE, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        _call(tools, target, line_start=2, line_end=2, first_line='    body = after.strip().lstrip("-*•>|").strip()',
              new='    body = after.strip().lstrip("-*•>|\\").strip()')
    assert str(caught.value).startswith("syntax_broken")
    assert target.read_text(encoding="utf-8") == SOURCE


def test_good_edit_still_applies(tmp_path):
    tools, work = _tools(tmp_path)
    target = work / "outbound.py"
    target.write_text(SOURCE, encoding="utf-8")
    _call(tools, target, old="    return body\n", new="    return body or None\n")
    assert "return body or None" in target.read_text(encoding="utf-8")


def test_fixing_an_already_broken_file_is_allowed(tmp_path):
    tools, work = _tools(tmp_path)
    target = work / "outbound.py"
    broken = SOURCE.replace('lstrip("-*•>|")', 'lstrip("-*•>|\\")')
    target.write_text(broken, encoding="utf-8")
    # 아직 다 못 고친 편집(여전히 깨짐)도 막지 않는다 — 원래 깨진 파일이었다
    _call(tools, target, old="    return body\n", new="    return body  # still broken above\n")
    # 그리고 고치는 편집은 당연히 된다
    # first_line 은 느슨하게 맞는다(낱말만 비교) — 역슬래시를 그대로 옮겨 적지 못해도 된다
    _call(tools, target, line_start=2, line_end=2, first_line='    body = after.strip().lstrip("-*•>|").strip()',
          new='    body = after.strip().lstrip("-*•>|").strip()')
    assert 'lstrip("-*•>|")' in target.read_text(encoding="utf-8")
    compile(target.read_text(encoding="utf-8"), "outbound.py", "exec")


def test_non_python_files_are_not_checked(tmp_path):
    tools, work = _tools(tmp_path)
    target = work / "notes.txt"
    target.write_text('say "hi"\n', encoding="utf-8")
    _call(tools, target, old='"hi"', new='"hi\\"')
    assert target.read_text(encoding="utf-8") == 'say "hi\\"\n'
