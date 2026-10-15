"""화면이 부르는 주소는 **백엔드에 있어야 한다** (2026-09-17 첫 실행 마감 점검).

## 왜

첫 실행을 고치며 화면과 백엔드를 같이 바꿨다(`/v1/setup/ollama/gpu-only`, `apply_ctx`, 설정 › 모델 …). 주소 하나가
오타이거나 백엔드에 안 붙으면 화면은 **조용히** 실패한다 — 버튼이 눌리고 아무 일도 없다. 노트북에서 「안 넘어간다」를
보는 자리가 바로 그것이다. 화면 코드의 `/v1/…` 문자열을 전부 뽑아 FastAPI 앱의 실제 경로와 대조한다.

`${…}` 로 끼운 부분은 경로 변수 하나로 본다. 쿼리 문자열은 뗀다.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "src"
# 화면 문자열에서 /v1/ 로 시작하는 경로를 뽑는다(따옴표·백틱 안).
PATH_IN_UI = re.compile(r"""["'`](/v1/[^"'`\s]*)""")


def _ui_paths() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in UI.rglob("*.ts*"):
        if ".test." in path.name or "fixture" in path.name.lower() or "fixtures" in path.parts:
            continue
        for raw in PATH_IN_UI.findall(path.read_text(encoding="utf-8", errors="replace")):
            if "*" in raw:
                continue  # 주석 속 설명(`/v1/setup/*`) — 부르는 주소가 아니다
            clean = raw.split("?", 1)[0]
            clean = re.sub(r"\$\{[^}]*\}", "{var}", clean)
            if "${" in clean:
                clean = clean.split("${", 1)[0]  # `${fresh ? "?fresh=1" : ""}` 처럼 괄호가 섞인 끝부분은 뗀다
            # 끝의 `/` 는 남긴다 — 「뒤에 변수를 붙여 조립하는 앞부분」이라는 표시다(아래 접두 비교는 이것만 허락).
            if clean.rstrip("/").endswith("/v1"):
                continue
            found.setdefault(clean, []).append(path.relative_to(UI).as_posix())
    return found


def _backend_patterns(tmp_path: Path) -> list[re.Pattern[str]]:
    app = create_app(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                                  camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False),
                     start_services=False)
    patterns = []
    for route in app.routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            regex = re.sub(r"\{[^}]+\}", "[^/]+", re.escape(route.path).replace(r"\{", "{").replace(r"\}", "}"))
            patterns.append(re.compile(f"^{regex}$"))
    return patterns


def _missing(ui: dict[str, list[str]], patterns: list[re.Pattern[str]]) -> dict[str, list[str]]:
    missing = {}
    for path, files in sorted(ui.items()):
        probe = path.replace("{var}", "x")
        if any(p.match(probe) for p in patterns):
            continue
        # `"/v1/jobs/" + id` 처럼 **`/` 로 끝나는 앞부분**만 접두로 대조한다. ★ 처음엔 모든 주소를 접두로 봐서
        #   오타 `/models/pul` 이 `/models/pull` 앞부분이라 통과했다(역검증 시험이 잡았다).
        if path.endswith("/") and any(p.match(probe + "x") or p.match(probe + "x/x") or
                                      p.pattern.startswith("^" + re.escape(path)) for p in patterns):
            continue
        missing[path] = sorted(set(files))
    return missing


def test_every_address_the_screen_calls_exists_in_the_backend(tmp_path: Path) -> None:
    ui = _ui_paths()
    assert len(ui) > 40, f"화면 주소를 거의 못 뽑았다({len(ui)}) — 눈금이 비었다"
    missing = _missing(ui, _backend_patterns(tmp_path))
    assert not missing, "화면이 부르는데 백엔드에 없는 주소:\n" + "\n".join(f"  {k}  ← {v}" for k, v in missing.items())


def test_the_first_run_addresses_added_today_are_wired() -> None:
    """오늘 새로 붙인 주소가 화면에 실제로 있는가(한쪽만 고치면 위 시험은 통과해도 버튼은 죽어 있다)."""
    ui = _ui_paths()
    for path in ("/v1/setup/ollama/gpu-only", "/v1/setup/models/pull", "/v1/setup/models/apply", "/v1/setup/connect/apply"):
        assert path in ui, f"{path} 를 화면이 안 부른다"


def test_the_gauge_catches_an_address_the_backend_does_not_have(tmp_path: Path) -> None:
    """눈금 역검증 — 없는 주소를 넣으면 잡아야 한다. 안 잡으면 위 시험의 통과는 아무 뜻이 없다."""
    patterns = _backend_patterns(tmp_path)
    fake = {"/v1/setup/ollama/gpu-onlyy": ["x.ts"], "/v1/setup/models/pul": ["x.ts"], "/v1/jobs/{var}": ["ok.ts"]}
    assert set(_missing(fake, patterns)) == {"/v1/setup/ollama/gpu-onlyy", "/v1/setup/models/pul"}
