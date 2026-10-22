"""시험은 사람 PC 의 진짜 레시피를 읽지 않는다 — 경로가 어떤 길로 계산됐든 (2026-10-22).

전체 회귀(12갈래)에서 test_site_recipes 가 진짜 `문서\\Sonjari\\recipes\\yes24_learned.json` 을 읽어 한 번 떨어졌다. 새는 길을 못 짚어서,
레시피를 읽는 함수 자체에서 막고(conftest `guarded_load`) 막힌 일은 회귀 끝에 경고로 남긴다. 이 시험은 그 막음이 일하는지 본다.
"""

from __future__ import annotations

from pathlib import Path

import conftest
from alture_jarvis import site_recipes
from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import SiteRecipeTools


class _Worker:
    def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        return {}


def test_pointing_straight_at_the_real_documents_still_reads_nothing(tmp_path: Path, request) -> None:
    builtin = tmp_path / "recipes"
    builtin.mkdir()
    real_docs = conftest._REAL_DOCUMENTS / "Sonjari"
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                          site_recipe_dir=builtin, documents_dir=real_docs)
    try:
        assert site_recipes.load_recipes(real_docs / "recipes") == {}, "읽는 함수 자체가 진짜 문서 폴더를 막는다"
        tools = SiteRecipeTools(config, _Worker())
        assert "yes24_learned" not in tools.recipes and list(tools.recipes) == []
    finally:
        # 이 시험이 일부러 남긴 「막힘」 기록은 지운다 — 회귀 끝 경고는 진짜 새는 일만 보여야 한다.
        log = conftest._REAL_DOCUMENTS_READS
        if log.exists():
            kept = [line for line in log.read_text(encoding="utf-8").splitlines() if request.node.nodeid not in line]
            log.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8") if kept else log.unlink()


def test_temp_folders_are_still_read_normally(tmp_path: Path) -> None:
    folder = tmp_path / "recipes"
    folder.mkdir()
    assert not conftest._under_real_documents(folder)
    assert site_recipes.load_recipes(folder) == {}
