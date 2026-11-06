"""회사 모션 템플릿 배치 — 사람 확정 규칙이 먼저 · 모델 제안은 사람 확정을 못 덮는다 · 찾기가 템플릿 낱말로 찾는다 (2026-11-04).

현업 애니메이터 11-04 답: hit_active = 기본 공격 · down/recover = 새 「다운」 칸 · entry/idleintro = Lobby_Get · rigor = 피격 · sprint = 이동.
"""
from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.animator import library, template as tp

RULES = {
    "template": [],
    "rules": [
        {"match": r"recover", "목록": "기본 모션", "상태": "다운", "클립명": "Down", "by": "현업 애니메이터"},
        {"match": r"(^|_)down", "목록": "기본 모션", "상태": "다운", "클립명": "Down", "by": "현업 애니메이터"},
        {"match": r"hit_active", "목록": "공격 모션", "상태": "기본 공격", "클립명": "Attack_Basic", "by": "현업 애니메이터"},
        {"match": r"^entry|idleintro", "목록": "아웃 게임", "상태": "이모션1", "클립명": "Lobby_Get", "by": "현업 애니메이터"},
    ],
}


def _entry(root: Path, name: str) -> dict:
    e = library.new_entry(root, name=name, origin="company", character="캐릭A")
    (e["folder"] / "motion.bip").write_bytes(b"x")
    return e


def test_rules_match_the_motion_part_not_the_character_name(tmp_path: Path) -> None:
    assert tp._motion_part("Hero_A_hit_active_1_230622_01_hair02추가") == "hit_active_1"
    assert tp.rule_for("Hero_Downton_idle_240101_01", RULES["rules"]) is None  # 캐릭터 이름의 Down 에 걸리면 안 된다
    assert tp.rule_for("Hero_A_downloop_230622_01", RULES["rules"])["상태"] == "다운"
    assert tp.rule_for("Hero_A_airborne_recover_230622_01", RULES["rules"])["상태"] == "다운"  # 먼저 적힌 규칙
    assert tp.rule_for("Hero_A_idleintro_230623_01", RULES["rules"])["클립명"] == "Lobby_Get"
    assert tp.rule_for("Hero_A_idle_230622_01", RULES["rules"]) is None


def test_confirmed_rules_win_and_proposals_cannot_overwrite_them(tmp_path: Path) -> None:
    root = tmp_path
    active = _entry(root, "Hero_A_hit_active_1_230622_01")
    idle = _entry(root, "Hero_A_astand_possession_230705")
    entries = library.entries(root)
    out = tp.apply_rules(entries, RULES)
    assert out["confirmed"] == 1 and len(out["left_for_model"]) == 1
    # 모델이 사람 확정 칸을 덮으려 해도 그대로
    kept = tp.propose(active["folder"], "공격 모션", "특수 공격", "SpecialAttack", "모델 생각")
    assert kept["상태"] == "기본 공격" and kept["by"] == tp.CONFIRMED
    placed = tp.propose(idle["folder"], "기본 모션", "대기", "Idle", "전투대기")
    assert placed["by"] == tp.PROPOSED and placed["variant"] == "빙의"
    on_disk = json.loads((idle["folder"] / "entry.json").read_text(encoding="utf-8"))
    assert on_disk["template"]["상태"] == "대기"


def test_find_uses_template_words(tmp_path: Path) -> None:
    root = tmp_path
    rec = _entry(root, "Hero_A_airborne_recover_230622_01")
    _entry(root, "Hero_A_idle_230622_01")
    tp.apply_rules(library.entries(root), RULES)
    found = library.find(root, "다운", k=5)
    assert [e["id"] for e in found] == [rec["id"]]


def test_template_file_round_trips(tmp_path: Path) -> None:
    tp.save(tmp_path, RULES)
    assert tp.load(tmp_path)["rules"][0]["match"] == "recover"
    assert tp.load(tmp_path / "nowhere")["rules"] == []


def test_apply_always_matches_com_to_the_scene(tmp_path: Path) -> None:
    """현업 애니메이터 11-04: 모션을 들고 올 때 COM 을 기존 메쉬 자리에 맞춘다 — 수평은 COM, 높이는 발.

    맥스에서 Move All 이 두 배로 옮기는 경우가 있어(11-04 실측 2.06 → 4.12) 옮긴 뒤 재고 다시 맞춘다.
    """
    script = library.apply_script(tmp_path / "motion.bip", label="x", frames=(0, 30))
    assert "sjComMatch" in script and "sjFootZ" in script
    assert "keepPos" in script and script.index("keepPos = at time") < script.index("loadBipFile")
    assert "move com step" in script and "gain" in script  # 재고 다시 맞추기
    assert ".position =" not in script  # 바이페드 COM 에는 .position 이 없다
    assert "comNote" in script  # 어긋남을 사람에게 돌려준다


def test_apply_body_fit_options(tmp_path: Path) -> None:
    """체형 보정: 다리 보폭 배율 · 위팔 벌림 · 키 맞춤. 현업 애니메이터가 고른 판 = 0.5 · 35°(11-04 쿠키 한 동작)."""
    plain = library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30))
    assert "#retargetHeight" in plain and 'local fitNote = "체형 보정 없음"' in plain
    assert "(animationRange.end.frame as integer) 1." not in plain  # 보정이 없으면 sjBodyFit 를 부르지 않는다
    b = library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30), stride=0.5, arm_spread=35)
    assert "sjBodyFit com (animationRange.start.frame as integer) (animationRange.end.frame as integer) 0.500 35.0" in b
    # 범위 밖 값은 자른다 · 키 맞춤 끄기
    wild = library.apply_script(tmp_path / "m.bip", label="x", stride=9, arm_spread=200, match_height=False)
    assert " 2.000 60.0" in wild and "#retargetHeight\n" not in wild
    # 「키 바뀜」 기준은 장면 단위 0.5 가 아니라 바이페드 키의 1% — 키 2.9 짜리 쿠키 장면에서도 맞게
    assert "0.01 * h" in plain and "moved > 0.5" not in plain
