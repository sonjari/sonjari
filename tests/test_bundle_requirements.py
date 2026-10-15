"""포장본 검사 목록이 **실제 import 와 맞는가** (2026-09-16).

포장에서 `playwright` 가 빠진 채로 나가 웹 조사를 통째로 못 한 판이 있었다. 검사 목록이 코드보다 낡으면
같은 일이 또 난다 — 새 의존성이 생기면 이 시험이 그 자리에서 잡는다.

**같은 날 자료에서도 났다**: `recipes/`·`skills/` 가 통째로 안 들어갔는데 앱은 멀쩡히 떴다(검토된 절차 대신
모델이 더듬는다). 그래서 검사기가 보는 자리가 `config.py` 가 보는 자리와 **같은지**도 여기서 붙잡는다 —
둘이 갈리면 검사가 초록불을 켜고 제품은 빈손이 된다.
"""

from __future__ import annotations

import ast
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "msix"))
from check_bundle import OPTIONAL, REQUIRED, REQUIRED_DATA, data_root  # noqa: E402
import check_bundle

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"


def _imported_tops() -> set[str]:
    tops: set[str] = set()
    for file in SRC.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
    return {t for t in tops if t not in set(sys.stdlib_module_names) | {"alture_jarvis"}}


def test_every_third_party_import_is_classified() -> None:
    known = {name.split(".")[0] for name in REQUIRED} | set(OPTIONAL)
    # pywin32 는 한 배포판이 여러 이름으로 들어온다 — 대표 하나(win32com)만 목록에 둔다.
    known |= {"pythoncom", "win32clipboard", "charset_normalizer"}
    unknown = sorted(_imported_tops() - known)
    assert not unknown, (
        "포장본 검사 목록에 없는 의존성이 있다 — 빠진 채로 나가도 아무도 모른다:\n  "
        + "\n  ".join(unknown)
        + "\n\npackaging/msix/check_bundle.py 의 REQUIRED(없으면 제품이 못 돎) 나 OPTIONAL 에 넣어라."
    )


def test_the_browser_is_required_not_optional() -> None:
    """★ 이것이 빠져서 포장본이 웹 조사를 못 했다. 다시 선택으로 내려가면 안 된다."""
    assert "playwright.sync_api" in REQUIRED and "playwright" not in OPTIONAL


@pytest.mark.parametrize('absent', ['cv2', 'winrt.windows.media.control'])
def test_missing_camera_and_media_components_stop_a_package(monkeypatch, tmp_path, absent):
    """노트북에서 빠졌던 실제 하위 모듈을 지우면 빌드 검사가 실패해야 한다."""
    root = tmp_path/'data'
    for folder, (pattern, least, _) in REQUIRED_DATA.items():
        (root/folder).mkdir(parents=True)
        for i in range(least):
            target = root/folder/(f'{i}.json' if folder == 'recipes' else f'{i}/SKILL.md')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('자료', encoding='utf-8')
    monkeypatch.setattr(check_bundle, 'data_root', lambda: root)
    monkeypatch.setattr(check_bundle, '_prepare_windows_cache', lambda: None, raising=False)
    def load(name):
        if name == absent:
            raise ImportError('노트북 포장본에서 빠진 모듈')
        return object()
    monkeypatch.setattr(check_bundle.importlib, 'import_module', load)
    assert check_bundle.main() == 1, f'{absent} 없이 빌드 검사가 통과함'


def test_package_check_redirects_cache_before_importing_window_automation(monkeypatch, tmp_path):
    prepared = []
    monkeypatch.setattr(check_bundle, '_prepare_windows_cache', lambda: prepared.append(True), raising=False)
    monkeypatch.setattr(check_bundle, 'data_root', lambda: tmp_path)
    monkeypatch.setattr(check_bundle, 'REQUIRED_DATA', {})
    def load(name):
        if name == 'pywinauto':
            assert prepared, '읽기 전용 포장 경로의 생성 캐시를 아직 돌리지 않았다'
        return object()
    monkeypatch.setattr(check_bundle.importlib, 'import_module', load)
    assert check_bundle.main() == 0


def test_data_folders_the_checker_looks_at_are_the_ones_config_uses() -> None:
    """검사기의 자리 규칙 == `config.py` 의 자리 규칙. 갈리면 검사가 헛것을 본다."""
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig()
    assert config.site_recipe_dir.parent == data_root()
    assert config.skills_dir.parent == data_root()
    assert set(REQUIRED_DATA) == {config.site_recipe_dir.name, config.skills_dir.name}


def test_this_repo_actually_has_the_data_the_package_needs() -> None:
    """저장소에 없으면 포장본에도 없다 — 빌드가 죽기 전에 여기서 먼저 말한다."""
    root = data_root()
    for folder, (pattern, least, _why) in REQUIRED_DATA.items():
        found = [p for p in (root / folder).glob(pattern) if p.is_file()]
        assert len(found) >= least, f"{root / folder} 에 {pattern} 가 {len(found)}개 (최소 {least})"


def test_what_the_settings_screen_calls_available_is_actually_shipped() -> None:
    """**켜짐이라 말하는 기능은 포장본에 들어 있어야 한다** (2026-09-18).

    아버님 노트북에서 설정은 「말로 시키기 켜짐」「소리 내어 답하기 켜짐」이라고 적혀 있었는데
    받아쓰기 모듈이 없었고 음성 서버도 없었다. 사람은 자기가 뭘 잘못한 줄 안다.

    이제 두 자리를 붙잡아 둔다 — 설정이 「이 판에 있는가」를 보는 모듈과 포장이 반드시 싣는 목록.
    새 기능을 설정에 노출하면서 포장에 안 넣으면 여기서 걸린다.
    """
    from alture_jarvis.settings import _CAPABILITY_MODULES

    shipped = set(REQUIRED) | {name.split(".")[0] for name in REQUIRED}
    for key, (modules, _reason) in _CAPABILITY_MODULES.items():
        for module in modules:
            assert module in shipped, (
                f"설정 화면이 {key} 를 켤 수 있다고 말하는데 포장본은 {module} 를 안 싣는다 — "
                "check_bundle.REQUIRED 에 넣거나 그 설정을 내려라"
            )
