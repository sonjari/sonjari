"""SEED 의 모든 주소는 SITE_NAMES 에도 영어 이름이 있어야 한다 (2026-10-09).

`site_atlas.SEED` 는 처음부터 아는 사이트(한글 이름 → 주소)이고, `english.SITE_NAMES` 는
영어 요청에서 같은 곳을 알아보는 영어 이름 → 주소 표다. SEED 에 있는데 SITE_NAMES 에
영어 이름이 없는 주소가 있으면 영어로 요청하면 그 사이트를 못 알아본다
(「on YES24」·「on Reddit」이 그랬다).

그래서 이 불변을 시험으로 지킨다 — SEED 에 새 사이트를 넣을 때 영어 이름을 빠뜨리면
여기서 바로 걸린다.
"""
from __future__ import annotations

from alture_jarvis.english import SITE_NAMES
from alture_jarvis.site_atlas import SEED


def test_every_seed_address_has_an_english_name() -> None:
    known_hosts = set(SITE_NAMES.values())
    missing = sorted({host for host in SEED.values() if host not in known_hosts})
    assert not missing, (
        "SEED 에 있는데 SITE_NAMES 에 영어 이름이 없는 주소: " + ", ".join(missing)
    )
