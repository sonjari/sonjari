"""만든 웹 페이지를 **스스로 볼 수 있어야 한다** (2026-09-20 실전에서 드러남).

## 어떻게 찾았나

프론트 과제 두 번째 판은 파일을 **만들었다**(정찰 규칙을 고친 덕이다). 그런데 그 뒤:

     2 O local_write_file            index.html  17.6KB
     3 X browser_open                browser_url_not_allowed
     4 X local_run_project_command   python_module_not_allowed
     5 X local_run_project_command   project_command_not_allowed
     6 X local_run_project_command   command_argument_blocked
     7 X local_run_project_command   project_command_not_allowed
     8 X local_run_project_command   project_command_not_allowed
    → 잡 결과: failed · coding_verification_missing

**만든 페이지를 볼 방법이 하나도 없었다.** 다섯 번 다른 길을 시도하다 전부 막혔고, 검증을
못 했다는 이유로 잡 전체가 실패로 찍혔다 — 산출물은 멀쩡히 있는데.

## 왜 `file://` 를 그냥 열면 안 되나

`browser_open` 이 `file://` 를 받으면 `file:///C:/Users/…/.ssh/id_ed25519` 도 열린다.
브라우저가 폴더 권한 체계를 **우회하는 문**이 되는 것이다. 그래서 **작업 폴더만** 로컬
주소로 띄우고, 브라우저에는 평소대로 `http://127.0.0.1:...` 를 준다.

★ 이러면 사장님이 말씀하신 것도 같이 된다 — Code 모드 오른쪽 **컴퓨터 칸이 브라우저 화면을
  보여 주므로**, 만든 페이지가 거기 그대로 렌더된다. 모델도 보고 사람도 본다.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "site"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def test_a_page_it_made_becomes_a_local_address(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "index.html").write_text("<h1>오늘의 현황</h1>", encoding="utf-8")

    served = tools.serve_page({"__job_id": "code-job", "path": "index.html"})

    assert served["url"].startswith("http://127.0.0.1:")
    with urllib.request.urlopen(served["url"], timeout=10) as resp:
        assert "오늘의 현황" in resp.read().decode("utf-8")
    tools.stop_serving()


def test_it_only_serves_the_work_folder(tmp_path: Path) -> None:
    """★ 이 문이 넓으면 브라우저가 폴더 권한을 통째로 우회한다."""
    tools, work = _tools(tmp_path)
    (work / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    secret = tmp_path / "비밀.txt"
    secret.write_text("보이면 안 된다", encoding="utf-8")

    with pytest.raises(PermissionError):
        tools.serve_page({"__job_id": "code-job", "path": str(secret)})

    served = tools.serve_page({"__job_id": "code-job", "path": "index.html"})
    root = served["url"].rsplit("/", 1)[0]
    with pytest.raises(Exception):
        # 위로 거슬러 올라가는 주소는 열리면 안 된다.
        urllib.request.urlopen(f"{root}/../%EB%B9%84%EB%B0%80.txt", timeout=5)
    tools.stop_serving()


def test_only_loopback_can_reach_it(tmp_path: Path) -> None:
    """다른 기기에 열어 주지 않는다 — 이 PC 안에서만 보는 창이다."""
    import inspect

    source = inspect.getsource(LocalComputerTools.serve_page)
    # 주석은 세지 않는다 — 왜 그랬는지 적어 둔 기록에 그 주소가 나온다(§12).
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "127.0.0.1" in code and "0.0.0.0" not in code


def test_the_tool_is_registered_so_the_model_can_call_it() -> None:
    """★ 도구를 만들어도 **등록 자리**를 빠뜨리면 모델은 못 부른다 — 이 저장소의 단골 함정."""
    import inspect

    from alture_jarvis.code_runtime import CODE_CORE_TOOL_NAMES

    register = inspect.getsource(LocalComputerTools.register)
    assert '"local_preview_page": self.serve_page' in register
    assert "local_preview_page" in CODE_CORE_TOOL_NAMES
