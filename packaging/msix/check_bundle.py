"""포장한 앱 안에 **정말 다 들어갔는가** — 동봉 파이썬으로 직접 불러 본다 (2026-09-16).

    <포장본>\\backend\\python\\python.exe packaging\\msix\\check_bundle.py

왜 있나: 빌드가 확인하던 것은 「우리 코드가 import 되는가」 하나뿐이었다. 그래서 `playwright`(107MB)가 제외 목록에
들어간 채로 포장본이 나갔고, 스토어로 받은 앱은 첫 웹 과제에서 「No module named 'playwright'」로 멈췄다 —
**웹 조사를 통째로 못 하는 판이 나갈 뻔했다.** 이제 실제로 쓰는 것을 전부 불러 보고, 하나라도 없으면 빌드가 죽는다.

**같은 날 두 번째로** 같은 일이 자료에서 났다 — `recipes/`·`skills/` 가 통째로 안 들어갔다. 그래서 이제
모듈뿐 아니라 **자료 폴더가 실제로 차 있는지**도 본다(`REQUIRED_DATA`).

목록은 `src/alture_jarvis` 의 import 를 훑어 만든 것이고, 새 의존성이 생기면 여기 추가한다
(`tests/test_bundle_requirements.py` 가 목록과 실제 import 를 대조한다).
"""

from __future__ import annotations

import importlib
import subprocess
import importlib.util
import os
import sys
from pathlib import Path

# 빌드 콘솔이 cp949 라 한글·em dash 에서 죽었다(2026-09-16) — 검사기가 인코딩 때문에 실패하면
# 「무엇이 없는지」가 아니라 엉뚱한 오류만 남는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 없으면 제품이 제 일을 못 한다 — 빌드를 실패시킨다.
REQUIRED = {
    "fastapi": "백엔드 HTTP",
    "uvicorn": "백엔드 실행",
    "pydantic": "요청 계약",
    "httpx": "모델·API 호출",
    "truststore": "HTTPS 검사를 윈도우에 맡김 — 없으면 초기화한 PC 에서 Ollama 받기가 인증서로 죽는다(2026-09-24)",
    "websockets": "브라우저 무대 — 화면 밖 크롬에 CDP 로 따로 붙어 화면 스트림·사람 입력을 넣는다(2026-09-24)",
    "mcp": "Claude·Codex 연결",
    "starlette": "원격 입구(remote_gateway) — 노트북의 클로드 코드가 테일스케일로 붙는 HTTP 문(2026-10-21). fastapi 가 이미 데려온다",
    "playwright.sync_api": "실제 크롬 조종 — 이게 빠져서 포장본이 웹 조사를 못 했다(2026-09-16)",
    "docx": "워드 문서 만들기",
    "openpyxl": "엑셀 만들기",
    "pptx": "PPT 만들기",
    "fontTools": "장표 글꼴 — PPTX 에 쓴 글자만 담아 심는다(pptx_fonts · 2026-10-26)",
    "lxml": "PPT 만들기(python-pptx 가 데려온다) · PPTX 글꼴 목록 쓰기",
    "brotli": "장표 글꼴 — woff2 를 풀어 PPTX 에 심는다(2026-10-26). 없으면 PPTX 가 앱 글꼴 없이 나간다",
    "hwpx": "한글 문서",
    "pypdf": "PDF 읽기",
    "pypdfium2": "PDF 그림",
    "PIL": "이미지",
    "pywinauto": "창 조작",
    "comtypes.client": "UIA 생성 캐시 — 쓰기 가능한 앱 데이터에 둔다",
    "win32com": "윈도우 연동",
    "numpy": "표·이미지 계산",
    # ★ 2026-09-18. 포장본에 음성이 통째로 없었다 — 노트북 진단에 `faster_whisper_not_installed` 와
    #   TTS `[WinError 10061]`. 그런데 설정 화면은 「말로 시키기 켜짐」이라고 적고 있었다.
    #   **우리가 켜짐이라 말하는 기능은 포장본에 반드시 들어간다**(settings._CAPABILITY_MODULES 와 짝).
    #   압축 기준 약 49MB 다(실측: av 4 + av.libs 63 + ctranslate2 60 + tokenizers 8 + faster_whisper 1).
    "faster_whisper": "음성 받아쓰기",
    "ctranslate2": "받아쓰기 엔진",
    "av": "받아쓰기가 소리를 푸는 데 쓴다 — 없으면 faster_whisper 가 import 부터 죽는다",
    "sounddevice": "마이크 녹음(누르고 말하기)",
    "supertonic": "음성 출력 — 포장본에서는 우리가 직접 서버를 켠다(alture_jarvis.tts_server)",
    "keyboard": "누르고 말하기 단축키 — 설정에 그 칸이 있으니 판에도 있어야 한다",
    "cv2": "카메라 영상 — 노트북 포장본에서 빠졌다",
    "winrt.windows.foundation": "윈도우 미디어 연동의 비동기 기반",
    "winrt.windows.foundation.collections": "윈도우 미디어 연동의 컬렉션 기반",
    "winrt.windows.media.control": "말할 때 음악 멈추기 — 실제 하위 모듈까지 검사한다",
    # ★ 2026-10-18 0.4.22.0 굽기 전: 디스코드 다리가 본체 안으로 들어와 설정 화면에 「디스코드로 일 시키기」가 생겼는데,
    #   굽는 파이썬(E: 의 .venv)에 discord.py 가 없었고 여기서는 「선택」이라 굽기가 멈추지 않았다 — 화면엔 있는데 판엔 없는
    #   9-18 음성과 같은 모양. 화면에 있는 기능은 필수다.
    "discord": "디스코드로 일 시키기(설정 화면에 있다)",
    "win32cred": "디스코드 봇 토큰을 윈도우 자격 증명 관리자에 저장",
}

#: 없어도 제품은 돈다(그 기능만 꺼진다). 빌드는 알려만 준다.
OPTIONAL = {
    "ultralytics": "사람 인식",
    "bleak": "블루투스",
    "psutil": "프로세스 목록(없으면 PowerShell 로 대신 본다)",
    # 2026-10-26 「막히면 내 API 키로 클로드에게 묻기」(api_escalation.py). 없으면 그 설정만 켤 수 없다(「부품 없음」).
    #   포장본에 넣는 것은 부품 판 올림이라 대표 허락 뒤 — 그 전까지는 빠진 채로 나가는 것이 맞다.
    "anthropic": "막히면 내 API 키로 클로드에게 묻기(없으면 그 설정만 꺼짐)",
}


#: 코드가 아니라 **자료**로 들어가는 것. 없으면 제품이 조용히 못난 판이 된다.
#
# ★ 2026-09-16: `recipes/` 와 `skills/` 가 포장본에 통째로 없었다 — playwright 와 같은 모양이다.
#   증상은 더 나쁘다: 없다고 죽지 않고, 검토된 절차 대신 **모델이 더듬는다.** 그날 포장본으로 돌린
#   이어받기 판이 사람인 검색칸을 못 찾아 손으로 채우다 끝났는데, 그 사이트 레시피는 우리가 이미
#   갖고 있었다. 「있는데 안 썼다」가 아니라 **거기 없었다.**
#
# 여기서 보는 자리는 `config.py` 가 보는 자리와 **같은 규칙**이어야 한다
# (`<alture_jarvis>/../../`). 둘이 갈리면 이 검사가 초록불을 켜고 제품은 빈손이 된다 —
# `tests/test_bundle_requirements.py` 가 그 둘을 붙잡아 둔다.
REQUIRED_DATA = {
    # 폴더가 **있는지**가 아니라 알맹이를 센다. skills/ 는 README 와 vendor/ 껍데기만 있어도
    # 폴더로는 차 보인다 — 실제로 붙는 것은 SKILL.md 다.
    "recipes": ("*.json", 1, "사람이 검토한 사이트 절차 — 없으면 모델이 셀렉터를 더듬는다"),
    "skills": ("**/SKILL.md", 20, "밖에서 가져온 지식 — 없으면 일에 안 붙는다"),
}


def data_root() -> Path:
    """`config.py` 의 `Path(__file__).resolve().parents[2]` 와 같은 자리."""
    import alture_jarvis.config as config_module

    return Path(config_module.__file__).resolve().parents[2]


def main() -> int:
    missing: list[str] = []
    try:
        _prepare_windows_cache()
    except Exception as exc:  # noqa: BLE001
        missing.append(f"  COM 캐시 준비 — {type(exc).__name__}: {exc}")
    for name, why in REQUIRED.items():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — 이유까지 보여 준다
            missing.append(f"  {name} ({why}) — {type(exc).__name__}: {exc}")
    # ★ 2026-09-26 초기화한 노트북 코드 모드 E2E: 포장본에 **ruff·mypy 가 없었다**(`No module named ruff`). 온텔릭이 허용하는
    #   도구(`_PYTHON_MODULES`)를 이 관문이 안 봐서 빈손으로 나갔다. 목록을 새로 적지 않고 제품이 쓰는 목록을 그대로 본다.
    try:
        from alture_jarvis.local_computer import _PYTHON_MODULES

        for tool in sorted(_PYTHON_MODULES):
            if importlib.util.find_spec(tool) is None:
                missing.append(f"  {tool} (코드 모드가 `python -m {tool}` 로 부르는 도구) — 설치 안 됨")
                continue
            # ★ 불러올 수 있다 ≠ 돈다: ruff 는 파이썬 패키지가 실행 파일(ruff.exe)을 감싼 것이라, 패키지는 있는데 실행 파일이
            #   포장에서 빠져 `RuffNotFound` 였다(2026-09-26 노트북). 표준 모듈이 아닌 도구는 실제로 한 번 돌려 본다.
            if tool in {"unittest", "compileall", "py_compile"}:
                continue
            ran = subprocess.run([sys.executable, "-m", tool, "--version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=180)
            if ran.returncode != 0:
                tail = (ran.stderr or ran.stdout).strip().splitlines()[-1:] or ["?"]
                missing.append(f"  {tool} — `python -m {tool} --version` 실패: {tail[0][:160]}")
        print(f"code tools {len(_PYTHON_MODULES)} checked (ran --version)")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"  (코드 도구 목록을 못 읽었다) — {type(exc).__name__}: {exc}")
    off = [f"{name}({why})" for name, why in OPTIONAL.items()
           if not _importable(name)]
    print(f"required {len(REQUIRED) - len(missing)}/{len(REQUIRED)} ok")
    if off:
        print("optional off: " + ", ".join(off))

    try:
        root = data_root()
    except Exception as exc:  # noqa: BLE001
        missing.append(f"  (자료 자리를 못 구했다) — {type(exc).__name__}: {exc}")
        root = None
    if root is not None:
        counts = []
        for folder, (pattern, least, why) in REQUIRED_DATA.items():
            found = [p for p in (root / folder).glob(pattern) if p.is_file()]
            counts.append(f"{folder} {len(found)}")
            if len(found) < least:
                missing.append(
                    f"  {folder}/ ({why}) — {root / folder} 에 {pattern} 가 {len(found)}개다(최소 {least})"
                )
        print(f"data at {root}: " + ", ".join(counts))

    # 장표 결의 앱 글꼴(2026-10-26) — 꾸러미 안 `alture_jarvis/slide_themes/fonts/`. 빠지면 죽지 않고 윈도우 기본 글꼴로 조용히
    #   돌아가 「새 글꼴」이 사라진다(위 자료와 같은 모양). 목록(fonts.json)의 파일 · 크기 · 옆의 OFL.txt 를 하나하나 본다.
    try:
        from alture_jarvis import slides_style

        fams = slides_style.bundled_fonts()
        faces = [(fam, face) for fam in fams for face in fam.get("faces") or []]
        if not faces:
            missing.append(f"  장표 글꼴 — {slides_style.FONT_DIR / 'fonts.json'} 이 없거나 비었다")
        for fam, face in faces:
            path = slides_style.FONT_DIR / str(face["file"])
            if not path.is_file() or path.stat().st_size != int(face["bytes"]):
                missing.append(f"  장표 글꼴 {fam['family']} — {path} 가 없거나 크기가 다르다")
        for fam in fams:
            if not (slides_style.FONT_DIR / str(fam["license"])).is_file():
                missing.append(f"  장표 글꼴 {fam['family']} — 라이선스 {fam['license']} 가 없다(OFL 은 글꼴 옆에 같이 둔다)")
        print(f"slide fonts {len(faces)} files in {len(fams)} families")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"  (장표 글꼴 목록을 못 읽었다) — {type(exc).__name__}: {exc}")

    if missing:
        print("MISSING:\n" + "\n".join(missing))
        return 1
    return 0


def _prepare_windows_cache() -> None:
    if os.name == 'nt':
        from alture_jarvis.config import JarvisConfig
        from alture_jarvis.windows_automation import WindowsAutomationTools

        WindowsAutomationTools(JarvisConfig())._prepare_com_cache()


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
