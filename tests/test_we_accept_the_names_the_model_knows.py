"""모델이 **이미 아는 이름**으로 불러도 받아 준다 (2026-09-21 AURORA 3판).

## 무슨 일

`local_apply_edit` 가 `old_required` 로 두 번 튕겼다. 거절문을 「`old` 에 넣어라」로
친절하게 고친 **뒤에도** 같은 자리에서 또 튕겼다. 무엇을 보냈는지 보니:

    {"new_string": "    id: 3, dest: '로바니에미', ..."}

**클로드 코드의 인자 이름**(`old_string` / `new_string`)이다. 모델은 그 이름을 이미
알고 있고, 우리 스키마만 `old` / `new` 를 쓴다.

## 왜 안내문으로는 안 됐나

안내문은 「우리 이름은 이것이다」라고 말한다. 그런데 모델은 **자기가 아는 이름이
맞다고 믿는다** — 실제로 세상에서 그게 더 흔하다. 이 저장소가 여러 번 확인한 것:
**결정론으로 박을 수 있으면 코드로 옮긴다**(사고 R).

어젯밤 같은 자리를 이미 한 번 겪었다 — 도구 설명을 명령 표로 바꿨더니 모델이
`command` 를 문자열로 보냈고, 막는 대신 **문자열을 받아 주도록** 고쳤다.

## 규칙

흔한 다른 이름은 **받아 준다.** 지어내는 게 아니라 같은 것을 다르게 부르는 것뿐이다.
우리 이름이 같이 오면 **우리 것이 이긴다** — 둘 다 왔을 때 조용히 고르면 안 된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


@pytest.fixture()
def tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    config.local_file_allowed_roots = str(tmp_path)
    return LocalComputerTools(config)


def _file(tmp_path: Path, body: str = "안녕 옛 제목\n둘째 줄\n") -> Path:
    path = tmp_path / "page.txt"
    path.write_text(body, encoding="utf-8")
    return path


def test_claude_code_names_are_accepted(tmp_path: Path, tools: LocalComputerTools) -> None:
    """★ 실전에서 두 번 튕긴 자리 — 모델은 `old_string`/`new_string` 을 보낸다."""
    path = _file(tmp_path)
    tools.apply_edit({"path": str(path), "old_string": "옛 제목", "new_string": "새 제목"})
    assert "새 제목" in path.read_text(encoding="utf-8")


def test_our_own_names_still_work(tmp_path: Path, tools: LocalComputerTools) -> None:
    path = _file(tmp_path)
    tools.apply_edit({"path": str(path), "old": "옛 제목", "new": "새 제목"})
    assert "새 제목" in path.read_text(encoding="utf-8")


def test_our_name_wins_when_both_come(tmp_path: Path, tools: LocalComputerTools) -> None:
    """둘 다 오면 조용히 고르지 않는다 — 우리 이름이 계약이다."""
    path = _file(tmp_path)
    tools.apply_edit({
        "path": str(path),
        "old": "옛 제목", "new": "우리 것",
        "old_string": "둘째 줄", "new_string": "딴 것",
    })
    body = path.read_text(encoding="utf-8")
    assert "우리 것" in body and "딴 것" not in body


def test_a_truly_missing_old_still_refuses_with_the_way_out(tmp_path: Path, tools: LocalComputerTools) -> None:
    """받아 주는 이름을 늘렸다고 **빈 호출까지** 통과시키면 안 된다."""
    path = _file(tmp_path)
    with pytest.raises(ValueError) as caught:
        tools.apply_edit({"path": str(path), "new_string": "새 것"})
    assert "local_write_file" in str(caught.value), "갈 곳을 안 댔다"


def test_write_file_accepts_the_other_name_too(tmp_path: Path, tools: LocalComputerTools) -> None:
    """같은 이유로 `content` 를 `file_text` 로 부르는 모델도 있다."""
    path = tmp_path / "new.txt"
    tools.write_file({"path": str(path), "file_text": "몸통"})
    assert path.read_text(encoding="utf-8") == "몸통"
