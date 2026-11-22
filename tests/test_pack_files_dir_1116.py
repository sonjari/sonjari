"""팩 파일 자리(2026-11-16 · 대표 「C: 가 작다 · D 로」).

지키는 것:
1. 「팩 파일 자리」가 있으면 새로 받는 것은 그 자리로 간다(받기 · 남은 자리 재기 · 조각 파일까지).
2. 자리를 바꿔도 **옛 자리(데이터 폴더)에 다 받아 둔 것은 그대로 쓴다** — 다시 받지 않는다(3D 약 10GB).
3. 3D · 영상 도구도 같은 규칙으로 찾는다.
4. 설정 칸: 절대 경로 · 있는 드라이브 · 시스템 폴더 거절 · 없으면 만든다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis.pack_models import READY_FILE, ModelFetcher

MODEL = {"id": "w", "kind": "weights", "dir": "w8", "platform": "", "size": 10, "source": {}}


def _fetcher(tmp_path: Path, root: Path | None) -> ModelFetcher:
    packs = SimpleNamespace(packs={})
    return ModelFetcher(packs, tmp_path / "data", root=root, free_bytes=lambda _p: 10**12)


def test_new_downloads_go_to_the_pack_files_dir(tmp_path: Path) -> None:
    fetcher = _fetcher(tmp_path, tmp_path / "D")
    assert fetcher.target_dir("genvideo", MODEL) == tmp_path / "D" / "models" / "genvideo" / "w8"
    part = fetcher._download_part("genvideo", {**MODEL, "source": {"asset": "x"}})
    assert tmp_path / "D" in part.parents, "받는 조각도 새 자리에"


def test_already_received_in_the_old_place_is_kept(tmp_path: Path) -> None:
    old = tmp_path / "data" / "models" / "gen3d" / "w8"
    old.mkdir(parents=True)
    (old / READY_FILE).write_text("{}", encoding="utf-8")
    fetcher = _fetcher(tmp_path, tmp_path / "D")
    assert fetcher.target_dir("gen3d", MODEL) == old, "옛 자리에 다 받은 것을 두고 새로 받으려 했다"
    # 옛 자리에 덜 받은 것(.ready 없음)은 새 자리로 받는다
    half = tmp_path / "data" / "models" / "genvideo" / "w8"
    half.mkdir(parents=True)
    assert fetcher.target_dir("genvideo", MODEL) == tmp_path / "D" / "models" / "genvideo" / "w8"


def test_no_setting_means_the_data_dir(tmp_path: Path) -> None:
    fetcher = _fetcher(tmp_path, None)
    assert fetcher.root == tmp_path / "data"
    assert fetcher.target_dir("gen3d", MODEL) == tmp_path / "data" / "models" / "gen3d" / "w8"


def test_gen3d_and_genvideo_dirs_follow_the_same_rule(tmp_path: Path) -> None:
    from alture_jarvis.gen3d_tools import gen3d_dirs
    from alture_jarvis.genvideo_tools import genvideo_dirs

    data, root = tmp_path / "data", tmp_path / "D"
    cfg = SimpleNamespace(data_dir=data, pack_files_dir=str(root), gen3d_bin_dir="", gen3d_models_dir="",
                          genvideo_bin_dir="", genvideo_models_dir="", genvideo_ltx_dir="")
    # 옛 자리에만 3D 모델이 있으면 옛 자리
    (data / "models" / "gen3d" / "trellis2-q8").mkdir(parents=True)
    _bin, models = gen3d_dirs(cfg, "win32")
    assert models == data / "models" / "gen3d" / "trellis2-q8"
    # 새 자리에도 있으면 새 자리
    (root / "models" / "gen3d" / "trellis2-q8").mkdir(parents=True)
    _bin, models = gen3d_dirs(cfg, "win32")
    assert models == root / "models" / "gen3d" / "trellis2-q8"
    bins, model_dirs, ltx = genvideo_dirs(cfg)
    assert bins[0] == root / "tools" / "genvideo" / "sdcpp" and data / "tools" / "genvideo" / "sdcpp" in bins
    assert model_dirs == [root / "models" / "genvideo", data / "models" / "genvideo"]
    assert ltx == root / "models" / "genvideo" / "ltx25"


def test_setting_checks_the_folder(tmp_path: Path) -> None:
    from alture_jarvis.settings import SettingsError, validate

    made = tmp_path / "packs here"
    assert validate("pack_files_dir", str(made)) == str(made) and made.is_dir(), "없으면 만든다"
    assert validate("pack_files_dir", "") == ""
    with pytest.raises(SettingsError, match="not_absolute"):
        validate("pack_files_dir", "relative/dir")
    with pytest.raises(SettingsError, match="system_folder"):
        validate("pack_files_dir", "C:\\Windows\\packs")
    with pytest.raises(SettingsError, match="system_folder"):
        validate("pack_files_dir", "C:\\Program Files\\x")


def test_gen3d_points_at_genvideo_next() -> None:
    import json

    repo = Path(__file__).resolve().parents[1]
    nxt = json.loads((repo / "packs" / "gen3d" / "pack.json").read_text(encoding="utf-8"))["next"]
    assert "genvideo" in [row["pack"] for row in nxt], "3D → 영상 생성 「다음 팩」이 없으면 이어 쓰기 권하기가 안 나온다(11-16 잇기 시험)"


def test_genvideo_missing_files_say_where_to_press() -> None:
    src = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "genvideo" / "runner.py").read_text(encoding="utf-8")
    assert "팩을 켜면 받는다" not in src, "켜기만으로는 안 받는다 — 11-16 잇기 시험에서 클로드를 헷갈리게 했다"
    assert "「받기」를 누르면" in src
