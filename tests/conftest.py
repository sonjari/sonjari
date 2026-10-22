"""검사 하네스 설정.

## TestClient 는 자기를 「testclient」라고 소개한다

`starlette.testclient.TestClient` 는 기본으로 클라이언트 주소를 문자열
`"testclient"` 로 준다. IP 가 아니다.

2026-08-24 에 제어 API 에 문지기(`peer_guard`)를 달았더니 검사 33개가 깨졌다.
**문지기가 옳았다** — 못 읽는 주소를 거절하는 것이 그 자리의 규칙이고, 거기서
관대해지면 그건 곧 전면 개방이다.

그래서 고칠 곳은 운영 코드가 아니라 여기다. `"testclient"` 를 허용 목록에
넣는 것은 **운영 코드에 뒷문을 내는 것**이라, 그렇게 하지 않았다. 대신 검사가
진짜 루프백 주소에서 온 것처럼 말하게 한다 — 실제로도 그런 셈이다.

★ 이 파일이 사라지면 검사 33개가 403 으로 깨진다. 그때 문지기를 의심하지 말고
  여기를 먼저 보라.
"""

from __future__ import annotations

import os

import pytest
import starlette.testclient

# ── 검사는 **돌고 있는 손자리**를 가리키는 값을 물려받지 않는다 (2026-10-09) ────────
#
# 손자리가 이 저장소의 사본에서 `pytest` 를 돌리면(우리 숙제를 손자리에게 맡긴 판), 운영 프로세스의 `JARVIS_RUNTIME_ROOT`
# 가 그대로 따라와 검사가 만든 런타임이 운영 DB 에 붙었다 — 진행 중인 진짜 판이 실패로 찍혔다.
# 운영 쪽에서 넘기지 않게 고쳤지만(`project_env.without_our_settings`), 그 고침이 안 실린 옛 판이나 사람이 손으로 값을 올려 둔
# 터미널에서도 같은 일이 난다. 그래서 여기서 한 번 더 지운다. 검사가 필요한 값은 검사가 스스로 넣는다(`monkeypatch.setenv`).
# 남기는 것은 「이 검사를 켠다」고 사람이 일부러 올리는 스위치뿐이다.
_SWITCHES_A_PERSON_SETS = frozenset({"JARVIS_UNITY_LIVE_PROJECT", "JARVIS_UI_VERIFY"})
for _name in [key for key in os.environ if key.upper().startswith("JARVIS_") and key.upper() not in _SWITCHES_A_PERSON_SETS]:
    del os.environ[_name]

# ── 검사는 **사용자의 진짜 앱 폴더**에 쓰지 않는다 (2026-10-10) ───────────────────────
#
# 위에서 `JARVIS_*` 를 지우면 설정을 기본값으로 만든 검사(`JarvisConfig()`)는 기본 뿌리로 간다 — `%LOCALAPPDATA%\Sonjari`.
# 그건 사용자의 진짜 앱 데이터 자리다. 손자리가 이 저장소의 사본에서 검사를 돌리기 시작한 10-09 03:52 부터 그 자리에
# 백업 파일 수백 개 · 색인 · DB 가 쌓였다(운영 폴더를 건드리던 것을 막자 갈 곳 없어진 검사가 기본 자리로 갔다).
# 10-10 에 스토어 판을 굽다가 드러났다: 포장한 앱이 그 폴더가 이미 있는 것을 보고 제 전용 자리 대신 그것을 써서
# 관문이 막았다(`token_in_private_cache false`). 일반 사용자 PC 에는 없는 폴더라 제품의 고장은 아니었지만, 우리가
# 사용자의 자리에 쓰레기를 쓰고 있었던 것은 맞다. 「임시 폴더 밖의 DB 는 거절」(아래)은 DB 하나만 봤다.
#
# 그래서 기본 뿌리가 나오는 자리(`LOCALAPPDATA`)를 검사가 도는 동안 임시 폴더로 돌린다. 제 값을 넣는 검사는 그대로
# 제 값을 쓴다(`monkeypatch.setenv`). Playwright 가 받아 둔 브라우저는 진짜 자리에 있으니 그 길은 따로 알려 준다.
# ※ `Path.home()` 아래로 가는 것(문서 폴더 · 엔진 · 브라우저 프로필)은 여기서 안 돌렸다 — 그건 따로 봐야 한다.
import atexit as _atexit
import shutil as _shutil
import tempfile as _tempfile

_REAL_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA", "")
if _REAL_LOCAL_APP_DATA:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(_REAL_LOCAL_APP_DATA, "ms-playwright"))
_TEST_LOCAL_APP_DATA = _tempfile.mkdtemp(prefix="sonjari-tests-localappdata-")
os.environ["LOCALAPPDATA"] = _TEST_LOCAL_APP_DATA
_atexit.register(_shutil.rmtree, _TEST_LOCAL_APP_DATA, ignore_errors=True)


def _guard_databases_outside_the_temp_folder() -> None:
    """시험은 **임시 폴더의 DB 만** 연다. 다른 곳을 가리키면 그 자리에서 떨어진다 (2026-10-09).

    그날의 사고: 손자리가 사본에서 돌린 시험이 운영 프로세스의 환경변수를 물려받아 **돌고 있는 진짜 DB** 에 붙었고, 거기서
    진행 중이던 판을 실패로 적었다. 조용히 붙었다는 것이 문제였다. 환경변수는 그 뒤로 막았다(위 · `project_env`) — 이것은
    그 문이 또 뚫려도 남는 둘째 문이다. 레딧에서 받은 조언 그대로다: 「테스트 모드에서는 DB 경로가 임시 폴더 밖을 가리키면
    바로 실패하게 하라」.

    ★ 이 문은 conftest 를 **불러오는 순간**에 선다 — 시험 파일을 모으는(수집) 단계의 불러오기도 지나가게 하지 않는다.
      처음엔 세션 픽스처로 뒀는데, 그러면 수집이 끝난 뒤에야 선다. 넣자마자 드러난 것이 바로 그 틈이었다:
      `alture_jarvis.api` 는 불러오기만 해도 기본 설정으로 앱을 만들었고(모듈 끝의 `app = create_app()`), 기본 뿌리는
      사용자의 앱 데이터 폴더다. 시험 수십 개가 수집 단계에서 **진짜 설치본의 DB** 를 열고 있었다. 그 줄은 「쓰일 때 만든다」로
      고쳤다(`api.__getattr__`) — 다음에 같은 종류가 또 생기면 이 문이 그 자리에서 알려 준다.
    """
    import tempfile
    from pathlib import Path

    from alture_jarvis import jobs

    if getattr(jobs.JobStore.__init__, "_guards_temp_only", False):
        return
    temp = Path(tempfile.gettempdir()).resolve()
    original = jobs.JobStore.__init__

    def guarded(self, path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if str(path) == ":memory:":
            # 메모리에만 있는 DB 는 어디에도 닿지 않는다 — 지나가게 둔다.
            return original(self, path, *args, **kwargs)
        resolved = Path(path).resolve()
        if not (temp == resolved or temp in resolved.parents):
            raise RuntimeError(
                f"시험이 임시 폴더 밖의 DB 를 열려고 했다: {resolved} — 시험은 tmp_path 아래의 DB 만 쓴다. "
                "설정을 기본값 그대로 만들지 않았는지(`JarvisConfig()`), 환경변수 JARVIS_* 가 남아 있지 않은지 보라."
            )
        return original(self, path, *args, **kwargs)

    guarded._guards_temp_only = True  # type: ignore[attr-defined]
    jobs.JobStore.__init__ = guarded  # type: ignore[method-assign]


_guard_databases_outside_the_temp_folder()


@pytest.fixture(autouse=True)
def _settings_a_test_loads_do_not_reach_the_next_test():  # noqa: ANN201
    """시험이 안쪽 보관소(`config._PRIVATE`)에 실은 값을 그 시험과 함께 치운다 (2026-10-09).

    `.env` 의 값은 이제 프로세스 환경이 아니라 그 보관소에 간다. 환경변수는 `monkeypatch` 가 되돌려 주지만 보관소는 아무도
    안 치운다 — `load_env_file` 을 부르는 시험이 남긴 값이 같은 일꾼의 다음 시험에서 설정으로 읽힌다. 순서에 따라 떨어지는
    시험이 된다.
    """
    from alture_jarvis import config

    before = dict(config._PRIVATE)
    yield
    config._PRIVATE.clear()
    config._PRIVATE.update(before)


@pytest.fixture(autouse=True, scope="session")
def _test_client_speaks_from_loopback() -> None:
    """검사용 클라이언트가 자기 주소를 루프백으로 말하게 한다."""
    original = starlette.testclient.TestClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        return original(self, *args, **kwargs)

    starlette.testclient.TestClient.__init__ = patched  # type: ignore[method-assign]
    yield
    starlette.testclient.TestClient.__init__ = original  # type: ignore[method-assign]


# ── 검사가 띄우는 브라우저는 **그래픽카드를 쓰지 않는다** (2026-10-07) ────────
#
# 실제로 일어난 일: 대표가 게임을 하는 중에 전체 회귀(`-n 6`)를 돌렸다. 시작 17초 뒤 화면이 연결된 그래픽카드의 드라이버가
# 응답을 놓쳤다는 기록(`nvlddmkm 153`)이 두 번 찍혔고 게임이 「DEVICE_HUNG」으로 꺼졌다. 진짜 브라우저를 띄우는 검사 파일이
# 29개이고, 여섯 줄이 한꺼번에 화면 없는 크로미움을 띄우면 그것들이 전부 그 카드에 붙는다(그날 앞선 세 번은 괜찮았으니
# 확정은 아니다 — 시각이 17초 차이로 맞았다).
#
# 검사는 화면을 그릴 일이 없다. 띄울 때 `--disable-gpu` 를 붙여 CPU 로만 그리게 한다 — 검사 결과는 같다.
# 운영 코드(손자리의 크롬)는 건드리지 않는다. 여기는 검사가 직접 띄우는 브라우저뿐이다.
@pytest.fixture(autouse=True, scope="session")
def _test_browsers_leave_the_graphics_card_alone() -> None:
    try:
        from playwright.sync_api import BrowserType
    except Exception:  # noqa: BLE001 - 브라우저 검사를 안 까는 환경
        yield
        return
    originals = {name: getattr(BrowserType, name) for name in ("launch", "launch_persistent_context")}

    def without_gpu(original):  # type: ignore[no-untyped-def]
        def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            given = list(kwargs.get("args") or [])
            if "--disable-gpu" not in given:
                given.append("--disable-gpu")
            kwargs["args"] = given
            return original(self, *args, **kwargs)
        return patched

    for name, original in originals.items():
        setattr(BrowserType, name, without_gpu(original))
    yield
    for name, original in originals.items():
        setattr(BrowserType, name, original)


# ── 검사는 **이 PC 에서 재생 중인 미디어를 건드리지 않는다** (2026-10-07) ──────────────
#
# 회귀 출력에 `Windows fatal exception: code 0x8001010e` 가 한 번에 20번씩 섞여 나왔다. 따라가 보니
# 「말하기 버튼을 누르면 재생 중인 미디어를 잠깐 멈춘다」(`media.pause_for_interaction`)를 타는 검사가
# 가짜를 안 끼운 채 **윈도우의 실제 미디어 제어**를 부르고 있었다 — 대표가 유튜브를 보는 중에도 회귀가 돈다.
# 그 20번은 「다른 스레드에서 불렀다」로 실패한 흔적이지만, 실패에 기대는 것은 방어가 아니다.
# (같은 날 낮에는 회귀가 띄운 브라우저가 화면 그래픽카드를 써서 게임이 꺼졌다 — 같은 가족이다.)
#
# 멈추기·다시 틀기를 빈 결과로 바꾼다. 무엇을 멈추고 되살릴지 고르는 쪽(`MediaSessionController`)의 검사는
# 가짜 뒷단을 끼워 돌리므로 그대로다. 운영 코드는 건드리지 않는다.
@pytest.fixture(autouse=True, scope="session")
def _tests_leave_playing_media_alone() -> None:
    try:
        from alture_jarvis.media import WindowsMediaBackend
    except Exception:  # noqa: BLE001 - 가져오지 못하는 환경이면 건드릴 것도 없다
        yield
        return
    originals = {name: getattr(WindowsMediaBackend, name) for name in ("pause_playing", "resume")}
    WindowsMediaBackend.pause_playing = lambda self, excluded_apps: []  # type: ignore[method-assign]
    WindowsMediaBackend.resume = lambda self, source_ids: []  # type: ignore[method-assign]
    yield
    for name, original in originals.items():
        setattr(WindowsMediaBackend, name, original)


# ── 검사는 **사람 화면에 창을 띄우지 않는다** (2026-09-01) ─────────────────
#
# 실제로 일어난 일: 라이브 상자 검사가 `성적표 (최종).csv` 를 만들자,
# 새로 붙인 「결과물이면 띄워 준다」가 그 파일로 **엑셀을 실행**했다. 회귀가
# 69% 에서 멎었고(py-spy 로 `sandbox.run` 에 걸린 것을 확인), 사용자님 화면에는
# 엑셀 창이 떴다.
#
# 코드 쪽은 이미 고쳤다(잡이 없으면 안 띄운다). 그래도 이 그물을 둔다 —
# 다음에 누가 `os.startfile` 을 다른 자리에 붙여도 검사에서는 안 뜨고,
# **띄우려 했다는 사실은 남는다**(막기만 하고 침묵하면 그게 더 나쁘다).
@pytest.fixture(autouse=True)
def _never_launch_apps_during_tests(monkeypatch, request):
    if not hasattr(os, "startfile"):  # pragma: no cover - 윈도우 밖
        return
    launched: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda path, *a, **k: launched.append(str(path)))
    # ★ 「이 확장자를 여는 프로그램이 있나」도 기계마다 다르다(2026-10-06). 워드가 없는 깨끗한 기계에서는
    #   `.docx` 가 탐색기로 빠져 **진짜 창**이 떴고, `os.startfile` 을 기다리던 시험 넷이 떨어졌다.
    #   시험에서는 늘 「있다」로 둔다 — 없는 경우는 `open_file(associated=…)` 로 직접 재는 시험이 따로 있다.
    monkeypatch.setattr("alture_jarvis.file_open._ask_windows", lambda suffix: "app")
    yield
    if launched:
        request.node.add_report_section(
            "call", "launched apps", "검사가 띄우려 한 파일:\n" + "\n".join(launched)
        )


@pytest.fixture(autouse=True)
def _installed_models_are_unknown_by_default(monkeypatch):
    """역할 모델 대체(`OllamaClient._selected_model`)가 **이 PC 의 실제 Ollama 목록**에 흔들리지 않게 (2026-09-20).

    기본은 「목록을 모른다(None)」 = 아무것도 안 바꾼다. 대체 규칙을 재는 시험은 인스턴스에 목록을 직접 넣는다.
    """
    from alture_jarvis.ollama import OllamaClient

    monkeypatch.setattr(OllamaClient, "_installed_models", lambda self: None)


@pytest.fixture(autouse=True)
def _tests_never_unload_the_real_gpu(monkeypatch):
    """★ 검사는 **이 PC 의 GPU 에서 모델을 내리지 않는다** (2026-09-20 실측).

    전체 검사가 도는 8분 동안 진짜 Ollama 로 58번 나갔다. 그중 나쁜 것은 `_make_room_for` 가
    보내는 `keep_alive: 0` 이다 — 검사가 사장님 GPU 에서 상주 모델(`qwen3.6`)을 **실제로
    내려 버렸고**, 뒤이은 워밍업이 젬마를 24시간 임대로 올려 놓았다. 같은 날 우리가 고친 바로
    그 고장을 검사 자신이 저질렀다.

    주소를 통째로 죽은 포트로 돌리면 가짜 서버를 세운 검사 57개가 같이 깨진다(재 봤다).
    그래서 **부수효과가 있는 그 한 자리만** 막는다. 이 동작 자체를 재는 검사는
    `inspect.getsource` 로 소스를 읽으므로 영향을 받지 않는다.
    """
    from alture_jarvis.ollama import OllamaClient

    monkeypatch.setattr(OllamaClient, "_make_room_for", lambda self, model: None)


@pytest.fixture(autouse=True)
def _tests_never_start_the_real_ollama_app(monkeypatch):
    """꺼진 Ollama 를 켜는 관리자가 **이 PC 에 공식 설치된 트레이 앱**을 찾아 띄우지 않게 (2026-10-01).

    `OllamaInstaller` 는 우리 설치가 없으면 `%LOCALAPPDATA%\\Programs\\Ollama\\ollama app.exe` 를 켠다. 운영 PC 에는
    그 앱이 실제로 있다. 그 길을 재는 시험은 `system_apps=` 로 가짜 자리를 넣는다.
    """
    from alture_jarvis import ollama_install

    monkeypatch.setattr(ollama_install, "_system_app_candidates", lambda: ())


@pytest.fixture(autouse=True)
def _tests_never_rewrite_the_real_guides(monkeypatch, request):
    """앱을 띄우는 시험이 **이 PC 의** `~/.claude/CLAUDE.md`·스킬을 고쳐 쓰지 않게 (2026-10-02).

    `create_app` 이 켜질 때 설치된 가이드를 새 문구로 맞춘다(`refresh_installed`). 첫 회귀에서 그게 실제 사용자 폴더를
    고쳤다(20:16, 백업까지 남김) — 내용은 맞았지만 커밋 전 문구가 실제 지침에 들어갈 수 있다. 가이드 시험은 가짜 폴더로 직접 부른다.
    """
    if request.module.__name__.endswith("test_guide_skill"):
        return
    from alture_jarvis.guide_skill import GuideSkillService

    monkeypatch.setattr(GuideSkillService, "refresh_installed", lambda self, tools: {})


@pytest.fixture(autouse=True)
def _browser_window_state_does_not_leak_between_tests():
    """크롬 주차 설정·사람이 부른 창은 **클래스** 값이다 — 런타임 하나를 만들면 다음 시험까지 남는다(2026-09-24)."""
    from alture_jarvis.browser import BrowserWorker

    BrowserWorker._park_offscreen = False
    BrowserWorker._human_shown = set()
    yield
    BrowserWorker._park_offscreen = False
    BrowserWorker._human_shown = set()


# ── 검사는 **진짜 Ollama 에 닿지 않는다** (2026-09-28 헤르메스 대결 중 발견) ─────────────────────────────
#
# 감시 로그에서 128K 러너가 올라온 시각 셋(13:00:52 · 13:28:16 · 13:36:10)이 **전체 회귀를 돌린 시각**과 겹쳤다.
# 시험 둘(`test_peer_guard::test_the_guard_is_actually_wired_into_the_app` · `test_silent_failure_organ::
# test_an_empty_commit_is_reported`)이 앱을 띄우며 **실제 `POST /api/generate`**(모델 예열)를 보냈다 — 설정 기본값 131072 로.
# 그래서 회귀 한 번마다 ① 128K 가 92% GPU 로 올라 CPU 가 뛰고 ② 다른 앱(헤르메스)이 쓰던 32K 러너를 빼앗았다.
# 워치독이 남의 모델을 뺏던 것(같은 날 새벽)과 같은 병이 검사 쪽에 있었다.
# 하나씩 막지 않고 **11434 로 가는 연결 자체를 거절**한다. 이 거절을 켠 채 전체 4,537건이 통과함을 확인했다 —
# 진짜 모델에 기대는 시험은 없다. 새 시험이 진짜 Ollama 를 부르면 여기서 연결 거절로 드러난다.
import socket as _socket

_OLLAMA_PORT = 11434
_real_connect = _socket.socket.connect
_real_connect_ex = _socket.socket.connect_ex


def _is_ollama(address: object) -> bool:
    return isinstance(address, tuple) and len(address) > 1 and address[1] == _OLLAMA_PORT


def _guarded_connect(self: _socket.socket, address: object, *args: object, **kwargs: object) -> object:
    if _is_ollama(address):
        raise ConnectionRefusedError("검사는 진짜 Ollama(11434)에 닿지 않는다 — tests/conftest.py")
    return _real_connect(self, address, *args, **kwargs)


def _guarded_connect_ex(self: _socket.socket, address: object, *args: object, **kwargs: object) -> int:
    if _is_ollama(address):
        return 10061  # 연결 거부
    return _real_connect_ex(self, address, *args, **kwargs)


_socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
_socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]


# ── 검사는 **진짜 디스코드 봇 토큰 · 클립보드에 닿지 않는다** (2026-10-18) ─────────────────────────────
#
# 본체가 뜰 때 디스코드 다리를 같이 켠다(`messaging/service.py`). 다리는 윈도우 자격 증명 관리자에서 봇 토큰을 읽는데,
# 대표 PC 에는 **진짜 토큰이 저장돼 있다.** 그대로 두면 앱을 띄우는 시험마다 진짜 봇으로 디스코드에 붙고, 잠금 파일은
# 시험의 임시 데이터 폴더에 생기니 따로 띄운 진짜 다리와도 안 부딪혀 **같은 메시지에 두 번 답한다.**
# 자격 증명 관리자 자리를 프로세스 안의 빈 보관소로, 클립보드를 빈 가짜로 바꾼다. 진짜 저장소를 재는 시험은 없다.
def _tests_never_touch_the_real_bot_token() -> None:
    try:
        from alture_jarvis.messaging import credentials as _credentials
        from alture_jarvis.messaging import service as _service
    except Exception:  # noqa: BLE001 - 가져오지 못하는 환경이면 건드릴 것도 없다
        return
    _store = _credentials.MemoryCredentialStore()

    class _EmptyClipboard:
        def read(self) -> str:
            return ""

        def clear(self) -> None:
            return None

    _credentials.default_store = lambda: _store  # type: ignore[assignment]
    _service.system_clipboard = lambda: _EmptyClipboard()  # type: ignore[assignment]


_tests_never_touch_the_real_bot_token()


# ── 끝나지 않는 시험은 크게 드러낸다 (2026-10-18) ───────────────────────────────────────────
#
# 열두 갈래 전체 회귀가 이날 세 번 멈췄다(한 번은 한 시간). 매번 헤드리스 크롬을 띄우는 시험 하나가 돌아오지 않았고,
# 멈춘 시험은 그때마다 달랐다. 크롬 시험을 한 작업자에 모아 봤더니 이번엔 결과 목록 시험 21개가 조용히 「건너뜀」이
# 됐다(초록불 · 되돌림). 그래서 막지 않고 드러낸다: 한 시험이 이 시간을 넘으면 그 작업자는 걸린 자리의 스택을 찍고
# 끝난다 — xdist 는 그 시험을 실패로 적고 작업자를 새로 띄운다. 영원히 기다리지도, 조용히 건너뛰지도 않는다.
_TEST_HANG_SEC = 300


@pytest.fixture(autouse=True)
def _a_hung_test_fails_loudly():
    import faulthandler

    faulthandler.dump_traceback_later(_TEST_HANG_SEC, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


# ★ **시험은 사람이 저장한 레시피를 읽지 않는다** (2026-10-20 · 확장 설계 T5).
#   배운 레시피는 실제 `문서\Sonjari\recipes` 에 산다. 그날 실사용 시험으로 거기 `yes24_learned.json` 이 생기자,
#   기본 설정으로 레시피 도구를 만드는 시험 둘이 그 파일까지 읽어 떨어졌다 — 시험 결과가 사람 PC 의 상태에 따라 달라진 것이다.
#   실제 문서 폴더를 가리키면 시험마다 빈 임시 폴더로 바꾼다. 시험이 `documents_dir` 를 따로 주면 그대로 쓴다.
#
# ★ 2026-10-22: 그래도 한 번 샜다 — 전체 회귀(12갈래)에서 test_site_recipes 가 진짜 `yes24_learned` 를 읽어 떨어졌다(따로 돌리면 통과,
#   의심 시험 14개를 앞에 붙여도 재현 안 됨). 새는 길을 못 짚었으니 **길과 상관없이** 막는다:
#   ① 「진짜 문서 폴더」는 시험이 하나도 돌기 전, 이 파일을 불러올 때 한 번 정한다(시험마다 그때의 `Path.home()` 으로 정하면 흔들린다).
#   ② 레시피를 읽는 함수 자체가 진짜 문서 폴더 아래를 받으면 빈 것으로 돌려준다 — 경로가 어떤 길로 계산됐든 진짜 파일은 못 읽는다.
#   ③ 막힌 일은 시험 이름 · 경로와 함께 남겨 회귀 끝에 경고로 보인다 — 다음에 새는 길이 드러나게.
from pathlib import Path as _Path

_REAL_DOCUMENTS = (_Path.home() / "Documents").resolve()
_REAL_DOCUMENTS_READS = _Path(_tempfile.gettempdir()) / "sonjari_tests_real_documents_reads.txt"


def _under_real_documents(path) -> bool:  # type: ignore[no-untyped-def]
    try:
        _Path(path).resolve().relative_to(_REAL_DOCUMENTS)
    except (ValueError, OSError, TypeError):
        return False
    return True


def pytest_sessionstart(session):  # type: ignore[no-untyped-def]
    if not hasattr(session.config, "workerinput"):  # 병렬이면 주인 프로세스에서만 지난 기록을 비운다
        _REAL_DOCUMENTS_READS.unlink(missing_ok=True)


def pytest_terminal_summary(terminalreporter):  # type: ignore[no-untyped-def]
    if _REAL_DOCUMENTS_READS.exists():
        lines = _REAL_DOCUMENTS_READS.read_text(encoding="utf-8").splitlines()
        terminalreporter.write_sep("!", f"시험이 진짜 문서 폴더를 읽으려다 막힘 {len(lines)}번 — 새는 길을 찾을 것")
        for line in lines[:20]:
            terminalreporter.write_line(line)


@pytest.fixture(autouse=True)
def _learned_recipes_stay_out_of_the_real_documents(monkeypatch, tmp_path_factory, request):
    from alture_jarvis import site_recipes
    from alture_jarvis.config import JarvisConfig

    original = JarvisConfig.user_recipes_dir
    empty: list[_Path] = []

    def isolated(self):  # type: ignore[no-untyped-def]
        path = original.fget(self)
        if not _under_real_documents(path):
            return path
        if not empty:
            empty.append(tmp_path_factory.mktemp("learned_recipes"))
        return empty[0]

    monkeypatch.setattr(JarvisConfig, "user_recipes_dir", property(isolated))

    real_load = site_recipes.load_recipes

    def guarded_load(directory):  # type: ignore[no-untyped-def]
        if _under_real_documents(directory):
            with _REAL_DOCUMENTS_READS.open("a", encoding="utf-8") as log:
                log.write(f"{request.node.nodeid} → {directory}\n")
            return {}
        return real_load(directory)

    monkeypatch.setattr(site_recipes, "load_recipes", guarded_load)
