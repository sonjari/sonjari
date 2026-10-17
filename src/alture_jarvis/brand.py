"""제품 이름은 이 파일 한 곳에만 둔다 — 상표 정리(2026-09-15): 자비스(JARVIS) → Ontelic.

- 화면·알림·프롬프트에 보이는 이름은 창 제목·설치 이름은 `NAME`, 한국어 문장 속은 `NAME_KO`.
- 옛 이름은 두 자리에만 남는다. **알아듣기**(사용자가 습관대로 「자비스」라고 부르는 말)와
  **옛 자리 이어 쓰기**(이미 `내 문서\\JARVIS`·`alture-jarvis` 연결이 있는 PC).
- 이 밖의 사람 눈에 보이는 문자열에 옛 이름이 들어오면 `tests/test_brand_name.py` 가 실패한다.
- 패키지 `alture_jarvis`·환경변수 `JARVIS_*`·헤더 `X-JARVIS-TOKEN` 은 사용자에게 안 보이는 내부
  이름이라 그대로 둔다(바꾸면 위성·운영 설정이 한꺼번에 깨진다). 실행 파일 이름은 스토어 포장 때.
"""

from __future__ import annotations

from pathlib import Path

#: ★ 2026-09-29 두 번째 이름 정리: Ontelic → **손자리 / Sonjari**(전략안 §55-9 — 같은 이름의 우즈베키스탄 AI 회사가 먼저 씀).
#:   1단계는 **보이는 이름만** 바꾼다. 이미 깔린 곳이 깨지는 설치 이름(패키지·실행 파일·데이터 폴더·자동 시작·MCP 이름)은
#:   `INSTALL_NAME` 으로 남겨 두고, 공개 직전 2단계에서 옛 자리를 이어 쓰게 해서 옮긴다.
NAME = "Sonjari"
NAME_KO = "손자리"
#: ★ 2단계(2026-09-29, 대표 결정 「지금 바로」): 설치 이름도 새 이름. 옛 자리가 있는 PC 는 그 자리를 **이어 쓴다** —
#:   노트북에 받아 둔 엔진(`~\\Ontelic\\engine`)·기억 복제본·앱 데이터가 새 폴더로 갈라지면 모델을 다시 받고 기억을 잃는다.
#:   사람 눈에 안 보이는 식별자(패키지 `RoboMetaFit.Ontelic`·Tauri identifier·자동 시작 id·업데이트 채널 주소)는
#:   그대로 둔다 — 바꾸면 설치된 판의 자동 업데이트·자동 시작·화면 저장값이 끊긴다.
INSTALL_NAME = "Sonjari"
#: 1단계까지의 설치 이름. 이 이름의 폴더가 이미 있으면 그 자리를 계속 쓴다.
LEGACY_INSTALL_NAME = "Ontelic"

LEGACY_NAMES = ("온텔릭", "Ontelic", "자비스", "JARVIS")
#: 자기를 가리키는 말로 알아듣는 이름 — 새 이름과 옛 이름 모두.
SELF_NAMES = (NAME_KO, NAME, *LEGACY_NAMES)
SELF_NAME_PATTERN = "|".join(SELF_NAMES)

DIR_NAME = INSTALL_NAME
LEGACY_DIR_NAME = "JARVIS"

MCP_SERVER_NAME = "sonjari"
#: 잇기는 옛 이름 항목을 지우고 새 이름으로 다시 쓴다(한 PC 에 둘이 나란히 뜨지 않게).
LEGACY_MCP_SERVER_NAMES = ("alture-jarvis", "ontelic")

#: 스토어 패키지의 실행 별칭(`uap5:AppExecutionAlias`) — packaging/msix/build_app_package.ps1 과 같은 값.
#: 스토어 판은 아직 나간 적이 없어 옛 이름을 이어 쓸 설치가 없다(느슨한 등록 시험판만 옛 이름).
MCP_ALIAS = "sonjari-mcp.exe"
#: 옛 시험판이 클로드·코덱스 설정에 적어 둔 별칭 — 패키지가 둘 다 선언해서, 잇기를 다시 안 해도 끊기지 않는다.
LEGACY_MCP_ALIAS = "ontelic-mcp.exe"


#: 앱 데이터(토큰·DB·설정) 자리 `%LOCALAPPDATA%\\<이름>`. Tauri(lib.rs·package.rs)도 같은 규칙을 쓴다 — 한쪽만 바꾸면
#: 화면이 토큰을 못 찾는다(tests/test_brand_name.py 가 두 언어를 대조한다).
RUNTIME_DIR_NAME = INSTALL_NAME
LEGACY_RUNTIME_DIR_NAME = "AltureJarvis"
#: 이어 쓸 옛 앱 데이터 자리 — **먼저 있는 것**을 쓴다(더 오래된 이름이 앞).
LEGACY_RUNTIME_DIR_NAMES = (LEGACY_RUNTIME_DIR_NAME, LEGACY_INSTALL_NAME)


def runtime_dir(local_app_data: Path) -> Path:
    """새 설치는 `…\\Sonjari`. 이미 `…\\AltureJarvis`·`…\\Ontelic` 를 쓰던 PC 는 그 자리를 계속 쓴다."""
    for name in LEGACY_RUNTIME_DIR_NAMES:
        legacy = Path(local_app_data) / name
        if legacy.is_dir():
            return legacy
    return Path(local_app_data) / RUNTIME_DIR_NAME


def user_root(home: Path) -> Path:
    """사용자 폴더 속 제품 자리 — 새 설치는 `~\\Sonjari`, 옛 `~\\Ontelic` 가 있으면 그 자리.

    엔진·업데이트·기억 복제본이 **같은 규칙 하나**로 자리를 정해야 한다 — 따로 정하면 한 PC 에서 둘로 갈린다.
    """
    legacy = Path(home) / LEGACY_INSTALL_NAME
    return legacy if legacy.is_dir() else Path(home) / INSTALL_NAME


def backup_dir(home: Path) -> Path:
    """기억 복제본 — 사용자 폴더 `Sonjari\\backup`(회사 이름 폴더를 사용자 홈에 만들지 않는다).

    옛 자리(`RoboMetaFit\\Ontelic\\backup` · `RoboMetaFit\\JARVIS\\backup`)에 세대가 이미 있으면 그 자리를 이어 쓴다.
    """
    home = Path(home)
    for legacy in (home / "RoboMetaFit" / LEGACY_INSTALL_NAME / "backup", home / "RoboMetaFit" / LEGACY_DIR_NAME / "backup"):
        if legacy.is_dir():
            return legacy
    return user_root(home) / "backup"


def engine_dir(home: Path) -> Path:
    """로컬 AI 엔진(Ollama) 자리 — 사용자 폴더 `Sonjari\\engine`.

    ★ 2026-09-18 노트북 실측으로 옮겼다. 예전 자리는 앱 데이터 안(`…\\Ontelic\\data\\ollama`)이었는데,
      스토어판에서는 거기 **새로 만든 파일이 앱 전용 칸**으로 간다. Ollama 는 우리가 받아 온 **패키지 밖
      실행 파일**이라 그 칸이 안 보인다 — 파일 43개가 멀쩡히 있는데도
      `llama-server binary not found` 로 모델이 하나도 안 올라갔다(서버는 켜지고 목록은 답해서 더 안 보였다).
      기억 복제본을 사용자 폴더에 둔 것과 같은 이유다(`backup_dir`). 앱을 지워도 남아 다시 안 받는다.
    """
    return user_root(home) / "engine"


def update_dir(home: Path) -> Path:
    """스토어판 「지금 업데이트」 도우미가 상태를 적는 자리 — 사용자 폴더 `Sonjari\\update`.

    도우미는 **앱이 꺼진 뒤에도** 돌아야 해서 패키지 밖에서 뜬다(WMI). 패키지 밖 프로그램은 앱 전용 칸을
    못 본다(2026-09-18 노트북 Ollama 사고) — 그래서 여기다.
    """
    return user_root(home) / "update"


def downloads_dir(home: Path) -> Path:
    """브라우저로 받은 파일 — 사용자가 탐색기에서 바로 찾는 `다운로드\\Sonjari`(옛 `다운로드\\Ontelic` 이 있으면 그 자리).

    예전 기본값(앱 데이터 안 outputs\\downloads)은 스토어판에서 앱 전용 칸으로 격리돼 사용자가 찾을 수 없었다.
    """
    downloads = Path(home) / "Downloads"
    legacy = downloads / LEGACY_INSTALL_NAME
    return legacy if legacy.is_dir() else downloads / INSTALL_NAME


def product_dir(parent: Path) -> Path:
    """`parent\\Sonjari`. 옛 `parent\\JARVIS`·`parent\\Ontelic` 가 이미 있으면 그 자리를 계속 쓴다 — 결과물·백업이 갈리지 않게."""
    for name in (LEGACY_DIR_NAME, LEGACY_INSTALL_NAME):  # 옛 `JARVIS`·`Ontelic` 가 있으면 그 자리
        legacy = Path(parent) / name
        if legacy.is_dir():
            return legacy
    return Path(parent) / DIR_NAME


def documents_product_dir(documents: Path) -> Path:
    r"""결과물 폴더 `문서\Sonjari`. **새 폴더가 이미 있으면 그쪽** — 옛 폴더는 새 폴더가 없을 때만 이어 쓴다.

    ★ 2026-10-17: 이 PC 는 10-16 에 `문서\JARVIS` 를 `문서\Sonjari` 로 옮겼는데, 옮기기 전부터 떠 있던 프로그램(클로드 앱이 띄운
      손자리 MCP 서버)이 옛 경로로 쓰면서 `JARVIS` 폴더가 다시 생겼고, 그 뒤 다시 켜진 백엔드는 `product_dir` 규칙대로 그 옛 폴더를
      골라 결과물이 다시 그리로 갔다(영어 첫 일 측정의 엑셀). 결과물 폴더만 「새 것이 있으면 새 것」으로 본다. 브라우저 프로필 ·
      코드 사본 같은 다른 자리는 `product_dir` 그대로다 — 거기서 옛 자리를 버리면 로그인 · 작업이 끊긴다.
    """
    fresh = Path(documents) / DIR_NAME
    return fresh if fresh.is_dir() else product_dir(documents)


__all__ = [
    "DIR_NAME", "documents_product_dir", "INSTALL_NAME", "LEGACY_DIR_NAME", "LEGACY_INSTALL_NAME", "LEGACY_MCP_ALIAS", "LEGACY_MCP_SERVER_NAMES",
    "LEGACY_NAMES", "LEGACY_RUNTIME_DIR_NAME", "LEGACY_RUNTIME_DIR_NAMES", "MCP_ALIAS",
    "MCP_SERVER_NAME", "NAME", "NAME_KO", "RUNTIME_DIR_NAME", "SELF_NAMES", "SELF_NAME_PATTERN", "backup_dir",
    "engine_dir",
    "downloads_dir", "product_dir", "runtime_dir", "update_dir", "user_root",
]
