from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

_VERIFY_LOCK = threading.Lock()
_VERIFY: Any = None


def shared_verify() -> Any:
    """`httpx.Client` 를 만들 때 쓸 **한 번 만든** 인증서 설정.

    ★ 2026-10-04 실측(헤르메스 전수조사의 「턴마다 붙는 덧시간 1.6~2.5초」를 다시 재다가): `httpx.Client(...)` 를 새로
      만들 때마다 인증서 묶음을 다시 읽어 **0.22초**가 들었다. 실제 요청(`/api/ps`)은 0.022초다. 이 파일은 호출마다
      클라이언트를 새로 만들고(11곳), 모델 한 턴에 대여섯 번을 거친다 — 턴마다 1초 넘게 아무 일도 안 하고 썼다.
      설정을 한 번 만들어 넘기면 0.0002초다. 연결·시간 제한·요청 방식은 그대로다.
    """
    global _VERIFY
    if _VERIFY is None:
        with _VERIFY_LOCK:
            if _VERIFY is None:
                try:
                    _VERIFY = httpx.create_ssl_context()
                except Exception:  # noqa: BLE001 — 못 만들면 httpx 기본 동작으로
                    _VERIFY = True
    return _VERIFY

from .config import JarvisConfig

#: 부르기 기록(`model_calls.jsonl`)에 붙일 이름표 — 「왜 불렀나」는 부르는 쪽만 안다 (2026-10-21 · `docs/측정계획_첫글자대기`).
#: 20초 넘은 첫 글자 대기 105건 중 생각 켬/끔 뒤집기 15건 · 기록 줄어듦 21건이 어느 부르기에서 나왔는지 몰라 짐작만 했다.
_CALL_TAGS: ContextVar[dict[str, Any]] = ContextVar("model_call_tags", default={})


@contextmanager
def tagged_call(**tags: Any) -> Iterator[None]:
    """이 안에서 부른 모델 호출의 기록에 이름표를 붙인다. 안쪽이 바깥을 덮는다(예: 걸음 안의 생각 예산 뒤 두 번째 부르기)."""
    token = _CALL_TAGS.set({**_CALL_TAGS.get(), **{key: value for key, value in tags.items() if value is not None}})
    try:
        yield
    finally:
        _CALL_TAGS.reset(token)


#: 흐름을 열다 404 를 맞았을 때 다시 물어보는 횟수와 간격.
#
# 처음엔 한 번(2초)이었는데 그걸로 모자랐다 — 재시도를 붙인 뒤에도 같은 404 로 판이
# 두 번 죽었다(2026-09-11 실측). 러너가 다시 서는 창이 2초보다 길다는 뜻이다.
# 무한은 안 된다: 무한 재시도는 진짜 고장을 침묵으로 바꾼다.
_STREAM_404_RETRIES = 2
_STREAM_404_BACKOFF_SEC = (2.0, 5.0)



#: 생각 되풀이 판정 (2026-09-26 노트북, 사용자: 「똑같은 띵킹 무한대」).
#:
#:   사고 예산(8천 자)은 **길이**만 본다. 4B 가 2천 자에서 같은 네 줄을 그대로 되풀이하기 시작하면 예산까지 수천 자·수십 초를
#:   헛돈다(캡처: 「하지만 이 질문은 … 내부 구현 방식에 대한 질문입니다」 문단이 통째로 반복). 끝의 한 토막이 **앞에 이미
#:   그대로** 있으면 되풀이다 — 그 자리에서 끊고, 예산을 넘긴 판과 같은 길(생각 없이 답)로 넘긴다.
_REPEAT_WINDOW = 160
_REPEAT_MIN_CHARS = 600
_REPEAT_CHECK_EVERY = 80


def thinking_is_looping(text: str) -> bool:
    """끝 `_REPEAT_WINDOW` 자가 앞부분에 글자 그대로 또 있으면 되풀이. 공백 차이는 무시한다."""
    if len(text) < _REPEAT_MIN_CHARS:
        return False
    flat = re.sub(r"\s+", " ", text)
    tail = flat[-_REPEAT_WINDOW:]
    # 너무 흔한 토막(같은 글자만 반복 등)은 판정에 쓰지 않는다 — 진짜 문장이어야 한다.
    if len(set(tail)) < 12:
        return False
    return flat.find(tail, 0, len(flat) - _REPEAT_WINDOW) >= 0


#: **답 글**의 되풀이는 생각보다 엄격하게 본다 — 멀쩡한 답(표·코드)에도 같은 줄이 두 번 나올 수 있다.
#: 끝 토막이 앞에 **세 번 이상** 더 있어야(모두 네 번) 되풀이로 친다 — 비슷한 함수 셋·같은 맺음말 셋은 멀쩡한 답이다.
#: 잘못 끊으면 답이 중간에서 잘린다(조용한 손해). 늦게 끊는 값은 몇백 자다.
_CONTENT_REPEAT_WINDOW = 200
_CONTENT_REPEAT_MIN_CHARS = 1200
_CONTENT_REPEAT_TIMES = 3


def content_is_looping(text: str) -> bool:
    """답 글이 같은 토막을 되풀이해 쏟아 내는 중인가.

    ★ 2026-10-04 허깅페이스 판(56247177): 모델이 「Qwen3-32B-A3B-Instruct가 아니라 Qwen3-32B-A3B-Instruct…」를 끝없이
      되풀이했다. 생각의 되풀이는 일찍 끊는데(09-18) 답 글은 상한(8,192토큰 — 한 턴 80초쯤)까지 그대로 흘렸고,
      그런 턴이 연달아 나와 판이 10분 동안 20걸음에서 멈춰 있었다. GPU 는 100% 였다 — 일하는 것처럼 보이는 멈춤이다.
    """
    if len(text) < _CONTENT_REPEAT_MIN_CHARS:
        return False
    flat = re.sub(r"\s+", " ", text)
    if len(flat) < _CONTENT_REPEAT_MIN_CHARS:
        return False
    tail = flat[-_CONTENT_REPEAT_WINDOW:]
    if len(set(tail)) < 12:
        return False  # 빈 칸뿐인 표 줄 같은 것 — 글자 종류가 적으면 판정하지 않는다
    return flat.count(tail, 0, len(flat) - _CONTENT_REPEAT_WINDOW) >= _CONTENT_REPEAT_TIMES


# ── 짧은 토막의 연달은 되풀이 (2026-10-12) ─────────────────────────────────────────
#
# 위의 판정은 1,200자를 넘고 200자짜리 끝 토막이 앞에 세 번 더 있어야 끊는다. 짧은 문장 하나를 되풀이하는 답은 그 문턱에
# 닿을 때까지 열 번 넘게 쏟아진다 — 작은 카드로 쓰는 사람이 「고장 난 TV 처럼 같은 말을 계속」이라고 한 구간이다.
# 운영의 지난 답 3,285개에 대 봤다: 「20~200자 토막이 **바로 이어서** 네 번」에 걸리는 것 3개, 셋 다 진짜였다 —
# 49,312자 · 35,252자 · 18,491자짜리 맴도는 답이 위의 판정을 빠져나가 그대로 나갔던 판이고, 이 판정이면 330 · 330 · 830자에서
# 끊겼다. 멀쩡한 답이 걸린 것은 0개였다(같은 줄이 네 번 **연달아** 나오는 표 · 목록 · 코드가 그 답들에는 없었다).
_STUTTER_MIN_UNIT = 20
_STUTTER_MAX_UNIT = 200
_STUTTER_TIMES = 4
_STUTTER_MIN_KINDS = 8  # 「| | | |」·「-----」처럼 글자 종류가 적은 토막은 판정하지 않는다


def content_is_stuttering(text: str) -> bool:
    """답 글의 끝이 같은 짧은 토막을 바로 이어서 `_STUTTER_TIMES` 번 되풀이한 것인가. 길이 문턱이 없다 — 일찍 끊는다."""
    flat = re.sub(r"\s+", " ", text[-(_STUTTER_MAX_UNIT * _STUTTER_TIMES + 400):])
    limit = min(_STUTTER_MAX_UNIT, len(flat) // _STUTTER_TIMES)
    for size in range(_STUTTER_MIN_UNIT, limit + 1):
        unit = flat[-size:]
        if len(set(unit)) < _STUTTER_MIN_KINDS:
            continue
        if flat.endswith(unit * _STUTTER_TIMES):
            return True
    return False


def _drop_repeats(text: str) -> str:
    """되풀이된 뒷부분을 떼고 처음 한 번만 남긴다 — 두 번째 호출에 같은 문단을 또 들려주지 않게."""
    flat = re.sub(r"\s+", " ", text)
    tail = flat[-_REPEAT_WINDOW:]
    # 가장 가까운 앞 자리 = 한 바퀴의 길이. (가장 먼 자리를 쓰면 여러 바퀴를 한 바퀴로 잰다.)
    first = flat.rfind(tail, 0, len(flat) - 1)
    period = len(flat) - _REPEAT_WINDOW - first
    if first < 0 or period <= 0:
        return text
    # 되풀이가 **어디서 시작됐는지** 뒤로 걸어 찾고, 한 바퀴만 남긴다.
    start = first
    while start > 0 and flat[start - 1] == flat[start - 1 + period]:
        start -= 1
    return flat[: start + period]

#: ★ **도구 목록이 붙은 호출에서 답 글이 길어지면 서버가 느려진다** (2026-10-04 실측, Ollama 0.32.14 · hf.co GGUF 의 `peg-native` 형식).
#:   서버가 토큰마다 지금까지 쓴 답 글 전체를 도구 문법으로 다시 훑는다 — 토큰당 시간이 (도구 수 × 쓴 길이)에 비례해 는다.
#:       같은 목록 글(약 3,500토큰)  도구 0개 답 글 24초(135 tok/s 일정) · 도구 151개 **도구 인자** 43초(110 일정)
#:                                  도구 40개 답 글 101초(109→19) · 80개 100초(2,269토큰, 93→13) · 151개 **382초**(78→5)
#:   운영 판 둘이 여기서 섰다: 10-03 22시 예약 판(8,191토큰·18분), 10-04 허깅페이스 판(6,428토큰에서 취소·12분).
#:   도구 목록을 늘 떼면 프롬프트 캐시가 깨진다(09-28) — 그래서 **무너지는 것을 재고 나서** 그 턴만 도구 없이 다시 받는다.
#:   기준은 이 PC 의 숫자가 아니라 **그 스트림 자신의 초반 속도 대비 비율**이다.
_SLOW_CONTENT_WINDOW = 150       # 조각(≈토큰) 묶음 하나
_SLOW_CONTENT_BASE_CHUNKS = 450  # 처음 세 묶음 전체로 「제 속도」를 잡는다 — 서버가 앞머리를 몰아 보내도 덜 흔들린다
_SLOW_CONTENT_MIN_CHUNKS = 600   # 이보다 짧은 답은 느려져 봐야 몇 초다 — 건드리지 않는다
_SLOW_CONTENT_MIN_SPAN = 0.05    # 한 묶음이 이보다 빨리 왔으면 생성 속도가 아니라 몰아 받은 것 — 판정하지 않는다
_SLOW_CONTENT_SHARE = 0.4        # 초반 속도의 이 비율 아래로
_SLOW_CONTENT_HITS = 2           # 연달아 두 묶음 — 한 번 출렁인 것(다른 앱이 GPU 를 잠깐 씀)은 넘긴다


#: 속도를 재는 시계. 시험이 바꿔 끼운다(가짜 스트림은 시간이 안 흐른다).
_clock = time.monotonic


def _cut_content_loop(text: str) -> str:
    """되풀이된 답 글에서 **처음 한 바퀴까지만** 남긴다 — 원문의 줄바꿈은 그대로 둔다(표가 한 줄로 뭉개지지 않게)."""
    kept = len(_drop_repeats(text))
    seen = 0
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                seen += 1
            in_space = True
        else:
            seen += 1
            in_space = False
        if seen >= kept:
            return text[: index + 1]
    return text


#: ★ 「시스템 메시지는 맨 앞에만」을 강제하는 채팅 템플릿 (2026-10-01 밤 Ornith 1.5 35B 운영 판).
#:   손자리는 일하는 도중에 시스템 안내(되받기·근거 장부·정리 지시)를 끼운다. Qwen 3.6 템플릿은 받아 줬는데 Ornith 템플릿은
#:   `raise_exception('System message must be at the beginning')` 으로 판 전체를 500 으로 죽였다(대표 운영 판).
#:   받아 주는 모델은 그대로 두고(프롬프트가 바뀌면 3.6 의 성적·캐시가 흔들린다), **거절한 모델만** 기억해 두고
#:   중간 시스템 메시지를 「[시스템 안내]」 사용자 메시지로 바꿔 보낸다.
_SYSTEM_FIRST_MARK = "System message must be at the beginnin"  # 「…beginning」·「…beginnin...」(llama 가 자른 원문) 둘 다
_SYSTEM_FIRST_ONLY: set[str] = set()


def fold_late_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """맨 앞 시스템 메시지(들)는 하나로 합치고, 그 뒤의 시스템 메시지는 사용자 쪽 「[시스템 안내]」로 바꾼다."""
    head: list[str] = []
    index = 0
    while index < len(messages) and str(messages[index].get("role") or "") == "system":
        head.append(str(messages[index].get("content") or ""))
        index += 1
    folded: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(head)}] if head else []
    for item in messages[index:]:
        if str(item.get("role") or "") == "system":
            folded.append({**item, "role": "user", "content": "[시스템 안내]\n" + str(item.get("content") or "")})
        else:
            folded.append(item)
    return folded


class _FoldSystemRetry(RuntimeError):
    """템플릿이 중간 시스템 메시지를 거절했다 — 접어서 한 번 다시 보낸다. 밖으로 새지 않는다."""


#: ★ 모델 실행기(llama-server)가 꺼졌을 때 Ollama 가 돌려주는 말 (2026-10-13 밤 6GB 노트북 · 메모리 24GB).
#:   실행기가 일반 메모리를 12GB 까지 쓰다 `std::bad_alloc` 으로 죽었고(윈도우 기록: 「가상 메모리 부족」), 그 요청은 500 으로
#:   돌아왔다. Ollama 는 그 500 의 글에 **55초 전의 다른 오류**(채팅 템플릿의 「System message must be at the beginning」)를
#:   같이 실어 보냈고, 우리는 그 글을 그대로 판의 실패 까닭으로 적었다 — 템플릿 오류는 이미 넘긴 뒤였는데 이름표가 원인을 속였다.
#:   실행기는 다음 요청에서 Ollama 가 다시 올린다. 그래서 한 번은 다시 묻고, 또 꺼지면 **꺼졌다고** 적는다.
_RUNNER_STOPPED_MARKS = ("model runner has unexpectedly stopped", "llama runner process has terminated",
                         "llama-server terminated")
#: 다시 묻기 전에 쉬는 시간 — 죽은 실행기가 쥔 그래픽 메모리를 Ollama 가 거둘 틈을 준다.
_RUNNER_STOPPED_BACKOFF_SEC = 3.0


def runner_stopped(text: str) -> bool:
    """Ollama 의 오류 글이 「모델 실행기가 꺼졌다」는 말인가."""
    low = str(text or "").lower()
    if any(mark in low for mark in _RUNNER_STOPPED_MARKS):
        return True
    # 2026-10-15 · 실행기는 살아 있는데 Ollama 가 자기 실행기에 붙지 못해(127.0.0.1 어떤 포트) 500 을 돌려주는 글도 「꺼졌다」처럼 한 번 다시 묻는다.
    return "dial tcp 127.0.0.1:" in low and ("connectex" in low or "connection refused" in low)


class _RunnerStopped(RuntimeError):
    """모델 실행기가 꺼졌다 — 한 번 다시 묻는다(Ollama 가 다시 올린다). 밖으로 새지 않는다."""


class _Transient404(RuntimeError):
    """**지금만** 404 인 상태. 모델은 설치돼 있는데 러너가 잠깐 모른다고 한다.

    없는 모델의 404 와 갈라야 해서 따로 둔다. 밖으로 새지 않는다 — 여기서 잡아
    한 번 다시 물어보고, 두 번째도 404 면 원래 오류가 그대로 올라간다.
    """


def _note_cut_first_pass(message: dict[str, Any], seconds: float) -> None:
    """끊고 다시 부른 호출의 관측에 **버린 첫 호출의 시간**을 더해 적는다 (2026-10-19 · 긱뉴스 판 1b6df02d).

    끊은 첫 호출은 흐름을 중간에 닫아서 서버의 끝 기록(`done` · 시간)이 안 온다. 그래서 관측(`_inference.telemetry`)에는
    두 번째 호출의 시간만 남고, 판의 `model_time` 은 첫 호출을 통째로 못 셌다. 그 판(699초)에서 그렇게 빠진 생성이
    두 번 · 약 137초였다(서버 기록: 4,096 + 4,424 토큰을 쓰다 끊김) — 「모델 시간 475초 + 도구 28초 = 나머지 196초는 어디?」의
    대부분이 이것이었다. 두 번째 호출이 또 끊겨 다시 부르면(드물다) 시간을 더해 간다. 동작은 바꾸지 않는다 — 적기만 한다.
    """
    inference = message.get("_inference")
    if not isinstance(inference, dict):
        return
    # 끊은 일 자체가 기록이다 — 시간이 0 으로 재져도(시험 · 아주 빠른 끊김) 횟수는 센다.
    inference["cut_first_pass_sec"] = round(float(inference.get("cut_first_pass_sec") or 0.0) + max(0.0, float(seconds)), 2)
    inference["cut_first_passes"] = int(inference.get("cut_first_passes") or 0) + 1


#: 최근에 본 상주 러너 컨텍스트 `{주소|모델: (ctx, monotonic)}` — `OllamaClient._resident_context` 가 「모른다」일 때 쓴다.
_RESIDENT_SEEN: dict[str, tuple[int, float]] = {}


#: 하네스가 모델에게 건넨 안내 표식 — 모델이 답 본문에 흉내 내면 지운다(사용자에게 줄 말이 아니다).
_ECHOED_NOTICE = re.compile(r"^\s*\[(?:생각 시간이 다 (?:됐다|됐습니다)|같은 생각을 되풀이하기 시작했다[^\]]*|Out of thinking time|Thinking time is up)\]\s*$")


def collapse_repeated_paragraphs(text: str) -> str:
    """같은 문단이 되풀이되면 처음 하나만 남기고, 끝에서 잘린 되풀이(앞 문단의 앞부분)도 버린다. 안내 표식 흉내 줄은 지운다."""
    kept: list[str] = []
    seen: set[str] = set()
    paragraphs = re.split(r"\n\s*\n", str(text or ""))
    for index, paragraph in enumerate(paragraphs):
        lines = [line for line in paragraph.split("\n") if not _ECHOED_NOTICE.match(line)]
        block = "\n".join(lines).strip()
        key = " ".join(block.split())
        if not key:
            continue
        # 구분선(`---`)·기호뿐인 문단은 되풀이가 정상이다 — 운영 답 2,609개 역검증에서 300개가 이것 때문에 바뀌었다.
        if not re.search(r"[0-9A-Za-z가-힣]", key):
            kept.append(block)
            continue
        # 맨 끝 문단이 앞 문단의 앞부분이면 생성이 잘린 꼬리다 — 짧아도 버린다. 중간 문단은 20자 이상일 때만(짧은 제목은 남긴다).
        last = index == len(paragraphs) - 1
        # 짧은 제목(「핵심 함수:」·`<br>`)의 되풀이는 정상이다 — 같은 문단 접기는 20자 이상만(역검증 772f3b19·842b4660).
        if (len(key) >= 20 and key in seen) or (
                (len(key) >= 20 or (last and len(key) >= 4)) and any(old != key and old.startswith(key) for old in seen)):
            continue
        seen.add(key)
        kept.append(block)
    return "\n\n".join(kept)


#: 대화 틀에서 생각 스위치를 읽는 자리(jinja · Go 틀)와 대화를 도는 자리.
_THINK_SWITCH_IN_TEMPLATE = re.compile(r"enable_thinking|\.IsThinkSet|\.ThinkLevel|\.Think\b")
_MESSAGES_LOOP_IN_TEMPLATE = re.compile(r"for\s+\w+\s+in\s+messages|range\s+[^}]*\.Messages")


def think_switch_is_drawn_before_the_messages(template: str) -> bool:
    """대화 틀이 생각 스위치를 **대화를 돌기 전에** 읽는가 — 그러면 스위치를 바꿀 때 프롬프트 앞머리가 달라진다.

    스위치가 대화 뒤(답을 시작하는 자리)에서만 쓰이면 꼬리만 달라져 캐시가 산다. 틀을 못 읽거나 둘 중 하나가 없으면 False.
    """
    switch = _THINK_SWITCH_IN_TEMPLATE.search(template or "")
    loop = _MESSAGES_LOOP_IN_TEMPLATE.search(template or "")
    return bool(switch and loop and switch.start() < loop.start())


class OllamaClient:
    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        # Code 잡이 도는 동안 **프로세스 전체**의 호출을 한 역할로 묶는다.
        self._pin_lock = threading.Lock()
        self._pin_role = ""
        self._pin_depth = 0
        # 판 하나만 다른 대화 모델로 돌린다(`pin_model`, 2026-10-18 디스코드 「@빠른」).
        self._pin_model = ""

    @property
    def pinned_role(self) -> str:
        return self._pin_role

    @contextmanager
    def pin_role(self, role: str) -> Iterator[None]:
        """이 블록 안에서는 모델·num_ctx·샘플링이 전부 이 역할을 따른다.

        3090 한 장에 채팅 모델(15.5G)과 코더(17.7G)가 같이 못 올라간다. Code 잡이
        도는 중에 채팅 역할 호출이 한 번이라도 끼면 17GB를 통째로 내렸다 다시
        올린다 — 실측 적재 30~53초다. 태그만 맞추는 것으로는 부족하다.
        ``num_ctx``가 갈려도 러너를 새로 띄우므로 역할 자체를 묶는다.

        ★ 스레드 지역이 아니다. 관찰 초소·예약·API 채팅은 **다른 스레드**에서
        도는데, 그쪽이 채팅 모델을 한 번 부르면 코더가 그대로 쫓겨난다. 잡이
        도는 동안만 프로세스 전체를 묶어야 실제로 축출이 0이 된다.
        """
        with self._pin_lock:
            previous = self._pin_role
            self._pin_role = str(role or "")
            self._pin_depth += 1
        try:
            yield
        finally:
            with self._pin_lock:
                self._pin_depth -= 1
                if self._pin_depth <= 0:
                    self._pin_depth = 0
                    self._pin_role = ""
                else:
                    self._pin_role = previous

    @property
    def pinned_model(self) -> str:
        return self._pin_model

    @contextmanager
    def pin_model(self, model: str) -> Iterator[None]:
        """이 블록 안에서는 **대화 모델로 가던 호출**이 이 태그로 간다 — 판 하나에만 거는 모델 바꾸기 (2026-10-18).

        디스코드에서 「@빠른 오늘 날씨」처럼 그 판만 다른 모델로 돌린다(`runtime._chat_job`). `pin_role` 과 같은 까닭으로
        프로세스 전체를 묶는다 — 판 도중 다른 스레드가 대화 모델을 한 번 부르면 3090 에서 둘이 서로를 쫓아낸다(사고 P).
        - 따로 정한 역할 모델(그림 · 코더 등, 대화 모델과 태그가 다른 역할)은 그대로 둔다. 바꾸는 것은 대화 모델 자리뿐이다.
        - 호출부가 태그를 찍었으면 안 바꾼다. 시스템 앞머리 · 설정 파일은 건드리지 않는다 — 블록을 나가면 흔적이 없다.
        """
        tag = str(model or "").strip()
        with self._pin_lock:
            previous = self._pin_model
            self._pin_model = tag
        try:
            yield
        finally:
            with self._pin_lock:
                self._pin_model = previous

    def _effective_role(self, role: str, model: str = "") -> str:
        pinned = self.pinned_role
        if not pinned or role == pinned:
            return role
        if role == "vision":
            # 이미지는 멀티모달 태그로 가야 한다. 여기서 묶으면 못 본다.
            return role
        if model and not self._same_model(model, self.config.model_for(pinned)):
            # 호출부가 다른 태그를 명시했다면 그 호출의 창 크기를 뺏지 않는다.
            return role
        return pinned

    @staticmethod
    def _model_identity(name: Any) -> str:
        """Ollama가 생략된 기본 태그를 붙여 돌려줘도 같은 모델로 본다."""
        value = str(name or "").strip().casefold()
        return value[:-7] if value.endswith(":latest") else value

    @classmethod
    def _same_model(cls, left: Any, right: Any) -> bool:
        return bool(cls._model_identity(left)) and cls._model_identity(left) == cls._model_identity(right)

    #: 「보통」 세기로 쓸 수 있는지 재 볼 값. 서버가 알아듣는 것은 `think` 자리의 글자다.
    _STEADY_THINK_LEVEL = "medium"
    #: 생각을 끈 호출과 입력 토큰 수가 이만큼 안쪽이면 앞머리가 같다고 본다(답을 시작하는 자리의 표식 몇 토큰만 다르다).
    _STEADY_FRONT_TOKEN_SLACK = 6

    def steady_think_level(self, model: str) -> str:
        """이 모델에 `think: "medium"` 을 줄 수 있고, 그때 프롬프트 앞머리가 생각을 끈 호출과 같은가 — 그러면 "medium", 아니면 "".

        ★ 2026-10-09 새벽 — 숙제 3 판(생각 예산 16,000자에 네 번 걸림 · 한 번에 130~200초)을 따라가다 잰 것.
          코드 판은 세기를 「보통」으로 정해 `reasoning_effort` 칸에 실어 왔는데(`_inference_contract`), 이 서버는 그 칸을
          읽지 않는다. 운영 모델의 틀은 세기를 안 받으면 **가장 센 것**(xhigh — 「신중히 생각하고 가정을 검증하고 대안을
          따져 보라」)을 프롬프트 첫 줄에 그린다. 입력 토큰으로 확인: 생각 끔 29 · 생각 켬 65 · 켬+reasoning_effort
          (맨 위·options 어디에 넣어도) 65 · `think:"low"` 53 · `think:"medium"` 27 · `think:"high"` 는 틀이 거절(500).
          즉 우리가 정한 「보통」은 한 번도 적용된 적이 없고, `think` 자리에 글자로 넣어야 닿는다.
          그리고 "medium" 은 앞머리에 문장이 없어 **생각을 끈 호출과 앞머리가 같다** — 한 판 안에서 생각을 껐다 켜도
          대화 전체를 다시 읽지 않는다(`think_moves_the_front` 의 문제가 같이 풀린다).

        틀은 모델마다 다르다. 이름이나 틀 글자를 읽지 않고 **작은 호출 둘로 잰다**(입력 토큰 수 비교 · 모델마다 한 번).
        그 모델이 올라와 있을 때만 잰다 — 이 호출로 모델을 다른 창 크기로 올리지 않는다. 못 재면 ""(예전 동작)이고 다음에 다시 본다.
        """
        cache = self.__dict__.setdefault("_steady_think_by_model", {})
        name = str(model or "")
        if name in cache:
            return str(cache[name])
        try:
            context = self._resident_window(name)
            if context <= 0:
                return ""
            off = self._prompt_tokens_for(name, False, context)
            on = self._prompt_tokens_for(name, self._STEADY_THINK_LEVEL, context)
            level = self._STEADY_THINK_LEVEL if off > 0 and on > 0 and abs(on - off) <= self._STEADY_FRONT_TOKEN_SLACK else ""
        except Exception:  # noqa: BLE001 — 못 쟀으면 예전 동작이다
            level = ""
        cache[name] = level
        return level

    def _resident_window(self, model: str) -> int:
        """지금 **올라와 있는** 이 모델의 창 크기. 안 올라와 있으면 0."""
        listed = (httpx.get(f"{self.config.ollama_base_url}/api/ps", timeout=5.0).json() or {}).get("models") or []
        for item in listed:
            if str(item.get("name") or "") == model or str(item.get("model") or "") == model:
                return int(item.get("context_length") or 0)
        return 0

    def _prompt_tokens_for(self, model: str, think: bool | str, context: int) -> int:
        """이 `think` 값으로 아주 작은 요청을 보냈을 때의 입력 토큰 수. 받아들이지 않으면 0."""
        # 모델을 부르는 길은 전부 카드의 자리를 먼저 비운다(`tests/test_one_model_on_the_card.py`). 재는 것은 그 모델이
        # 이미 올라와 있을 때뿐이라 보통은 볼 것만 보고 끝나지만, 규칙에 예외를 두지 않는다.
        self._make_room_for(model)
        response = httpx.post(
            f"{self.config.ollama_base_url}/api/chat",
            json={"model": model, "messages": [{"role": "user", "content": "ping"}], "stream": False, "think": think,
                  "keep_alive": self.config.ollama_keep_alive, "options": {"num_ctx": context, "num_predict": 1}},
            timeout=60.0,
        )
        if response.status_code != 200:
            return 0
        return int((response.json() or {}).get("prompt_eval_count") or 0)

    def _think_value(self, model: str, *, role: str, profile: str, think: bool) -> bool | str:
        """요청의 `think` 칸에 실을 값. 코드 판의 「보통」 세기는 서버가 알아듣는 글자로 싣는다(`steady_think_level`).

        코드 판이 아니거나, 세기가 「깊게」거나, 그 모델이 글자를 못 받으면 예전 그대로 참/거짓이다.

        ★ **조사·대화 판에는 싣지 않는다 — 재 보고 정했다** (같은 날 05:50~06:30 · 운영에만 올려 아홉 판 · 커밋 안 함).
          사람인·교보·항공권 세 판씩, 가장 센 세기(틀의 기본) 대 「보통」:

              사람인  1/3 · 1/3(두 번 잼)  →  2/3      평균 303 · 314  →  273초
              교보    3/3                →  2/3      평균 139        →   87초
              항공권  3/3                →  2/3      평균 427        →  420초

          기대한 것은 입력 다시 읽기의 감소였는데 조사 판에서는 거의 없었다(교보 47 → 40 · 항공권 140 → 140초) — 조사 판의
          다시 읽기는 생각 스위치 때문이 아니라 화면 글이 걸음마다 새로 붙는 정상 읽기였다. 항공권 한 판은 본문을 못 읽고
          접혔고 답의 줄 다수가 원문에서 확인되지 않았다(하네스가 partial 로 잡았다). 세 판씩이라 좋아졌다고도 나빠졌다고도
          못 하지만, 얻는 것이 분명하지 않으니 앞에 세우는 일(조사·문서)의 행동은 바꾸지 않는다.
        """
        if not think:
            return False
        normalized = "medium" if profile == "balanced" else profile
        if role != "code" or normalized != "medium":
            return True
        return self.steady_think_level(model) or True

    def think_moves_the_front(self, model: str) -> bool:
        """이 모델의 대화 틀이 **생각 스위치를 대화보다 앞에** 그리는가. 모르면 False(예전 동작)다. 모델마다 한 번만 묻는다.

        ★ 2026-10-09 새벽 — 우리 숙제를 손자리에게 맡긴 두 판(7958e32b · 그 재실행)의 서버 기록.
          Qwen 3.8 계열의 틀은 도구가 있으면 프롬프트 **첫 줄**에 「Reasoning effort is set to …」를 그리고, 그 줄은 생각이
          켜져 있을 때만 들어간다. 그래서 한 판 안에서 생각을 한 번 끄면 첫 토큰부터 달라져 대화 전체를 다시 읽고,
          다음 걸음에 다시 켜면 또 전부 다시 읽는다 — 입력 8~9만 토큰짜리 판에서 한 번에 89~126초였다(재실행 판의
          다시 읽기 397초 가운데 303초가 생각 예산 뒤의 세 번). 작은 실험(입력 9,500토큰): 생각을 끄고 다시 부르면
          9.10초(전부), 생각을 켠 채 같은 안내를 주면 0.32초였고 모델은 166자만 더 생각하고 도구를 불렀다.
          2026-09-18 의 「두 번째 읽기는 싸다(2만 토큰 0.5~1.4초)」는 그때 모델의 틀(스위치가 맨 끝에만 있다)에서 맞는 말이다.
        """
        cache = self.__dict__.setdefault("_think_front_by_model", {})
        name = str(model or "")
        if name in cache:
            return bool(cache[name])
        moved = False
        try:
            response = httpx.post(f"{self.config.ollama_base_url}/api/show", json={"model": name}, timeout=5.0)
            moved = think_switch_is_drawn_before_the_messages(str((response.json() or {}).get("template") or ""))
        except Exception:  # noqa: BLE001 — 못 물어봤으면 예전 동작이다(생각을 끄고 다시 부른다)
            moved = False
        cache[name] = moved
        return moved

    def _thinking_budget_for(self, model: str) -> int:
        """이 모델의 생각 예산(글자). 이름 앞부분이 맞으면 그 값, 아니면 기본값.

        ★ 2026-09-20: 8천 자는 Gemma 4 기준이었다(턴당 생각 2천 자 안팎이라 거의 안 걸림). Qwen 3.6 은 코워크 한 판에서
          5턴 중 4턴이 8천 자에서 끊겼고 턴당 32초를 생각에 썼다 — 끊은 뒤 1~2초 만에 제대로 된 걸음을 냈다.
        """
        name = str(model or "").strip().lower()
        # ★ 허깅페이스에서 받은 모델은 이름이 `hf.co/<올린 사람>/<모델>…` 이다 — 가족 이름은 **마지막 조각**의 앞머리다
        #   (2026-10-07: `hf.co/bartowski/Ornith-…` 에 `ornith` 가 안 맞아, 표에 넣어도 기본값으로 돌았을 것이다).
        base = name.rsplit("/", 1)[-1]
        budget = int(self.config.ollama_thinking_char_budget)
        table = {str(prefix).lower(): int(chars) for prefix, chars in dict(getattr(self.config, "ollama_thinking_budget_by_model", {}) or {}).items()}
        for family, chars in table.items():
            if name.startswith(family) or base.startswith(family):
                budget = chars
                break
        else:
            # ★ 2026-10-09: 가족 이름이 **이름 가운데** 있는 파생 모델(`swift-1.5-qwen3.8-27b-…`)은 그 가족의 값을 따른다.
            #   앞머리로만 맞추면 모델을 바꿀 때마다 표에서 빠져 젬마 기준 기본값으로 떨어진다 — 10-07 Ornith 에 이어
            #   10-08 에 운영 모델을 Swift 로 바꾸자 또 그랬다(8,000자에서 끊긴 것이 세 판에 열 번). 큰 판에서는 끊을 때마다
            #   버린 생각(55~170초)에 더해 대화 전체를 다시 읽는다(서버 기록 109초 · 115초). 긴 이름부터 본다.
            for family in sorted(table, key=len, reverse=True):
                if family and family in base:
                    budget = table[family]
                    break
        # 설정 「생각 깊이 › 보통」 — 생각하는 걸음에서도 짧게 끊는다(2026-09-24, 「너무 느리다」).
        if str(getattr(self.config, "agent_thinking_policy", "always") or "always") == "adaptive" and budget > 0:
            budget = min(budget, 2500)
        return budget

    def _installed_models(self) -> list[str] | None:
        """Ollama 에 깔린 태그들(60초 기억). 못 닿으면 None — 모르는 것을 「없다」로 치지 않는다."""
        now = time.monotonic()
        cached = getattr(self, "_installed_cache", None)
        if cached is not None and now - cached[0] < 60.0:
            return cached[1]
        try:
            with httpx.Client(verify=shared_verify(), timeout=2.0) as client:
                response = client.get(f"{self.config.ollama_base_url}/api/tags")
                response.raise_for_status()
                names: list[str] | None = [str(item.get("name") or "") for item in response.json().get("models", [])]
        except Exception:  # noqa: BLE001
            names = None
        self._installed_cache = (now, names)
        return names

    def missing_roles(self) -> dict[str, str]:
        """설정된 역할 모델 중 Ollama 에 **없는** 것 — {역할: 없는 태그}. 대화 모델 자체는 기존 `model_available` 이 본다."""
        names = self._installed_models()
        if names is None:
            return {}
        missing: dict[str, str] = {}
        for role, tag in dict(self.config.model_roles or {}).items():
            if role == "chat" or not str(tag or "").strip():
                continue
            if not any(self._same_model(name, tag) for name in names):
                missing[role] = str(tag)
        return missing

    #: 모델이 그림을 읽는지 물어본 답을 기억하는 시간(초). 같은 이름에 그림 부속을 붙이거나 떼면 답이 바뀌므로 짧게 둔다.
    _SIGHT_MEMORY_SEC = 60.0

    def reads_pictures(self, role: str = "chat") -> bool | None:
        """이 역할의 모델이 **그림을 읽는가** — Ollama 가 알리는 능력(`capabilities` 의 `vision`)으로 본다. 못 물었으면 None.

        ★ 2026-10-12: 그림이 든 호출은 여섯 군데(붙인 사진 · 페이지 그림 · 만든 화면 보기 · 스캔 PDF · 카메라 · 화면 좌표)인데
          전부 이 역할의 모델로 간다(설정의 「그림」 칸은 호출에서 읽지 않는다). 그림 부속이 없는 모델에게 그림을 주면
          Ollama 가 거절한다(`image input is not supported` · HTTP 500) — 지어내지는 않지만, 페이지 그림은 조각마다
          거절을 받느라 헛돌고, 붙인 사진은 거절 글이 그대로 실패로 나갔다. 부르기 전에 물어보고, 못 읽으면 그렇다고 말한다.
        ★ None(Ollama 에 못 닿음 · 능력을 안 알리는 옛 판)은 「못 읽는다」가 아니다. 모를 때는 예전처럼 불러 본다.
        """
        try:
            selected = self._selected_model(None, role=role)
        except ValueError:
            return None
        now = time.monotonic()
        memory: dict[str, tuple[float, bool]] = self.__dict__.setdefault("_sight_memory", {})
        known = memory.get(selected)
        if known is not None and now - known[0] < self._SIGHT_MEMORY_SEC:
            return known[1]
        try:
            with httpx.Client(verify=shared_verify(), timeout=5.0) as client:
                response = client.post(f"{self.config.ollama_base_url}/api/show", json={"model": selected})
                response.raise_for_status()
                capabilities = response.json().get("capabilities")
        except Exception:  # noqa: BLE001 — 못 물은 것은 모르는 것이다
            return None
        if not isinstance(capabilities, list) or not capabilities:
            return None
        sees = "vision" in {str(item) for item in capabilities}
        memory[selected] = (now, sees)
        return sees

    def _selected_model(self, model: str | None = None, *, role: str = "chat") -> str:
        if not model:
            role = self._effective_role(role)
            override = self._pin_model
            if override and role != "vision" and self._same_model(
                    self.config.model_for(role), self.config.model_for("chat")):
                return override
        selected = str(model or self.config.model_for(role)).strip()
        if not selected:
            raise ValueError("ollama_model_required")
        # ★ 2026-09-20 이 PC: 이미지 역할이 이미 지운 `plopfit-gemma4:latest` 를 가리켰다(사고 P 로 QAT 하나로 합친 뒤
        #   설정 한 줄만 남음). 역할 모델이 **깔려 있지 않으면** 대화 모델로 대신한다. 호출부가 이름을 찍었으면 안 바꾼다.
        if not model and role != "chat" and role in self.missing_roles():
            fallback = str(self.config.model_for("chat")).strip()
            if fallback:
                return fallback
        return selected

    def health(self, *, model: str | None = None, role: str = "chat") -> dict[str, Any]:
        selected = self._selected_model(model, role=role)
        try:
            with httpx.Client(verify=shared_verify(), timeout=3.0) as client:
                response = client.get(f"{self.config.ollama_base_url}/api/tags")
                response.raise_for_status()
                listed = list(response.json().get("models", []))
                names = [item.get("name", "") for item in listed]
                running_response = client.get(f"{self.config.ollama_base_url}/api/ps")
                running_response.raise_for_status()
                running = [dict(item) for item in running_response.json().get("models", [])]
            resident = next(
                (
                    item
                    for item in running
                    if self._same_model(item.get("name") or item.get("model"), selected)
                ),
                None,
            )
            return {
                "ok": True,
                "model": selected,
                "roles": dict(self.config.model_roles),
                "model_available": any(
                    self._same_model(name, selected) for name in names
                ),
                "models": names,
                # 받은 파일 크기 — 올리는 막대가 첫 회(이 PC 실측 전)에 쓰는 추정의 바탕(`load_progress`).
                "model_bytes": next(
                    (int(item.get("size") or 0) for item in listed if self._same_model(item.get("name"), selected)), 0
                ),
                # 역할 모델 중 깔려 있지 않은 것 — 그 역할은 대화 모델이 대신한다(`_selected_model`).
                "missing_roles": {
                    role: tag for role, tag in dict(self.config.model_roles or {}).items()
                    if role != "chat" and str(tag or "").strip()
                    and not any(self._same_model(name, tag) for name in names)
                },
                "resident": bool(resident),
                # 손자리가 모델에게서 마지막으로 답을 받은 지 몇 초인가(없으면 None). 워치독이 이 값이 작으면 따로 찌르지 않는다 —
                #   찌르는 호출도 하나뿐인 자리를 차지한다(2026-10-10).
                "last_ok_age_sec": (round(time.time() - self.__dict__["_last_ok_at"], 1)
                                    if self.__dict__.get("_last_ok_at") else None),
                "front_prime": {"enabled": bool(getattr(self.config, "front_prime_enabled", False)),
                                "last": self.__dict__.get("_front_last")},
                "context_length": int((resident or {}).get("context_length") or 0),
                "size_vram": int((resident or {}).get("size_vram") or 0),
                # ★ 2026-09-30: 손자리가 **쓸** 창 크기. 워치독이 모델을 깨울 때 이 값으로 깨워야 다음 질문이 러너를
                #   갈아 끼우지 않는다 — 전엔 OS 환경변수의 옛 값(65536)으로 깨웠고 손자리는 32768 이었다.
                "num_ctx": {role: int(self.config.num_ctx_for(role)) for role in ("chat", "code")},
                # ★ **능력 실측** 상태 (2026-09-20). 메모리 실측(`vram_measured`)과 다른 칸이다 —
                #   화면이 권한을 열 때 「이 모델은 아직 안 쟀습니다」를 같은 근거로 말하게 한다.
                "agent_grade": self._agent_grade(selected),
            }
        except Exception as exc:
            return {
                "ok": False,
                "model": selected,
                "roles": dict(self.config.model_roles),
                "error": str(exc),
                "agent_grade": self._agent_grade(selected),
            }

    @staticmethod
    def _agent_grade(tag: str) -> dict[str, Any]:
        from .model_catalog import agent_grade

        return agent_grade(tag)

    def _post_chat(self, client: "httpx.Client", body: dict[str, Any]) -> "httpx.Response":
        """`/api/chat` 한 번. **404 는 한 번만 다시 물어본다.**

        ## 왜 (2026-09-09 실측)

        3회 반복 벤치에서 9판 중 2판이 **1.0초에** 죽었다. 걸음 0, 도달 실패.
        고장 내용은 이것뿐이었다:

            Client error '404 Not Found' for url 'http://127.0.0.1:11434/api/chat'

        같은 모델을 curl 로 부르면 200 이 나왔고(콜드 로딩 38초), 워치독 기록에도
        같은 시각 프로브가 정상이었다. 모델은 설치돼 있었다. 재시도했더니 두 판 다
        정상으로 끝났다(11걸음/130초, 6걸음/125초).

        **근본 원인은 못 박았다.** 두 판 다 채팅 모델을 막 바꾼 직후 2분 안에
        일어났고, 그때 러너(`llama-server`)가 새로 뜨고 있었다. 짐작은 러너 교체
        창에서 Ollama 가 잠깐 그 모델을 모른다고 답하는 것인데, 재현이 안 됐다
        (내리고 즉시 불러도 200).

        원인을 모를 때 할 수 있는 일은 **증상이 사람에게 닿지 않게** 하는 것이다.
        그리고 404 는 두 가지 뜻이라 갈라야 한다:

            모델이 설치돼 있지 않다   → 영구 고장. 다시 물어도 소용없다.
            설치돼 있는데 지금 404    → 일시적. 한 번 더 물어보면 된다.

        `/api/tags` 로 그 둘을 가른다. 설치돼 있으면 2초 쉬고 한 번만 재시도한다 —
        무한 재시도는 진짜 고장을 침묵으로 바꾼다.
        """
        # ★ `/api/chat` 의 **단일 통로**라 자리 비우기를 여기 둔다 (2026-09-20).
        #
        #   부르는 쪽들이 이미 비우고 오지만, 그 목록에 하나라도 빠지면 그 길에서만
        #   둘이 같이 올라간다 — 이 저장소가 「등록 자리 하나를 빠뜨려」 겪은 그 모양이다.
        #   비울 것이 없으면 `/api/ps` 한 번(로컬, 수 ms)으로 끝나고 아무 일도 안 한다.
        self._front_seen(body)
        self._make_room_for(str(body.get("model") or ""))
        self._note_prefix_break(body)
        if str(body.get("model") or "") in _SYSTEM_FIRST_ONLY and isinstance(body.get("messages"), list):
            body = {**body, "messages": fold_late_system_messages(body["messages"])}
        response = client.post(f"{self.config.ollama_base_url}/api/chat", json=body)
        if response.status_code == 200:
            self.__dict__["_last_ok_at"] = time.time()  # 모델이 방금 실제로 답했다 — 워치독이 따로 찌르지 않아도 된다
        if response.status_code >= 500 and _SYSTEM_FIRST_MARK in response.text and isinstance(body.get("messages"), list):
            # 시스템은 맨 앞만 받는 템플릿 — 기억해 두고 접어서 한 번 다시(`fold_late_system_messages`).
            _SYSTEM_FIRST_ONLY.add(str(body.get("model") or ""))
            body = {**body, "messages": fold_late_system_messages(body["messages"])}
            response = client.post(f"{self.config.ollama_base_url}/api/chat", json=body)
        if response.status_code != 404:
            return response
        if not self._model_is_installed(str(body.get("model") or "")):
            # 진짜 없는 모델이거나 물어볼 수도 없다. 이 404 는 사실이므로 그대로 올린다.
            return response
        time.sleep(2.0)
        self._make_room_for(str(body.get("model") or ""))
        return client.post(f"{self.config.ollama_base_url}/api/chat", json=body)

    def _model_is_installed(self, model: str) -> bool:
        """404 의 두 뜻을 가른다 — **없는 모델**인가, **지금만** 404 인가.

        한 곳에 둔다. 예전에는 이 판단이 `_post_chat` 안에만 있어서 **스트리밍
        길에는 재시도가 아예 없었다.** 판단이 두 벌이면 한 벌만 고치고 고쳤다고
        믿게 된다 — 이 저장소가 `took_ms` 로 바로 어제 겪은 일이다.
        """
        if not model:
            return False
        try:
            with httpx.Client(verify=shared_verify(), timeout=5.0) as probe:
                names = [
                    str(item.get("name") or item.get("model") or "")
                    for item in probe.get(
                        f"{self.config.ollama_base_url}/api/tags"
                    ).json().get("models", [])
                ]
        except Exception:
            return False          # 물어볼 수도 없으면 재시도하지 않는다
        return any(self._same_model(name, model) for name in names)

    def _wait_out_transient_404(self, body: dict[str, Any]) -> None:
        """흐름을 열기 전에 **가벼운 한 번**으로 러너가 살아 있는지 본다.

        `_post_chat` 와 같은 판단인데, 스트리밍은 응답을 열고 나서 물러나기가
        어려워 미리 확인한다.

        ## ★ 싸야 한다 (2026-09-09, 내가 낸 사고)

        처음엔 `/api/chat` 에 **빈 메시지**를 보내 살아 있는지 봤다. 「생성도
        적재 해제도 안 하니 값이 싸다」고 적어 뒀는데 **틀렸다.** 빈 메시지 +
        0 이 아닌 `keep_alive` 는 Ollama 에게 **모델을 올리라는 뜻**이라 실측
        **8.2초**가 걸렸다. 모델 호출마다 붙으니 판당 80~160초다.

        편차 재측정에서 바닥이 66초 → 188초로 올랐고, 그 정체가 이것이었다.
        **9판 중 2판을 살리려다 9판 전부를 3배 느리게 만들었다.**

        지금은 `/api/ps` 만 본다(GET, ~50ms). 그리고 기다릴 이유가 있는 경우만
        기다린다 — **다른 모델이 올라와 있을 때**, 즉 교체가 실제로 일어나는
        창일 때만. 우리 모델이 이미 있거나 아무것도 없으면 곧장 간다.
        """
        model = str(body.get("model") or "")
        if not model:
            return
        try:
            with httpx.Client(verify=shared_verify(), timeout=3.0) as client:
                running = client.get(
                    f"{self.config.ollama_base_url}/api/ps"
                ).json().get("models", [])
                names = [
                    str(item.get("name") or item.get("model") or "") for item in running
                ]
                if any(self._same_model(name, model) for name in names):
                    return          # 이미 우리 모델이 올라와 있다. 교체 창이 아니다.
                if not names:
                    return          # 아무것도 안 올라와 있다. 콜드 적재일 뿐이다.
                # 다른 모델이 올라와 있다 = 교체가 일어난다. 404 가 났던 창이다.
                # `_make_room_for` 가 이미 내리라고 했으므로 잠깐만 기다린다.
                time.sleep(1.0)
        except Exception:
            return          # 확인이 안 되면 원래 하던 대로 간다

    def _make_room_for(self, model: str) -> None:
        """다른 모델이 자리를 차지하고 있으면 **먼저 내린다.**

        ## 왜 우리가 이걸 하나 (2026-08-31 실측)

        코드 모드에서 코워크로 넘어가면 타임아웃이 났다. 같은 요청·같은 인자로 두 번
        재 봤다:

            스스로 교체하게 두면   420초 무응답 (헤더조차 안 옴)
            먼저 내리고 부르면      24.4초 정상

        차이는 **직접 내렸는가** 하나뿐이다. ``OLLAMA_MAX_LOADED_MODELS=1`` 인데도
        Ollama 는 축출을 시작조차 안 했다 — 그동안 Qwen 으로 오는 프로브는 607ms 에
        멀쩡히 처리했다. 그러니 서버가 죽은 것도, 바쁜 것도 아니다.

        ``OLLAMA_LOAD_TIMEOUT`` 이 5분인데 그 에러조차 안 왔다. **적재를 시작조차
        안 했다는 뜻이다.** 짐작 가는 것은 `keep_alive` 24시간이 워치독 프로브마다
        갱신돼 그 모델이 영영 「만료되지 않은」 상태로 남는 것인데, 확증은 없다.

        원인을 몰라도 **자리는 우리가 비울 수 있다.** 내리는 데 실측 0.2초다.

        아무것도 안 올라와 있거나 원하는 것이 이미 올라와 있으면 아무 일도 안 한다.
        실패하면 조용히 넘어간다 — 여기서 막으면 멀쩡한 판까지 죽는다.
        """
        try:
            with httpx.Client(verify=shared_verify(), timeout=3.0) as client:
                running = client.get(
                    f"{self.config.ollama_base_url}/api/ps"
                ).json().get("models", [])
                stale = [
                    str(item.get("name") or item.get("model") or "")
                    for item in running
                    if not self._same_model(item.get("name") or item.get("model"), model)
                ]
                for name in stale:
                    if not name:
                        continue
                    # ★ 우리가 내린 것은 적는다(2026-09-27 밤). 「질문할 때마다 모델이 올라갔다 내려간다」를 잡으려는데
                    #   누가 35B 를 내렸는지 아무 데도 없었다 — Ollama 는 로그 없이 떠 있고, 여기는 조용히 내렸다.
                    self._load_ledger({"event": "unloaded_by_ontelic", "unloaded": name, "for": model})
                    # keep_alive:0 = 지금 내려라. 메시지가 비면 생성도 안 한다.
                    client.post(
                        f"{self.config.ollama_base_url}/api/chat",
                        json={"model": name, "messages": [], "keep_alive": 0},
                    )
        except Exception:
            # 자리를 못 비웠다고 판을 죽이지 않는다. 원래 하던 대로 시도한다.
            return

    #: 이만큼 넘게 걸린 적재는 「다시 올렸다」로 적는다. 상주 모델을 부르면 load_duration 은 수십 ms 다.
    _RELOAD_NOTE_MS = 2000

    def _note_prefix_break(self, body: dict[str, Any]) -> None:
        """직전 요청과 비교해 **앞부분이 바뀌었으면** 어디가 바뀌었는지 `data/prefix_breaks.jsonl` 에 적는다.

        ## 왜 (2026-09-28 레딧 판)

        qwen3.6 은 하이브리드 구조라 llama.cpp 가 **저장해 둔 체크포인트로만** 캐시를 되돌린다. 전사 중간이
        한 글자라도 바뀌면 첫 체크포인트(시스템·요청 끝 근처)까지 떨어져 뒤를 통째로 다시 읽는다 — 그 판은
        걸음마다 8천~1만 5천 토큰을 다시 읽어 걸음당 8~15초를 썼다. 무엇이 앞을 바꾸는지는 **추측하지 말고
        찍는다.** 뒤에 붙기만 한 요청은 적지 않는다. 기록 실패는 삼킨다 — 계측 때문에 판이 죽으면 안 된다.
        """
        try:
            import hashlib

            def digest(value: Any) -> str:
                return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]

            messages = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
            tool_names = sorted(
                str(((tool or {}).get("function") or {}).get("name") or "")
                for tool in (body.get("tools") or []) if isinstance(tool, dict)
            )
            current = {
                "model": str(body.get("model") or ""),
                "tool_names": tool_names,
                "tools": digest(body.get("tools") or []),
                "options": digest(body.get("options") or {}),
                # 무엇이 바뀌었는지 보려고 값도 둔다(작다). ★ 2026-09-28 C1: 판 안에서 옵션이 바뀌어 32K 러너가 128K 로 갈렸는데
                #   어느 값이 바뀌었는지 기록에 없어 재현도 못 하고 원인을 못 잡았다.
                "option_values": {k: v for k, v in (body.get("options") or {}).items() if isinstance(v, (int, float, str, bool))},
                "digests": [digest(m) for m in messages],
                "messages": messages,
            }
            previous = getattr(self, "_last_prefix", None)
            self._last_prefix = current
            if not previous or previous["model"] != current["model"]:
                return
            changed = next(
                (i for i, (a, b) in enumerate(zip(previous["digests"], current["digests"])) if a != b), None
            )
            shrank = changed is None and len(current["digests"]) < len(previous["digests"])
            if changed is None and not shrank and previous["tools"] == current["tools"] and previous["options"] == current["options"]:
                return  # 뒤에 붙기만 했다 — 캐시가 산다
            row: dict[str, Any] = {
                "model": current["model"],
                "prev_messages": len(previous["digests"]),
                "messages": len(current["digests"]),
                "tools_changed": previous["tools"] != current["tools"],
                "options_changed": previous["options"] != current["options"],
            }
            if row["options_changed"]:
                before, after = previous.get("option_values") or {}, current.get("option_values") or {}
                row["options_diff"] = {k: [before.get(k), after.get(k)] for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
                if "num_ctx" in row["options_diff"]:
                    row["ctx_choice"] = dict(getattr(self, "_last_ctx_choice", None) or {})
            if row["tools_changed"]:
                # 도구 목록은 템플릿에서 시스템 지시 바로 뒤에 들어간다 — 여기가 바뀌면 그 뒤 전사 전체를 다시 읽는다.
                before, after = set(previous.get("tool_names") or []), set(current["tool_names"])
                row.update({
                    "tools_added": sorted(after - before)[:20],
                    "tools_removed": sorted(before - after)[:20],
                    "tool_count": [len(before), len(after)],
                })
            if changed is not None:
                old, new = previous["messages"][changed], current["messages"][changed]
                row.update({
                    "index": changed,
                    "role": str(new.get("role") or ""),
                    "tool_name": str(new.get("tool_name") or ""),
                    "keys_changed": sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k)),
                    "old_chars": len(str(old.get("content") or "")),
                    "new_chars": len(str(new.get("content") or "")),
                    "old_head": str(old.get("content") or "")[:160],
                    "new_head": str(new.get("content") or "")[:160],
                })
            path = Path(self.config.data_dir) / "prefix_breaks.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **row}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        finally:
            # 같은 종류끼리 비교는 **따로** 한다 — 이쪽이 실패해도 위 기록은 남아야 한다.
            same_kind = getattr(self, "_note_same_kind_break", None)
            if same_kind is not None:
                try:
                    import hashlib

                    def _digest(value: Any) -> str:
                        return hashlib.sha1(
                            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                        ).hexdigest()[:12]

                    same_kind(body, [m for m in (body.get("messages") or []) if isinstance(m, dict)], _digest)
                except Exception:  # noqa: BLE001
                    pass

    def _note_same_kind_break(self, body: dict[str, Any], messages: list[dict[str, Any]], digest: Any) -> None:
        """**같은 종류**(에이전트·라우터·사실 추출…)의 직전 요청과 앞머리가 어디서 갈라지나 — `data/prefix_same_kind.jsonl`.

        ## 왜 (2026-09-30 서버 로그)

        이 서버는 최근 프롬프트 7개(8GB)를 따로 들고 있다가 새 요청과 가장 많이 겹치는 것을 되살린다. 그런데 새 질문의 첫
        에이전트 호출이 직전 에이전트 프롬프트와 **65토큰**만 겹쳐 2만 6천 토큰을 다시 읽었다. 바로 앞 요청(곁가지)과만
        비교하는 `_note_prefix_break` 로는 그 이유가 안 보인다 — 같은 종류끼리 비교해서 도구 이름·도구 설명·시스템
        지시 중 **무엇이 판마다 달라지는지** 찍는다. 추측하지 않는다(헤르메스는 이걸 「캐시는 신성하다」로 설계에 박았다).
        """
        system = next((str(m.get("content") or "") for m in messages if m.get("role") == "system"), "")
        kind = digest(system[:60])
        tools = [tool for tool in (body.get("tools") or []) if isinstance(tool, dict)]
        described = {
            str(((tool.get("function") or {}).get("name")) or ""): digest(tool) for tool in tools
        }
        order = [str(((tool.get("function") or {}).get("name")) or "") for tool in tools]
        # 요청 메시지의 **끝**으로 가린다 — 앞머리는 이번 판 맥락(`transcript.with_job_context`)이라 판이 달라도 같을 수 있다.
        first_user = next((str(m.get("content") or "")[-200:] for m in messages if m.get("role") == "user"), "")
        current = {"system": system, "described": described, "order": order, "first_user": first_user}
        memory = getattr(self, "_last_by_kind", None)
        if memory is None:
            memory = self._last_by_kind = {}
        previous = memory.get(kind)
        memory[kind] = current
        # 같은 판의 다음 걸음은 앞 비교(`_note_prefix_break`)가 본다. 여기는 **새 판**끼리만.
        if not previous or previous["first_user"] == first_user:
            return
        before, after = previous["described"], described
        common = [name for name in order if name in before]
        system_at = next(
            (i for i, (a, b) in enumerate(zip(previous["system"], system)) if a != b),
            None if len(previous["system"]) == len(system) else min(len(previous["system"]), len(system)),
        )
        row = {
            "kind_head": system[:60],
            "tools_added": sorted(set(after) - set(before))[:30],
            "tools_removed": sorted(set(before) - set(after))[:30],
            "tools_described_differently": [name for name in common if before[name] != after[name]][:30],
            "tool_order_changed": [name for name in previous["order"] if name in after] != [n for n in order if n in before],
            "tool_count": [len(before), len(after)],
            "system_chars": [len(previous["system"]), len(system)],
            "system_diverges_at": system_at,
        }
        if system_at is not None:
            row["system_old"] = previous["system"][max(0, system_at - 60): system_at + 120]
            row["system_new"] = system[max(0, system_at - 60): system_at + 120]
        if not (row["tools_added"] or row["tools_removed"] or row["tools_described_differently"]
                or row["tool_order_changed"] or system_at is not None):
            return
        path = Path(self.config.data_dir) / "prefix_same_kind.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **row}, ensure_ascii=False) + "\n")

    def _load_ledger(self, row: dict[str, Any]) -> None:
        """모델을 내리고 다시 올린 기록 — `data/ollama_loads.jsonl`. 실패해도 조용히 넘어간다(기록 때문에 판이 죽으면 안 된다)."""
        try:
            path = Path(self.config.data_dir) / "ollama_loads.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": stamp, **row}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    #: 부르기 기록 파일이 이만큼 커지면 반으로 줄인다(최근 것만 남긴다).
    CALL_LOG_MAX_BYTES = 4_000_000

    def _log_call(self, body: dict[str, Any], payload: dict[str, Any], first_byte: float, first_token: float = 0.0,
                  *, cut: str = "", elapsed: float = 0.0, thinking_chars: int | None = None,
                  content_chars: int | None = None) -> None:
        """부르기마다 한 줄 — **첫 글자까지 몇 초 · 앞부분 몇 토큰을 몇 초에 읽었나** · 도구 목록 · 지시문 앞머리 지문.

        ★ 2026-10-20 대표: 「처음 생각 토큰이 나오기까지 너무 오래 걸린다 — 이거 제일 짜증 나」. 같은 엑셀 판이 10-16 엔 앞부분 읽기 5.9초,
          오늘은 32.3초였다(글 만드는 시간은 같음). 판 합계만 남아서 **어느 부르기에서 캐시가 깨졌는지** 몰랐다. 「첫 바이트」는 재고 있었는데
          버리고 있었다. 이제 남긴다 — 짐작으로 고치지 않으려고. 글 · 도구 내용은 안 남기고 지문(해시)만.
        """
        try:
            import hashlib

            messages = body.get("messages") if isinstance(body.get("messages"), list) else []
            system = next((str(item.get("content") or "") for item in messages if isinstance(item, dict) and item.get("role") == "system"), "")
            tools = body.get("tools") if isinstance(body.get("tools"), list) else []
            names = [str(((tool or {}).get("function") or {}).get("name") or "") for tool in tools]
            row = {
                "model": str(body.get("model") or "")[-40:],
                "messages": len(messages),
                "tools": len(names),
                "tools_sig": hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:10],
                "system_chars": len(system),
                "system_head_sig": hashlib.sha1(system[:4000].encode("utf-8")).hexdigest()[:10],
                "first_byte_sec": round(float(first_byte or 0.0), 2),
                "first_token_sec": round(float(first_token or 0.0), 2),
                "prompt_tokens": int(payload.get("prompt_eval_count") or 0),
                "prefill_sec": round(float(payload.get("prompt_eval_duration") or 0) / 1e9, 2),
                "eval_tokens": int(payload.get("eval_count") or 0),
                "load_sec": round(float(payload.get("load_duration") or 0) / 1e9, 2),
                "temperature": (body.get("options") or {}).get("temperature"),
                "think": body.get("think"),
            }
            # 이름표(왜 불렀나 · 지난번과 앞에서부터 같은 메시지 수) — 기록 칸 이름을 덮지 않는다.
            row.update({key: value for key, value in _CALL_TAGS.get().items() if key not in row})
            # ★ 2026-10-22 대표: 코딩 분업 판 33분 중 「글 쓰기 약 16분」을 생각과 실제 답으로 나누지 못했다(생성 토큰은 둘을 합친 수).
            #   글자 수만 남긴다(내용은 안 남긴다).
            if thinking_chars is not None:
                row["thinking_chars"] = int(thinking_chars)
            if content_chars is not None:
                row["content_chars"] = int(content_chars)
            if cut:
                # ★ 우리가 중간에 끊은 부르기(생각 예산 · 되풀이 · 느린 글)도 남긴다 — 예전엔 기록 줄보다 먼저 빠져나가
                #   「생각하다 끊긴 몇 분」이 기록에 없었다. 서버가 끝까지 안 가 토큰 수는 0 이다.
                row["cut"] = cut
                row["elapsed_sec"] = round(float(elapsed or 0.0), 2)
            path = Path(self.config.data_dir) / "model_calls.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > self.CALL_LOG_MAX_BYTES:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **row}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — 기록은 덤이다. 부르기를 실패시키지 않는다
            pass

    def _note_reload(self, body: dict[str, Any], payload: dict[str, Any]) -> None:
        try:
            load_ms = float(payload.get("load_duration") or 0) / 1_000_000
        except (TypeError, ValueError):
            return
        if load_ms >= self._RELOAD_NOTE_MS:
            options = body.get("options") if isinstance(body.get("options"), dict) else {}
            self._load_ledger({"event": "reloaded", "model": body.get("model"), "num_ctx": options.get("num_ctx"),
                               "load_ms": round(load_ms), "tools": bool(body.get("tools"))})

    def effective_num_ctx(self, role: str = "chat", model: str | None = None) -> int:
        """이번 요청이 **실제로 쓸** 컨텍스트 — 다른 앱의 러너에 맞췄으면 그 크기(2026-09-28 T1).

        전사 예산을 설정값(128K)으로 잡고 32K 러너를 받아 쓰자 창이 넘쳐(`truncated = 1`) 읽은 상세 본문이 밀려났고,
        모델은 본문 없이 유명한 책 제목과 가격을 지어냈다. 예산은 이 값으로 잡는다.
        """
        selected = self._selected_model(model, role=role)
        return int(self._options(0.0, model=selected, role=role)["num_ctx"])

    def _resident_names(self) -> list[str]:
        """지금 Ollama 에 올라가 있는 모델 이름들. 못 물어보면 빈 목록(모른다 = 없다고 보고 예전처럼 한다)."""
        try:
            with httpx.Client(verify=shared_verify(), timeout=1.5) as client:
                response = client.get(f"{self.config.ollama_base_url}/api/ps")
                response.raise_for_status()
                return [str(item.get("name") or item.get("model") or "") for item in response.json().get("models", [])]
        except Exception:
            return []

    #: 「모른다」일 때 믿을 수 있는 최근 관측의 수명(초).
    _RESIDENT_MEMORY_SEC = 600.0

    def _resident_context(self, model: str) -> int:
        """지금 올라가 있는 이 모델 러너의 컨텍스트. 없으면 0.

        ★ **「모른다」를 「없다」로 읽지 않는다** (2026-09-28 헤르메스 대결 재측정). 백엔드 재기동 직후 첫 판에서 이 질문이 1.5초 제한에
          걸려 0 을 돌려줬고, 에이전트 호출이 설정값 131072 로 나가 **32K 로 떠 있던 러너를 128K 로 갈아 끼웠다**(계측기 기록:
          `resident: 0` · 그 순간 `/api/ps` 는 32768). 제한을 늘리고, 실패하면 최근에 본 크기를 쓴다.
        """
        if not self.config.ollama_adopt_resident_context:
            return 0
        # 클라이언트 객체가 여럿이어도(에이전트·곁가지 호출) 본 것은 같이 쓴다 — 같은 Ollama 를 본 것이다.
        seen = _RESIDENT_SEEN
        key = f"{self.config.ollama_base_url}|{self._model_identity(model)}"
        try:
            with httpx.Client(verify=shared_verify(), timeout=5.0) as client:
                response = client.get(f"{self.config.ollama_base_url}/api/ps")
                response.raise_for_status()
                listed = response.json().get("models", [])
                for item in listed:
                    if self._same_model(
                        item.get("name") or item.get("model"), model
                    ):
                        ctx = int(item.get("context_length") or 0)
                        seen[key] = (ctx, time.monotonic())
                        return ctx
                # 진단용: 물어봤는데 안 보였을 때 무엇이 보였나(계측기 `ctx_choice` 에 실린다).
                self.__dict__["_resident_error"] = "not_listed: " + ",".join(
                    f"{item.get('name') or item.get('model')}@{item.get('context_length')}" for item in listed
                )[:160]
                # ★ 요청이 끝나는 찰나 `/api/ps` 가 **빈 목록**을 준다(2026-09-28 14:38:50 실측 — 러너는 떠 있었고 1초 뒤 교체됐다).
                #   방금 본 러너가 있으면 그 크기를 쓴다. 정말 내려갔어도 그 크기로 다시 올리니 남의 조건을 안 바꾼다.
                remembered = seen.get(key)
                if remembered and time.monotonic() - remembered[1] <= self._RESIDENT_MEMORY_SEC:
                    return remembered[0]
        except Exception as exc:  # noqa: BLE001 — 못 물어봤다: 최근 관측이 있으면 그것을 믿는다
            self.__dict__["_resident_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            remembered = seen.get(key)
            if remembered and time.monotonic() - remembered[1] <= self._RESIDENT_MEMORY_SEC:
                return remembered[0]
            return 0
        return 0

    # ── 고정 앞부분 데워 두기 (2026-10-10) ─────────────────────────────────────────────────
    #
    # 대표: 「뒤죽박죽으로 시간이 오래 걸린다 — 원인을 정확히 진단해 보자」. Ollama 기록의 호출별 읽기·쓰기를 사흘치 세어 보니
    # 큰 일의 첫 걸음이 **앞부분을 처음부터 다시 읽는 데** 21~27초를 쓰고 있었다(2만~2만 6천 토큰 · 초당 약 950토큰).
    # 큰 호출이 앞부분의 90% 이상을 다시 읽은 비율: 바로 앞이 같은 일의 걸음이면 2~4%, 작은 호출(기억 정리·분류·화면 글자 읽기)이면
    # 38~54%, 모델을 다시 올린 직후면 매번.
    #
    # 서버(llama-server)는 최근 대화 몇 개의 상태를 메모리에 따로 들고 있다가 새 요청과 가장 많이 겹치는 것을 되살린다. 다만
    # **저장점이 찍힌 자리로만** 되돌릴 수 있고, 저장점은 대화를 처음 읽을 때 끝쪽 메시지의 시작에만 찍힌다. 이어 가던 대화의
    # 저장점은 전부 뒤쪽에 있으니, 새 일이 들어오면 겹치는 앞부분(도구 목록 + 고정 지침)은 같아도 되돌아갈 자리가 없어 처음부터 읽는다.
    #
    # 그래서 그 앞부분만 든 짧은 요청을 **앱을 켠 뒤 한 번** 읽혀 둔다. 그러면 「앞부분의 끝」에 저장점이 찍힌 상태가 서버에 남고,
    # 첫 일은 거기서 이어 읽는다. 잰 값(이 PC · 27B · 128K · 모델을 막 올린 뒤 같은 짧은 일 세 판씩): 일 전체 28.9·28.2·28.7초 →
    # 11.6초대, 첫 걸음이 읽는 양 19,761토큰(19.7초) → 328토큰(1.1초).
    #
    # ★ **켠 뒤 한 번만이다. 일이 끝날 때마다 하지 않는다** — 처음엔 그렇게 만들었다가 재 보고 뺐다. 데우는 요청은 서버에 살아 있는
    #   대화와 앞부분이 같아서, 서버는 그 대화를 꺼내 앞부분까지 잘라 낸다(뒤쪽 저장점을 지운다). 지난 사흘 기록에서 일과 일 사이를
    #   건넌 첫 걸음 428번 가운데 266번은 대화가 살아 있어 거의 안 읽었다 — 매번 데웠다면 그 266번을 다시 읽게 만들어, 통째로 읽던
    #   90번에서 번 것(약 1,800초)보다 훨씬 많이 잃는다(어림 약 5,800초). 대화가 사라지는 진짜 까닭은 서버 보관함의 크기다
    #   (한도 8GB · 대화 하나 평균 2.4GB · 사흘에 439번 밀려남) — 그쪽은 서버 설정이라 따로 재고 고친다.
    #   켠 직후에는 지울 대화가 없다(모델을 올리면 보관함이 빈다). 그래서 이때만 순수한 이득이다.
    #
    # 지키는 것:
    #   - 진짜 요청이 오면 데우던 것을 끊고 비켜 준다(`_front_seen` 이 요청마다 `cancel_front_prime` 을 부른다).
    #   - 우리 모델이 그 창 그대로 올라가 있을 때만. 모델을 올리지도, 창을 갈아 끼우지도, 남의 모델을 밀어내지도 않는다.
    #   - 기억하는 것은 실제로 나간 요청의 앞부분 그대로다 — 따로 조립하지 않는다(조립한 것은 한 글자만 달라도 소용없다).
    #   - `front_prime_enabled` 로 끈다. 한 일은 `data/front_primes.jsonl` 에 남는다(읽은 토큰 · 걸린 시간 · 끊겼는가).

    #: 도구가 이보다 적은 요청은 앞부분이 짧다(가벼운 대화·곁가지) — 데워 둘 값이 없다.
    FRONT_MIN_TOOLS = 20
    FRONT_FILE = "front_prime.json"
    #: 마지막 요청 뒤 이만큼 조용해야 데운다 — 일 사이의 곁가지 호출이 끝나기를 기다린다.
    FRONT_QUIET_SEC = 4.0
    #: 못 데웠을 때(모델이 안 올라가 있음 등) 다시 볼 때까지.
    FRONT_RETRY_SEC = 45.0

    def _front_path(self) -> Path:
        return Path(self.config.data_dir) / self.FRONT_FILE

    def _front_or_load(self) -> dict[str, Any] | None:
        front = self.__dict__.get("_front")
        if front is None and not self.__dict__.get("_front_loaded"):
            self.__dict__["_front_loaded"] = True
            try:
                loaded = json.loads(self._front_path().read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("model") and loaded.get("tools") and loaded.get("system"):
                    front = self.__dict__["_front"] = loaded
            except (OSError, ValueError):
                front = None
        return front

    # ── 노는 시간 일(서기 · 2026-10-21) ──────────────────────────────────────────
    def background_chat(self, system: str, user: str, *, model: str, options: dict[str, Any],
                        rewarm: bool = True) -> str | None:
        """손자리가 놀 때만 하는 짧은 부르기(`scribe`). **사람 일이 오면 끊긴다**(`_front_seen` → `cancel_background`). 끊기면 None.

        ★ 2026-10-21 새벽 실측: 서기 실험이 같은 모델에 1만 7천 토큰을 밀어 넣는 동안 대표 판의 부르기가 첫 글자까지 15.8초를
          기다렸다(모델 서버는 한 번에 하나). 그래서 노는 시간 일은 **사람 요청이 오는 순간 끊기는** 문으로만 보낸다 — 앞부분 데우기와 같은 문.
        끝나면 본 지시문을 다시 데우게 표시한다(`_front_dirty`) — 서기가 캐시를 밀었어도 다음 사람 질문의 첫 글자가 늦지 않게.
        """
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False, "think": False, "format": "json", "options": dict(options),
                "keep_alive": self.config.ollama_keep_alive}
        self._make_room_for(model)
        client = httpx.Client(verify=shared_verify(), timeout=httpx.Timeout(600.0, connect=5.0))
        self.__dict__["_background_cancelled"] = False
        self.__dict__["_background_client"] = client
        try:
            response = client.post(f"{self.config.ollama_base_url}/api/chat", json=body)
            response.raise_for_status()
            if self.__dict__.get("_background_cancelled"):
                return None
            return str((response.json().get("message") or {}).get("content") or "")
        except Exception:  # noqa: BLE001 — 끊긴 것도 결과다(사람 일이 왔다)
            return None
        finally:
            self.__dict__["_background_client"] = None
            # 사실 뽑기처럼 짧은 부르기는 다시 데우지 않는다(`rewarm=False`) — 데우기는 「켠 뒤 한 번만」이 잰 결론이다(위 ★).
            if rewarm:
                self.__dict__["_front_dirty"] = True
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def cancel_background(self) -> bool:
        """노는 시간 일이 나가 있으면 끊는다. 끊었으면 True."""
        client = self.__dict__.get("_background_client")
        if client is None:
            return False
        self.__dict__["_background_cancelled"] = True
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    def _front_seen(self, body: dict[str, Any]) -> None:
        """모델에 요청을 보내기 직전에 한 번. 데우는 중이면 비켜 주고, 큰 일의 요청이면 그 앞부분을 기억한다."""
        try:
            self.cancel_front_prime()
            self.cancel_background()
            self.__dict__["_last_send_at"] = time.monotonic()
            tools = body.get("tools") or []
            messages = body.get("messages") or []
            first = messages[0] if messages and isinstance(messages[0], dict) else {}
            if len(tools) < self.FRONT_MIN_TOOLS or str(first.get("role") or "") != "system":
                return
            # 큰 일이 이제 제 앞부분을 직접 읽는다 — 그 대화가 서버에 생기니 따로 데울 일이 없다(데우면 그 대화를 지운다).
            self.__dict__["_front_dirty"] = False
            import hashlib

            options = {k: v for k, v in dict(body.get("options") or {}).items() if k != "num_predict"}
            front = {"model": str(body.get("model") or ""), "tools": tools, "system": dict(first),
                     "think": body.get("think"), "options": options}
            front["key"] = hashlib.sha1(json.dumps(
                [front["model"], tools, front["system"], front["think"], options.get("num_ctx")],
                ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
            current = self._front_or_load()
            if current and current.get("key") == front["key"]:
                return
            self.__dict__["_front"] = front
            path = self._front_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(json.dumps(front, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except Exception:  # noqa: BLE001 — 데워 두기는 덤이다. 이것 때문에 요청이 죽으면 안 된다
            pass

    def cancel_front_prime(self) -> bool:
        """데우는 요청이 나가 있으면 끊는다. 끊었으면 True."""
        client = self.__dict__.get("_prime_client")
        if client is None:
            return False
        self.__dict__["_prime_cancelled"] = True
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    def front_prime_due(self) -> bool:
        """지금 데울 차례인가 — 켜져 있고, 기억한 앞부분이 있고, **켠 뒤 아직 큰 일도 데우기도 없었고**, 잠깐 조용했다."""
        if not getattr(self.config, "front_prime_enabled", False):
            return False
        if self.__dict__.get("_prime_client") is not None:
            return False
        now = time.monotonic()
        # 켠 뒤 한 번만(머리말의 ★). 작은 호출이 지나갔다고 다시 하지 않는다 — 살아 있는 대화를 지운다.
        if not self.__dict__.get("_front_dirty", True):
            return False
        if now < self.__dict__.get("_front_retry_at", 0.0):
            return False
        if now - self.__dict__.get("_last_send_at", 0.0) < self.FRONT_QUIET_SEC:
            return False
        return self._front_or_load() is not None

    def _front_resident_ctx(self, model: str) -> int:
        """이 모델이 **지금** 올라가 있으면 그 창, 아니면 0. 여기서는 「모른다」를 「없다」로 읽는다 — 데우려고 모델을 올리지 않는다."""
        try:
            with httpx.Client(verify=shared_verify(), timeout=3.0) as client:
                response = client.get(f"{self.config.ollama_base_url}/api/ps")
                response.raise_for_status()
                for item in response.json().get("models", []):
                    if self._same_model(item.get("name") or item.get("model"), model):
                        return int(item.get("context_length") or 0)
        except Exception:  # noqa: BLE001
            return 0
        return 0

    def prime_front(self, reason: str = "idle") -> dict[str, Any]:
        """기억해 둔 앞부분만 든 짧은 요청을 한 번 읽힌다. 한 일을 돌려주고 `data/front_primes.jsonl` 에 남긴다."""
        front = self._front_or_load()
        if not front:
            return {"ok": False, "skipped": "no_front"}
        model = str(front.get("model") or "")
        options = dict(front.get("options") or {})
        resident = self._front_resident_ctx(model)
        wanted = int(options.get("num_ctx") or 0)
        if not resident or (wanted and resident != wanted):
            self.__dict__["_front_retry_at"] = time.monotonic() + self.FRONT_RETRY_SEC
            return {"ok": False, "skipped": "not_resident" if not resident else "window_differs", "resident_ctx": resident}
        body = {
            "model": model,
            "messages": [dict(front["system"]), {"role": "user", "content": "."}],
            "tools": front["tools"],
            "stream": False,
            "think": front.get("think", False),
            "keep_alive": self.config.ollama_keep_alive,
            "options": {**options, "num_predict": 1},
        }
        client = httpx.Client(verify=shared_verify(), timeout=httpx.Timeout(300.0, connect=5.0))
        self.__dict__["_prime_cancelled"] = False
        self.__dict__["_prime_client"] = client
        started = time.monotonic()
        row: dict[str, Any] = {"reason": reason, "tools": len(front["tools"]), "num_ctx": wanted or resident}
        try:
            response = client.post(f"{self.config.ollama_base_url}/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
            if self.__dict__.get("_prime_cancelled"):
                raise RuntimeError("cancelled")
            self.__dict__["_front_dirty"] = False
            self.__dict__["_last_ok_at"] = time.time()
            row.update({
                "ok": True,
                "prompt_tokens": int(payload.get("prompt_eval_count") or 0),
                "read_ms": round(float(payload.get("prompt_eval_duration") or 0) / 1_000_000, 1),
                "load_ms": round(float(payload.get("load_duration") or 0) / 1_000_000, 1),
            })
        except Exception as exc:  # noqa: BLE001 — 끊긴 것도 결과다
            cancelled = bool(self.__dict__.get("_prime_cancelled"))
            row.update({"ok": False, "cancelled": cancelled, "error": "" if cancelled else str(exc)[:160]})
            if not cancelled:
                self.__dict__["_front_retry_at"] = time.monotonic() + self.FRONT_RETRY_SEC
        finally:
            self.__dict__["_prime_client"] = None
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        row["total_ms"] = round((time.monotonic() - started) * 1000, 1)
        self.__dict__["_front_last"] = dict(row)
        try:
            path = Path(self.config.data_dir) / "front_primes.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **row}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        return row

    def _options(
        self,
        temperature: float,
        *,
        model: str,
        role: str = "chat",
        inference_profile: str = "default",
        force_preferred: bool = False,
    ) -> dict[str, Any]:
        role = self._effective_role(role, model)
        preferred = self.config.num_ctx_for(role)
        num_ctx = preferred
        resident = 0
        if not force_preferred:
            resident = self._resident_context(model)
            minimum = max(4096, int(self.config.ollama_min_num_ctx))
            if minimum <= resident <= preferred:
                num_ctx = resident
        # 왜 이 크기로 골랐는지 남긴다 — 옵션이 바뀐 기록(`prefix_breaks`)에 같이 실린다(2026-09-28 재기동 직후 첫 판 128K 재현).
        self._last_ctx_choice = {"role": role, "model": model, "preferred": preferred, "resident": resident,
                                 "forced": force_preferred, "chosen": num_ctx,
                                 **({"resident_error": self.__dict__.pop("_resident_error")} if "_resident_error" in self.__dict__ else {})}
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_ctx": num_ctx,
            # ★ 간체 섞임 완화 (2026-09-23, 사장님 실사용 보고 + 조사).
            #   Qwen 계열은 중국어·영어 위주 학습이라 드물게 낮은 확률의 한자 토큰이
            #   섞인다. min_p 는 그 "최고 확률 토큰의 1% 도 안 되는" 꼬리를 잘라내는데,
            #   공식 권장값은 이 꼬리를 안 자르는 0.0 이다(아래 code 역할 참고). 커뮤니티
            #   보고(QwQ-32B-Preview 토론)로는 0.01 이 코딩 품질은 거의 안 건드리면서
            #   그 꼬리에서 튀는 간체 토큰을 줄인다 — 정량 실측은 아직 없다(하한이 아니라
            #   완화 조치). 역할 공통 기본값이고, code 역할이 필요하면 아래서 덮어쓴다.
            "min_p": 0.01,
        }
        if role == "code":
            # Qwen3.8 공식 권장 샘플링을 역할 호출부에서 명시한다. Modelfile 기본값에
            # 기대면 다른 태그/런타임으로 바꾼 순간 조용히 0.1로 회귀한다.
            #
            # ★ min_p 만은 공식 권장(0.0)을 안 따른다 — 위 주석 참고. presence_penalty 는
            #   Qwen3 공식 문서가 "올리면 언어 섞임이 늘 수 있다"고 적어 둔 값이라 0.0 그대로 둔다
            #   (https://github.com/QwenLM/Qwen3/discussions/1744).
            if inference_profile == "fast":
                options.update(
                    {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.01}
                )
            else:
                options.update(
                    {
                        "temperature": 1.0,
                        "top_p": 0.95,
                        "top_k": 20,
                        "min_p": 0.01,
                        "presence_penalty": 0.0,
                        "repeat_penalty": 1.0,
                    }
                )
        # 한 번의 호출이 끝없이 흐르지 않게. 상한이 없으면 스트리밍이 read 타임아웃을
        # 계속 리셋해서 180초 설정이 아무 일도 안 한다(실측: 31분).
        cap = int(getattr(self.config, "ollama_max_predict", 0) or 0)
        if cap > 0:
            options["num_predict"] = cap
        return options

    @staticmethod
    def _inference_contract(*, role: str, profile: str, think: bool) -> dict[str, Any]:
        if role != "code":
            return {}
        normalized = "medium" if profile == "balanced" else profile
        effort = {"fast": "low", "medium": "medium", "deep": "high"}.get(
            normalized, "medium"
        )
        return {
            "reasoning_effort": effort,
            "preserve_thinking": bool(think and normalized in {"medium", "deep"}),
        }

    @staticmethod
    def _inference_observation(
        *,
        requested: dict[str, Any],
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
        thinking_chars: int,
    ) -> dict[str, Any]:
        acknowledged: dict[str, Any] = {}
        response_message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        for key, expected in requested.items():
            if key in payload:
                acknowledged[key] = payload.get(key) == expected
            elif key in response_message:
                acknowledged[key] = response_message.get(key) == expected
            else:
                acknowledged[key] = None
        timing = {
            key: payload.get(key)
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            )
            if payload.get(key) is not None
        }
        eval_count = int(timing.get("eval_count") or 0)
        eval_duration = int(timing.get("eval_duration") or 0)
        if eval_count and eval_duration:
            timing["eval_tokens_per_sec"] = round(eval_count / (eval_duration / 1_000_000_000), 3)
        return {
            # 어느 모델이 실제로 답했는지는 눈금의 라벨이 아니라 서버가 돌려준
            # 값이어야 한다. 이 한 줄이 없어서 "Qwen으로 쟀다"가 증거 없는
            # 주장이었다 — 이 저장소는 그 사고를 이미 두 번 겪었다.
            "model": payload.get("model") or "",
            "requested": requested,
            "request_sent": bool(requested),
            "response_acknowledged": acknowledged,
            "thinking_history_messages_sent": sum(
                1 for item in messages if item.get("role") == "assistant" and item.get("thinking")
            ),
            "thinking_chars_received": thinking_chars,
            "telemetry": timing,
            "note": (
                "null acknowledgement means Ollama accepted the request but did not echo proof of application"
                if requested and any(value is None for value in acknowledged.values())
                else ""
            ),
        }

    def warmup(self, *, model: str | None = None, role: str = "chat") -> dict[str, Any]:
        """Load the configured model without generating a user-visible response."""
        selected = self._selected_model(model, role=role)
        # ★ **이미 뭔가 올라가 있으면 데우지 않는다** (2026-09-28 헤르메스 대결). 예열은 첫 답을 빠르게 하려는 선택일 뿐인데,
        #   `force_preferred` 로 설정값(128K)을 밀어 넣어 다른 앱(헤르메스)이 쓰던 32K 러너를 백엔드 재기동마다 빼앗았다
        #   (적재 기록 13:02 세 번 · 13:29 · 13:37). 요청은 이미 상주 러너에 맞춘다(`_resident_context`) — 예열만 그 원칙을 안 지켰다.
        #   못 물어보면 예전처럼 데운다.
        resident = self._resident_names()
        if resident:
            return {"ok": True, "model": selected, "skipped": "resident", "resident": resident,
                    "keep_alive": self.config.ollama_keep_alive, "load_ms": 0.0, "total_ms": 0.0}
        # ★ 데우는 것도 **올리는 것**이다 (2026-09-20). 여기가 빠져 있어서, 다른 모델이 카드를
        #   쥐고 있는 채로 우리 모델을 올리면 둘이 같이 올라가거나 적재가 통째로 멎었다.
        self._make_room_for(selected)
        body = {
            "model": selected,
            "prompt": "Sonjari warmup.",
            "stream": False,
            "keep_alive": self.config.ollama_keep_alive,
            "options": {
                **self._options(0.0, model=selected, role=role, force_preferred=True),
                "num_predict": 1,
            },
        }
        with httpx.Client(verify=shared_verify(), timeout=self.config.timeout_for(self._effective_role(role))) as client:
            response = client.post(f"{self.config.ollama_base_url}/api/generate", json=body)
            response.raise_for_status()
            payload = response.json()
        return {
            "ok": True,
            "model": selected,
            "keep_alive": self.config.ollama_keep_alive,
            "load_ms": round(float(payload.get("load_duration") or 0) / 1_000_000, 1),
            "total_ms": round(float(payload.get("total_duration") or 0) / 1_000_000, 1),
        }

    def chat_message(
        self,
        prompt: str,
        *,
        system: str = "",
        history: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        think: bool = False,
        num_predict: int | None = None,
        model: str | None = None,
        role: str = "chat",
    ) -> dict[str, Any]:
        selected = self._selected_model(model, role=role)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in history or []:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if role in {"system", "user", "assistant", "tool"} and content:
                messages.append({"role": role, "content": content})
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user["images"] = images
        messages.append(user)
        options = self._options(temperature, model=selected, role=role)
        if num_predict is not None:
            # 짧게 끝나야 하는 답에 상한을 건다. 길게 두면 작은 모델은 같은 말을
            # 반복하며 무너진다(2026-08-11 비전 판정에서 실제로 그랬다).
            options["num_predict"] = max(1, int(num_predict))
        body = {
            "model": selected,
            "messages": messages,
            "stream": False,
            "options": options,
            "think": think,
            "keep_alive": self.config.ollama_keep_alive,
        }
        if tools:
            body["tools"] = tools
        # 다른 모델이 자리를 잡고 있으면 먼저 내린다 — Ollama 는 스스로 안 한다.
        self._make_room_for(selected)
        with httpx.Client(verify=shared_verify(), 
            timeout=httpx.Timeout(
                self.config.timeout_for(self._effective_role(role)),
                connect=10.0,
                read=float(self.config.ollama_stall_timeout_sec),
            )
        ) as client:
            response = self._post_chat(client, body)
            response.raise_for_status()
            payload = response.json()
        message = dict(payload.get("message") or {})
        message["content"] = str(message.get("content") or "").strip()
        return message

    def chat_message_stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        think: bool = False,
        on_chunk: Callable[[dict[str, Any]], None] | None = None,
        model: str | None = None,
        role: str = "chat",
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in history or []:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if role in {"system", "user", "assistant", "tool"} and content:
                messages.append({"role": role, "content": content})
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user["images"] = images
        messages.append(user)
        return self.chat_messages_stream(
            messages,
            tools=tools,
            temperature=temperature,
            think=think,
            on_chunk=on_chunk,
            model=model,
            role=role,
        )

    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        think: bool = False,
        model: str | None = None,
        role: str = "chat",
        inference_profile: str = "default",
    ) -> dict[str, Any]:
        """Send an agent transcript without stripping tool-call metadata."""
        selected = self._selected_model(model, role=role)
        contract = self._inference_contract(
            role=role, profile=inference_profile, think=think
        )
        body: dict[str, Any] = {
            "model": selected,
            "messages": messages,
            "stream": False,
            "options": self._options(
                temperature,
                model=selected,
                role=role,
                inference_profile=inference_profile,
            ),
            "think": self._think_value(selected, role=role, profile=inference_profile, think=think),
            "keep_alive": self.config.ollama_keep_alive,
        }
        body.update(contract)
        if tools:
            body["tools"] = tools
        # 다른 모델이 자리를 잡고 있으면 먼저 내린다 — Ollama 는 스스로 안 한다.
        self._make_room_for(selected)
        with httpx.Client(verify=shared_verify(), 
            timeout=httpx.Timeout(
                self.config.timeout_for(self._effective_role(role)),
                connect=10.0,
                read=float(self.config.ollama_stall_timeout_sec),
            )
        ) as client:
            response = self._post_chat(client, body)
            response.raise_for_status()
            payload = response.json()
        self._note_reload(body, payload)
        message = dict(payload.get("message") or {})
        message["content"] = str(message.get("content") or "").strip()
        message["_inference"] = self._inference_observation(
            requested=contract,
            payload=payload,
            messages=messages,
            thinking_chars=len(str(message.get("thinking") or "")),
        )
        return message

    def chat_messages_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        think: bool = False,
        on_chunk: Callable[[dict[str, Any]], None] | None = None,
        model: str | None = None,
        role: str = "chat",
        inference_profile: str = "default",
        thinking_char_budget: int | None = None,
        after_budget: bool = False,
    ) -> dict[str, Any]:
        """Stream thinking/content/tool calls and return one accumulated message.

        ## 사고 예산 (2026-09-18 실측)

        로컬 엔진에는 「사고 예산」이 없다. 그래서 어떤 턴은 `num_predict` 를 **전부 사고에 쓰고**
        답을 못 낸다 — 한 턴 85초, 한 판(316초)에서 그런 턴 둘이 168초를 먹었다.

        `think` 를 `low`/`medium` 으로 낮춰 봤지만 우리 모델에서는 차이가 없었다
        (3,193자 → 2,740자, 시간 17.5 → 14.1초 · 같은 프롬프트 실측). 그래서 **우리가 끊는다.**

        끊는 방식은 Qwen 공식 우회법과 같은 모양이다 — 흐름을 닫고, **지금까지 한 생각을 들려주며**
        「더 생각하지 말고 지금 답하라」로 한 번 더 부른다. 앞 대화가 그대로라 맥락 캐시가 들어
        두 번째 프리필은 싸다(실측 20K 토큰이 0.5~1.4초).
        """
        selected = self._selected_model(model, role=role)
        contract = self._inference_contract(
            role=role, profile=inference_profile, think=think
        )
        body: dict[str, Any] = {
            "model": selected,
            "messages": messages,
            "stream": True,
            "options": self._options(
                temperature,
                model=selected,
                role=role,
                inference_profile=inference_profile,
            ),
            "think": self._think_value(selected, role=role, profile=inference_profile, think=think),
            "keep_alive": self.config.ollama_keep_alive,
        }
        body.update(contract)
        if tools:
            body["tools"] = tools
        if selected in _SYSTEM_FIRST_ONLY and isinstance(body.get("messages"), list):
            body["messages"] = fold_late_system_messages(body["messages"])
        self._note_prefix_break(body)
        thinking_parts: list[str] = []
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        final_payload: dict[str, Any] = {}
        budget = int(
            self._thinking_budget_for(selected)
            if thinking_char_budget is None
            else thinking_char_budget
        )
        # 생각을 안 하는 호출에는 걸 것이 없다.
        budget = budget if (budget > 0 and think) else 0
        thinking_chars = 0
        repeat_hit = False
        repeat_checked_at = 0
        content_chars = 0
        content_checked_at = 0
        content_loop = False
        content_chunks = 0
        content_started = 0.0
        window_started = 0.0
        base_rate = 0.0
        last_rate = 0.0
        slow_hits = 0
        slow_content = False
        budget_hit = False
        # ★ 굳은 요청을 끊는다 (2026-08-31).
        #
        # 예전에는 `timeout=<판 예산>` 하나였다. httpx 에서 그 값은 **소켓 읽기마다**
        # 걸리는 값이라, Ollama 가 응답을 시작조차 안 하면 code 판은 900초를 기다렸다.
        # 실측으로 그 상태를 잡았다 — 3090 0% · 슬롯 idle · 모델 상주인데
        # `_receive_response_headers` 에서 스택이 굳어 있었다.
        #
        # 스트리밍이라 **생성이 시작되면 토큰은 연속으로 온다.** 그래서 조각 사이가
        # `ollama_stall_timeout_sec` 만큼 벌어지면 그건 느린 게 아니라 고장이다.
        # 연결은 10초면 충분하다(같은 기계다).
        timeout = httpx.Timeout(
            self.config.timeout_for(self._effective_role(role)),
            connect=10.0,
            read=float(self.config.ollama_stall_timeout_sec),
        )
        self._front_seen(body)
        # 다른 모델이 자리를 잡고 있으면 먼저 내린다. Ollama 가 스스로는 안 한다.
        self._make_room_for(selected)
        # 스트리밍도 같은 404 를 맞는다. 흐름을 열기 **전에** 한 번 갈라 둔다 —
        # 열고 나서 되돌리려면 이미 읽기 시작한 뒤라 지저분해진다(`_post_chat` 주석).
        self._wait_out_transient_404(body)
        started = time.monotonic()
        first_byte = 0.0
        first_token = 0.0  # 첫 생각 · 글 · 도구 조각이 실제로 들어온 때(`_log_call`)
        # ★ **스트리밍에도 404 재시도를 단다** (2026-09-11).
        #
        #   `_post_chat`(비스트리밍)에만 재시도가 있었다. 그런데 실제 판이 타는 길은
        #   이쪽이다 — 한 판이 큐에서 238초 기다린 끝에 **4.7초 만에 걸음 0 으로**
        #   죽었고 고장은 `404 Not Found for /api/chat` 하나뿐이었다. 그때도 모델은
        #   `/api/ps` 에 15.5GB 로 올라와 있었다. 최근 기록에 같은 죽음이 네 번 더 있다.
        #
        #   앞의 `_wait_out_transient_404` 는 우리 모델이 이미 올라와 있으면 곧장
        #   간다. 그 자리는 **교체 창**만 보는 것이라 그게 맞다. 하지만 그 뒤에도
        #   404 는 났다 — 그러니 흐름을 열다 맞으면 **거기서 한 번 더 물어본다.**
        #
        #   되돌리기가 안전한 이유: 상태 검사는 헤더 직후, **한 조각도 읽기 전**이다.
        #   `on_chunk` 로 내보낸 것이 아직 없으므로 화면에 두 번 그려질 일이 없다.
        #   그래도 모아 둔 것을 비우고 다시 시작한다 — 「아직 없을 것이다」에 기대지
        #   않는다.
        runner_retried = False
        for _attempt in range(_STREAM_404_RETRIES + 1):
            try:
                with httpx.Client(verify=shared_verify(), timeout=timeout) as client:
                    with client.stream(
                        "POST", f"{self.config.ollama_base_url}/api/chat", json=body
                    ) as response:
                        # 헤더가 왔다 = 생성이 시작됐다. 이 지연이 프리필 비용이고,
                        # 상한을 다시 정할 땐 감이 아니라 이 값의 분포를 보고 정한다.
                        first_byte = time.monotonic() - started
                        if response.status_code < 400:
                            self.__dict__["_last_ok_at"] = time.time()  # 생성이 시작됐다 = 모델이 살아 있다
                        if response.status_code >= 400:
                            # ★ **본문을 읽고 나서 판단한다** (2026-09-11).
                            #
                            #   전에는 상태 코드만 보고 재시도했다. 그런데 재시도를 붙인 뒤에도
                            #   같은 404 로 판이 죽었고(2회), 무엇이 없다는 것인지 모르는 채로
                            #   추측만 늘었다. Ollama 는 404 에 `{"error":"model 'x' not found"}`
                            #   같은 본문을 실어 준다 — 그걸 버리고 있었다.
                            #
                            #   흐름을 아직 안 읽었으므로 여기서 본문을 읽어도 된다.
                            detail = ""
                            full_text = ""
                            try:
                                response.read()
                                full_text = response.text
                                detail = full_text[:300]
                            except Exception:  # noqa: BLE001
                                detail = ""
                            if (
                                response.status_code == 404
                                and _attempt < _STREAM_404_RETRIES
                                and self._model_is_installed(str(body.get("model") or ""))
                            ):
                                raise _Transient404(detail)
                            # ★ 실행기가 꺼진 것이 먼저다 — 그 글에는 옛 오류가 같이 실려 와서, 아래 검사들이 엉뚱한 이름을 붙인다.
                            if runner_stopped(full_text):
                                if not runner_retried and _attempt < _STREAM_404_RETRIES:
                                    raise _RunnerStopped(detail)
                                raise RuntimeError(
                                    f"model_runner_stopped: 모델 실행기가 두 번 꺼졌습니다(메모리가 모자랐을 수 있습니다) "
                                    f"(model={body.get('model')})"
                                )
                            # ★ 표시는 **자르기 전** 본문에서 찾는다 (2026-10-02 대표 운영 판). 300자로 자른
                            #   본문에서는 문구가 「Jinja Exception: System 」에서 끊겨 접기가 안 걸렸다 —
                            #   첫 호출이 스트림인 판(코워크 조사)만 매번 500 으로 죽었다.
                            if (
                                _SYSTEM_FIRST_MARK in full_text
                                and str(body.get("model") or "") not in _SYSTEM_FIRST_ONLY
                                and isinstance(body.get("messages"), list)
                            ):
                                _SYSTEM_FIRST_ONLY.add(str(body.get("model") or ""))
                                body["messages"] = fold_late_system_messages(body["messages"])
                                raise _FoldSystemRetry(detail)
                            if detail:
                                raise RuntimeError(
                                    f"ollama_{response.status_code}: {detail} "
                                    f"(model={body.get('model')})"
                                )
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not line:
                                continue
                            payload = json.loads(line)
                            chunk = dict(payload.get("message") or {})
                            thinking = str(chunk.get("thinking") or "")
                            content = str(chunk.get("content") or "")
                            calls = [dict(item) for item in chunk.get("tool_calls") or []]
                            if not first_token and (thinking or content or calls):
                                first_token = time.monotonic() - started
                            if thinking:
                                thinking_parts.append(thinking)
                                thinking_chars += len(thinking)
                                if (
                                    not repeat_hit
                                    and thinking_chars - repeat_checked_at >= _REPEAT_CHECK_EVERY
                                    and not content_parts
                                    and not tool_calls
                                ):
                                    repeat_checked_at = thinking_chars
                                    repeat_hit = thinking_is_looping("".join(thinking_parts))
                            if content:
                                content_parts.append(content)
                                content_chars += len(content)
                                if (
                                    not tool_calls
                                    and content_chars - content_checked_at >= _REPEAT_CHECK_EVERY
                                ):
                                    content_checked_at = content_chars
                                    so_far = "".join(content_parts)
                                    content_loop = content_is_looping(so_far) or content_is_stuttering(so_far)
                                content_chunks += 1
                                if content_chunks == 1:
                                    content_started = window_started = _clock()
                                elif content_chunks % _SLOW_CONTENT_WINDOW == 0:
                                    ticked = _clock()
                                    span = ticked - window_started
                                    window_started = ticked
                                    last_rate = _SLOW_CONTENT_WINDOW / span if span >= _SLOW_CONTENT_MIN_SPAN else 0.0
                                    if content_chunks == _SLOW_CONTENT_BASE_CHUNKS:
                                        whole = ticked - content_started
                                        if whole >= _SLOW_CONTENT_MIN_SPAN * 3:
                                            base_rate = content_chunks / whole  # 이 스트림의 제 속도
                                    elif (
                                        tools
                                        and not tool_calls
                                        and base_rate > 0.0
                                        and last_rate > 0.0
                                        and content_chunks >= _SLOW_CONTENT_MIN_CHUNKS
                                        and last_rate < base_rate * _SLOW_CONTENT_SHARE
                                    ):
                                        slow_hits += 1
                                        slow_content = slow_hits >= _SLOW_CONTENT_HITS
                                    else:
                                        slow_hits = 0
                            if calls:
                                tool_calls.extend(calls)
                            if on_chunk and (thinking or content or calls or payload.get("done")):
                                on_chunk(
                                    {
                                        "thinking": thinking,
                                        "content": content,
                                        "tool_calls": calls,
                                        "done": bool(payload.get("done")),
                                    }
                                )
                            # ★ 예산을 넘겼으면 **여기서 흐름을 닫는다.** 이미 답이나 도구 호출이
                            #   나오기 시작했으면 건드리지 않는다 — 그 턴은 이미 사고를 끝낸 것이다.
                            if (
                                budget
                                and not budget_hit
                                and thinking_chars > budget
                                and not content_parts
                                and not tool_calls
                            ):
                                budget_hit = True
                                break
                            if repeat_hit:
                                # 같은 문단을 되풀이하기 시작했다 — 예산까지 기다리지 않고 지금 끊는다.
                                budget_hit = True
                                break
                            if slow_content and not calls and not content_loop:
                                # 답 글이 길어지며 속도가 무너졌다 — 여기서 닫고, 아래에서 도구 없이 다시 받는다.
                                break
                            if content_loop and not calls:
                                # ★ 답 글이 되풀이를 쏟아 낸다 (2026-10-04) — 상한까지 80초를 기다리지 않고 닫는다.
                                #   흐름을 닫으면 서버도 생성을 멈춘다. 두 번째 호출은 하지 않는다: 되풀이 앞까지는 멀쩡한 답이다.
                                break
                            if payload.get("done"):
                                final_payload = payload
                                metrics = {
                                    key: payload.get(key)
                                    for key in (
                                        "done_reason",
                                        "total_duration",
                                        "load_duration",
                                        "prompt_eval_count",
                                        "eval_count",
                                    )
                                    if payload.get(key) is not None
                                }
            except _FoldSystemRetry:
                # 아직 한 조각도 안 읽었다(헤더 직후) — 접은 메시지로 곧장 다시 연다.
                thinking_parts.clear()
                content_parts.clear()
                tool_calls.clear()
                started = time.monotonic()
                continue
            except _RunnerStopped:
                # 헤더에서 갈렸으니 읽은 조각이 없다. 그래도 비우고 다시 연다 — Ollama 가 실행기를 다시 올린다.
                runner_retried = True
                self.__dict__["_runner_restarts"] = int(self.__dict__.get("_runner_restarts") or 0) + 1
                thinking_parts.clear()
                content_parts.clear()
                tool_calls.clear()
                time.sleep(_RUNNER_STOPPED_BACKOFF_SEC)
                started = time.monotonic()
                continue
            except _Transient404:
                thinking_parts.clear()
                content_parts.clear()
                tool_calls.clear()
                time.sleep(_STREAM_404_BACKOFF_SEC[
                    min(_attempt, len(_STREAM_404_BACKOFF_SEC) - 1)
                ])
                started = time.monotonic()
                continue
            break
        # Some runtimes may repeat a completed tool call in the final chunk.
        unique_calls: list[dict[str, Any]] = []
        seen: set[str] = set()
        for call in tool_calls:
            fingerprint = json.dumps(call, ensure_ascii=False, sort_keys=True)
            if fingerprint not in seen:
                seen.add(fingerprint)
                unique_calls.append(call)
        if budget_hit or (slow_content and not content_loop and not unique_calls):
            self._log_call(body, final_payload or {}, first_byte, first_token,
                           cut=("repeat" if repeat_hit else "budget") if budget_hit else "slow_content",
                           elapsed=time.monotonic() - started,
                           thinking_chars=len("".join(thinking_parts)), content_chars=len("".join(content_parts)))
        if budget_hit and after_budget:
            # 생각을 켠 채 부른 두 번째 호출마저 예산을 넘겼다 — 예전 방식(생각 끔)으로 한 번 더. 안내는 이미 실려 있다.
            with tagged_call(purpose="budget_fallback"):
                fallback = self.chat_messages_stream(
                    messages, tools=tools, temperature=temperature, think=False, on_chunk=on_chunk,
                    model=model, role=role, inference_profile=inference_profile, thinking_char_budget=0,
                )
            fallback["_fell_back_to_no_thinking"] = True
            return fallback
        if budget_hit:
            with tagged_call(purpose="budget_second"):
                return self._answer_after_thinking_budget(
                    messages,
                    resolved_model=selected,
                    thinking=_drop_repeats("".join(thinking_parts)) if repeat_hit else "".join(thinking_parts),
                    reason="repeat" if repeat_hit else "budget",
                    budget=budget,
                    tools=tools,
                    temperature=temperature,
                    on_chunk=on_chunk,
                    model=model,
                    role=role,
                    inference_profile=inference_profile,
                    first_pass_sec=round(time.monotonic() - started, 2),
                )
        if slow_content and not content_loop and not unique_calls:
            with tagged_call(purpose="slow_again"):
                return self._answer_again_without_tools(
                    messages,
                    partial="".join(content_parts),
                    thinking="".join(thinking_parts),
                    observed={
                        "cut_at_chunks": content_chunks,
                        "base_rate": round(base_rate, 1),
                        "rate": round(last_rate, 1),
                        "tools": len(tools or []),
                        "first_pass_sec": round(time.monotonic() - started, 2),
                    },
                    temperature=temperature,
                    on_chunk=on_chunk,
                    model=model,
                    role=role,
                    inference_profile=inference_profile,
                )
        self._note_reload(body, final_payload or {})
        self._log_call(body, final_payload or {}, first_byte, first_token,
                       thinking_chars=len("".join(thinking_parts)), content_chars=len("".join(content_parts)))
        if content_loop:
            metrics = {**metrics, "done_reason": "content_loop_cut"}
        message: dict[str, Any] = {
            "role": "assistant",
            "thinking": "".join(thinking_parts),
            "content": (
                _cut_content_loop("".join(content_parts)) if content_loop else "".join(content_parts)
            ).strip(),
            "tool_calls": unique_calls,
            "_metrics": metrics,
            # 첫 바이트까지 걸린 시간. 프리필 비용이자, `ollama_stall_timeout_sec`
            # 을 감이 아니라 분포로 다시 정하기 위한 유일한 근거다.
            "_first_byte_sec": round(first_byte, 2),
            "_inference": self._inference_observation(
                requested=contract,
                payload=final_payload,
                messages=messages,
                thinking_chars=len("".join(thinking_parts)),
            ),
        }
        return message

    def _answer_again_without_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        partial: str,
        thinking: str,
        observed: dict[str, Any],
        temperature: float,
        on_chunk: Callable[[dict[str, Any]], None] | None,
        model: str | None,
        role: str,
        inference_profile: str,
    ) -> dict[str, Any]:
        """답 글이 길어지며 느려진 턴을 **도구 목록 없이** 다시 받는다 — 같은 요청, 같은 대화, 목록만 뺀다.

        이어 쓰게 하지 않고 처음부터 다시 받는다: 이음매에서 표의 줄이 겹치거나 빠지는 것보다 30초가 싸다.
        생각은 다시 하지 않는다 — 앞에서 이미 답을 쓰기 시작한 턴이다. 다시 받은 것이 비면 앞에서 받은 데까지를 쓴다.
        """
        second = self.chat_messages_stream(
            messages,
            tools=None,
            temperature=temperature,
            think=False,
            on_chunk=on_chunk,
            model=model,
            role=role,
            inference_profile=inference_profile,
            thinking_char_budget=0,
        )
        answered = str(second.get("content") or "").strip()
        if not answered:
            second["content"] = partial.strip()
        if thinking and not second.get("thinking"):
            second["thinking"] = thinking
        second["tool_calls"] = []  # 목록 없이 부른 턴이다 — 글로 흉내 낸 호출이 섞여도 호출로 치지 않는다
        second["_slow_content"] = {
            "hit": True,
            **observed,
            "partial_chars": len(partial),
            "second_pass": {
                "content_chars": len(answered),
                "eval_count": (second.get("_metrics") or {}).get("eval_count"),
                "used_partial": not answered,
            },
        }
        _note_cut_first_pass(second, float(observed.get("first_pass_sec") or 0.0))
        return second

    #: 두 번째 호출에 들려줄 생각의 **끝부분**. 앞이 아니라 끝인 이유는 모델이 결론에 가까운
    #: 것을 마지막에 적기 때문이다. 너무 길면 두 번째 프리필이 비싸진다.
    _THINKING_SPLICE_CHARS = 2000
    #: 생각을 켠 채 부르는 두 번째 호출의 예산. 「더 생각하지 말라」는 안내를 받고도 이만큼 넘게 생각하면 끈다.
    _SECOND_PASS_THINKING_CHARS = 2000
    #: 생각을 켠 채 두 번째 호출을 부를 것인가. 실제 판 5/5 실패라 꺼 둔다(2026-10-09).
    _KEEP_THINKING_ON_SECOND_PASS = False

    def _answer_after_thinking_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        thinking: str,
        budget: int,
        reason: str = "budget",
        tools: list[dict[str, Any]] | None,
        temperature: float,
        on_chunk: Callable[[dict[str, Any]], None] | None,
        model: str | None,
        role: str,
        inference_profile: str,
        first_pass_sec: float,
        resolved_model: str = "",
    ) -> dict[str, Any]:
        """사고 예산을 넘긴 턴을 **답으로 끝낸다**.

        생각을 버리지 않는다 — 끝부분을 그대로 들려주고 이어서 답하게 한다. 사고는 `thinking` 에
        남겨 장부와 화면이 무엇을 보고 결정했는지 볼 수 있게 한다(생각을 지우면 근거가 사라진다).
        """
        tail = thinking[-self._THINKING_SPLICE_CHARS :]
        nudge = {
            "role": "user",
            "content": (
                ("[같은 생각을 되풀이하기 시작했다 — 거기서 끊었다]\n" if reason == "repeat" else "[생각 시간이 다 됐다]\n")
                + "지금까지 네가 한 생각의 끝부분이다:\n"
                f"{tail}\n\n"
                "더 생각하지 말고 지금 바로 다음 도구를 부르거나 최종 답을 내라."
            ),
        }
        # ★ 틀이 생각 스위치를 앞머리에 그리는 모델은 **생각을 켠 채** 짧은 예산으로 부른다(`think_moves_the_front`).
        #   끄면 프롬프트가 첫 토큰부터 달라져 대화 전체를 다시 읽는다. 그마저 넘기면 예전 방식으로 떨어진다(`after_budget`) —
        #   지금보다 나빠질 수 있는 폭이 이 짧은 예산만큼으로 묶인다. 그 밖의 모델은 예전 그대로 생각을 끈다.
        #   ★ 같은 날: 「보통」 세기를 글자로 실은 판은 앞머리가 생각을 끈 호출과 같다(`steady_think_level`) — 그 판은 예전 방식
        #     (생각 끔)이 싸고 확실하다. 숙제 3 판에서 생각을 켠 채 부른 두 번째 호출은 네 번 모두 또 넘겼다.
        #   ★ 같은 날 05:50: 생각을 켠 채 부르는 두 번째 호출은 **기본으로 끈다**(`_KEEP_THINKING_ON_SECOND_PASS`). 실제 판에서
        #     다섯 번 중 다섯 번이 또 예산을 넘겨 예전 방식으로 떨어졌다(숙제 3 넷 · 사람인 하나) — 시간만 더 썼다. 작은 실험
        #     (생각이 이미 결론에 닿은 경우)에서만 됐다. 장치와 시험은 남긴다.
        front_is_steady = isinstance(self._think_value(resolved_model, role=role, profile=inference_profile, think=True), str)
        keeps_thinking = (
            self._KEEP_THINKING_ON_SECOND_PASS and bool(resolved_model) and not front_is_steady
            and self.think_moves_the_front(resolved_model)
        )
        second = self.chat_messages_stream(
            list(messages) + [nudge],
            tools=tools,
            temperature=temperature,
            think=keeps_thinking,
            on_chunk=on_chunk,
            model=model,
            role=role,
            inference_profile=inference_profile,
            thinking_char_budget=self._SECOND_PASS_THINKING_CHARS if keeps_thinking else 0,
            after_budget=keeps_thinking,
        )
        # ★ 2026-10-03 22시 예약 판(5fa9b74c): 2단째(생각 끔)가 「[생각 시간이 다 됐습니다] …읽어보겠습니다.」 한 문단을 **1만 8천 자**
        #   되풀이했다 — 생각 쪽엔 되풀이 끊기가 있는데 본문 쪽엔 없었다. 같은 문단은 하나로 접고, 우리 안내 표식을 흉내 낸 줄은 지운다.
        if isinstance(second.get("content"), str):
            second["content"] = collapse_repeated_paragraphs(second["content"])
        second_thinking = second.get("thinking") if keeps_thinking else ""
        second["thinking"] = thinking
        second["_thinking_budget"] = {
            "hit": True,
            "reason": reason,
            "budget_chars": budget,
            "thinking_chars": len(thinking),
            "first_pass_sec": first_pass_sec,
            "spliced_chars": len(tail),
            # ★ 2026-09-30: 2단째가 **무엇을 냈는지**. QR 판에서 3.8 이 2단째에 8,027 토큰을 내고 도구 0개로 끝났는데
            #   본문이 어디에도 안 남아 「생각을 본문으로 이어 썼다」를 추정으로만 말했다. 다음엔 숫자로 본다.
            "second_pass": {
                # 생각을 켠 채 불렀나 · 그러고도 넘겨 예전 방식으로 떨어졌나 · 두 번째에 더 한 생각(글자).
                "kept_thinking": keeps_thinking,
                "fell_back": bool(second.get("_fell_back_to_no_thinking")),
                "thinking_chars": len(str(second_thinking or "")),
                "content_chars": len(str(second.get("content") or "")),
                "tool_calls": len(second.get("tool_calls") or []),
                "eval_count": (second.get("_metrics") or {}).get("eval_count"),
                "content_head": str(second.get("content") or "")[:300],
            },
        }
        _note_cut_first_pass(second, first_pass_sec)
        return second

    def chat(
        self,
        prompt: str,
        *,
        system: str = "",
        history: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
        temperature: float = 0.2,
        think: bool = False,
        model: str | None = None,
        role: str = "chat",
    ) -> str:
        message = self.chat_message(
            prompt,
            system=system,
            history=history,
            images=images,
            temperature=temperature,
            think=think,
            model=model,
            role=role,
        )
        return str(message.get("content") or "").strip()
