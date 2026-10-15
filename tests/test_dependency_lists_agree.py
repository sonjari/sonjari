"""`requirements.txt` 와 `pyproject.toml` 이 **갈라지지 못하게** 한다.

## 왜 (2026-09-12)

나래님 위성에서 「첨부한 문서를 못 읽는다」를 조사하다 나왔다. 두 목록이 서로
다른 일을 하고 있었다:

    처음 설치 (install_satellite.ps1)  →  requirements.txt  +  pip install -e .
    갱신     (apply_update.ps1)        →                        pip install -e .

`pip install -e .` 는 **pyproject 만** 읽는다. 그래서 requirements.txt 에만 있던
`python-hwpx`(한글 읽기)·`tzdata` 는 **갱신으로는 영영 안 깔렸다.** 처음 설치한
기계에만 있고, 나중에 붙은 기능은 위성에 안 닿는다.

이 저장소가 같은 병으로 여러 번 데였다 — 「두 벌은 반드시 갈린다」. 그래서
지우는 대신 **어긋나면 시험이 깨지게** 한다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _name(spec: str) -> str:
    """`python-hwpx`, `uvicorn[standard]>=0.35.0; platform_system == 'Windows'` → 이름만."""
    head = spec.split(";", 1)[0].strip()
    head = re.split(r"[<>=!~\[]", head, 1)[0]
    return head.strip().lower().replace("_", "-")


def _requirements() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {
        _name(line)
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    }


def _pyproject() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {_name(spec) for spec in data["project"]["dependencies"]}


def test_everything_requirements_installs_is_also_a_real_dependency() -> None:
    """갱신은 pyproject 만 본다 — requirements 에만 있으면 위성에 안 닿는다."""
    missing = _requirements() - _pyproject()
    assert not missing, (
        "requirements.txt 에만 있는 것: "
        + ", ".join(sorted(missing))
        + " — 갱신(`pip install -e .`)으로는 안 깔린다. pyproject 에도 넣어라."
    )


def test_the_document_readers_libraries_survive_an_update() -> None:
    """첨부를 읽는 라이브러리는 **특히** 갱신으로 닿아야 한다.

    한글·PDF·엑셀·파워포인트는 docx/xlsx/pptx 만 zip 폴백이 있고
    pdf·hwpx 는 없다 — 없으면 첨부가 통째로 거절된다.
    """
    declared = _pyproject()
    for package in ("pypdf", "python-hwpx", "charset-normalizer"):
        assert package in declared, f"{package} 가 pyproject 에 없다"
