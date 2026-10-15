"""상표 정리(2026-09-15) — 사람 눈에 보이는 문자열에 옛 이름(자비스·JARVIS)이 다시 들어오지 않게 막는다.

안내문으로는 안 막힌다(사고 R). 새 화면·새 오류문을 만들 때 습관대로 「자비스가 …」라고 쓰면 여기서 실패한다.
옛 이름은 `brand.py` 한 곳에서만 쓴다 — 사용자가 옛 이름으로 불러도 알아듣기, 옛 폴더·연결 이어 쓰기.

내부 이름(패키지 `alture_jarvis`·환경변수 `JARVIS_*`·헤더 `X-JARVIS-TOKEN`·클래스 `JarvisConfig`)은 사용자에게
안 보여서 그대로 둔다 — 규칙이 식별자 글자에 붙은 `JARVIS` 는 세지 않는다.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

from alture_jarvis import brand
from alture_jarvis.mcp_connect import LEGACY_SERVER_NAMES, SERVER_NAME, ConnectService, toml_without_server

REPO = Path(__file__).resolve().parents[1]
# ★ 2026-09-29: 온텔릭·Ontelic 도 옛 이름이 됐다(→ 손자리/Sonjari). 식별자·경로 속 `RoboMetaFit.Ontelic`·`Ontelic.exe`·
#   `\Ontelic\` 는 설치 이름이라 안 센다(2단계에서 옮긴다).
OLD = re.compile(r"자비스|온텔릭|(?<![A-Za-z0-9_\-])JARVIS(?![A-Za-z0-9_\-])"
                 r"|(?<![A-Za-z0-9_\-.\\/])Ontelic(?![A-Za-z0-9_\-\\/])(?!\.[A-Za-z])")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\{/\*)")
#: 설치 이름이 사는 줄 — 데이터 폴더·자동 시작·패키지 식별자·실행 파일 이름(2단계에서 옮긴다).
INSTALL_LINE = re.compile(r"RUNTIME_DIR_NAME|STARTUP_TASK_ID|\"identifier\"|mainBinaryName|productName")
#: 옛 이름을 **알아듣는** 정규식(`온텔릭|ontelic|…`) — 사용자가 옛 이름으로 불러도 자기로 알아들어야 한다.
RECOGNIZER = re.compile(r"(?:자비스|온텔릭|Ontelic|JARVIS)\||\|(?:자비스|온텔릭|Ontelic|JARVIS)")


def _python_visible_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    floating: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        for stmt in body if isinstance(body, list) else []:  # lambda 의 body 는 식 하나
            if isinstance(stmt, ast.Expr):
                floating.update(id(n) for n in ast.walk(stmt.value))  # 독스트링·떠 있는 문자열 = 주석
    for node in ast.walk(tree):
        if id(node) in floating:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_backend_strings_use_the_new_name():
    hits = []
    for path in sorted((REPO / "src" / "alture_jarvis").rglob("*.py")):
        if path.name == "brand.py":
            continue
        for line, value in _python_visible_literals(path):
            if OLD.search(value) and not RECOGNIZER.search(value):
                hits.append(f"{path.relative_to(REPO).as_posix()}:{line}: {value.strip()[:80]!r}")
    assert hits == [], "옛 이름은 brand.py 의 상수로만:\n" + "\n".join(hits)


def _code_lines(path: Path):
    in_block = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if in_block:
            in_block = "*/" not in line
            continue
        if line.lstrip().startswith("/*") and "*/" not in line:
            in_block = True
            continue
        if COMMENT_LINE.match(line):
            continue
        yield n, line.partition(" // ")[0]


def test_ui_and_window_strings_use_the_new_name():
    files = [p for p in sorted((REPO / "ui" / "src").rglob("*"))
             if p.suffix in {".ts", ".tsx", ".json"} and ".test." not in p.name]
    files += sorted((REPO / "ui" / "src-tauri" / "src").rglob("*.rs"))
    files += [REPO / "ui" / "index.html", *sorted((REPO / "ui" / "src-tauri").glob("tauri*.conf.json"))]
    hits = [f"{p.relative_to(REPO).as_posix()}:{n}: {line.strip()[:80]}"
            for p in files for n, line in _code_lines(p) if OLD.search(line) and not INSTALL_LINE.search(line)]
    assert hits == [], "\n".join(hits)


def test_window_and_install_name_is_the_brand():
    conf = json.loads((REPO / "ui" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["productName"] == brand.INSTALL_NAME  # 설치 이름 — 2단계에서 옮긴다
    assert f"<title>{brand.NAME}</title>" in (REPO / "ui" / "index.html").read_text(encoding="utf-8")


def test_prompts_name_the_assistant_ontelic():
    from alture_jarvis.agent import AGENT_SYSTEM_PROMPT
    from alture_jarvis.runtime import MEMORY_SUMMARY_PROMPT, SYSTEM_PROMPT

    for prompt in (SYSTEM_PROMPT, MEMORY_SUMMARY_PROMPT, AGENT_SYSTEM_PROMPT):
        assert brand.NAME_KO in prompt
        assert not OLD.search(prompt)


def test_old_name_is_still_understood_as_self_reference():
    """사용자는 한동안 「자비스 상태 봐줘」라고 부른다 — 새 이름과 옛 이름 둘 다 자기 진단으로 가야 한다."""
    from alture_jarvis import runtime, task_contract

    for said in ("자비스 상태 점검해줘", "온텔릭 상태 점검해줘", "JARVIS 진단"):
        assert runtime._SELF_REFERENCE.search(said), said
        assert task_contract._SELF_REFERENCE.search(said), said
    assert "자비스 코드" in runtime.LOCAL_SOURCE_PHRASES and "온텔릭 코드" in runtime.LOCAL_SOURCE_PHRASES


def test_product_dir_keeps_an_existing_legacy_folder(tmp_path: Path):
    assert brand.product_dir(tmp_path) == tmp_path / "Sonjari"
    (tmp_path / "Ontelic").mkdir()
    assert brand.product_dir(tmp_path) == tmp_path / "Ontelic"  # 1단계까지의 결과물 폴더를 이어 쓴다
    (tmp_path / "JARVIS").mkdir()
    assert brand.product_dir(tmp_path) == tmp_path / "JARVIS"  # 옛 결과물·백업이 갈리지 않게


def test_connect_replaces_the_legacy_entry_instead_of_adding_a_second(tmp_path: Path):
    class Cfg:
        host, port, data_dir = "127.0.0.1", 8091, tmp_path / "data"

    cursor = tmp_path / "home" / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(json.dumps({"mcpServers": {"alture-jarvis": {"command": "old"}, "ontelic": {"command": "old2"},
                                             "other": {"command": "x"}}}),
                      encoding="utf-8")
    service = ConnectService(Cfg(), home=tmp_path / "home", which=lambda _: None, processes=lambda: [],
                             python="C:/py/python.exe")
    assert service.apply("cursor")["ok"]
    servers = json.loads(cursor.read_text(encoding="utf-8"))["mcpServers"]
    assert SERVER_NAME == "sonjari" and set(servers) == {"sonjari", "other"}

    toml = '[mcp_servers.alture-jarvis]\ncommand = "old"\n\n[mcp_servers.other]\ncommand = "x"\n'
    assert "alture-jarvis" not in toml_without_server(toml) and "other" in toml_without_server(toml)
    assert LEGACY_SERVER_NAMES == ("alture-jarvis", "ontelic")


def _rebrand():
    spec = importlib.util.spec_from_file_location("rebrand", REPO / "scripts" / "rebrand_visible_names.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rebrand


def test_rebrand_fixes_korean_particles():
    """「자비스」는 받침이 없고 「온텔릭」은 있다 — 찾아 바꾸기가 만드는 「온텔릭가」를 막는다."""
    rebrand = _rebrand()
    cases = {
        "자비스가 되돌립니다": "온텔릭이 되돌립니다",
        "자비스는 실수할 수": "온텔릭은 실수할 수",
        "자비스를 돌릴": "온텔릭을 돌릴",
        "자비스와 연결 중": "온텔릭과 연결 중",
        "돕는 자비스다.": "돕는 온텔릭이다.",
        "자비스에게 물어보기": "온텔릭에게 물어보기",
        "자비스의 컴퓨터": "온텔릭의 컴퓨터",
        "JARVIS로 돌아가세요": "온텔릭으로 돌아가세요",
        "ALTURE JARVIS 가 이어서": "온텔릭이 이어서",
        "JARVIS 작업 완료": "온텔릭 작업 완료",
        "ALTURE JARVIS": "Ontelic",
        "JARVIS · 승인이 필요합니다": "Ontelic · 승인이 필요합니다",
        "JARVIS_CONTROL_TOKEN": "JARVIS_CONTROL_TOKEN",
        "X-JARVIS-TOKEN": "X-JARVIS-TOKEN",
    }
    for old, new in cases.items():
        assert rebrand(old) == new, (old, rebrand(old))


def test_store_package_names_agree_across_python_rust_and_the_manifest():
    """스토어 이름은 세 언어에 흩어져 있다 — 한 곳만 바꾸면 별칭·자동 시작이 조용히 안 맞는다(사고 Q 모양)."""
    build = (REPO / "packaging" / "msix" / "build_app_package.ps1").read_text(encoding="utf-8")
    manifest = (REPO / "packaging" / "msix" / "AppxManifest.template.xml").read_text(encoding="utf-8")
    package_rs = (REPO / "ui" / "src-tauri" / "src" / "package.rs").read_text(encoding="utf-8")
    assert f'$Alias = "{brand.MCP_ALIAS}"' in build
    task = re.search(r'STARTUP_TASK_ID: &str = "([^"]+)"', package_rs).group(1)
    # 자동 시작 id 는 사람에게 안 보이고, 바꾸면 켜 둔 자동 시작이 꺼진다 — 옛 이름 그대로 둔다(이름 2단계).
    assert f'TaskId="{task}"' in manifest and task.startswith(brand.LEGACY_INSTALL_NAME)
    assert f'$LegacyAlias = "{brand.LEGACY_MCP_ALIAS}"' in build and "{{LEGACY_ALIAS}}" in manifest
    for conf in ("tauri.msix.conf.json", "tauri.store.conf.json"):
        data = json.loads((REPO / "ui" / "src-tauri" / conf).read_text(encoding="utf-8"))
        assert data["mainBinaryName"] == brand.INSTALL_NAME and "jarvis" not in data["identifier"]
    assert f'$ExeName = "{brand.INSTALL_NAME}.exe"' in build and "{{EXE}}" in manifest
