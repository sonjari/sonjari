"""사고 원문을 화면에서만 한국어로 보여 준다.

## 왜 번역인가 (2026-08-30 실측)

Qwen 은 지시를 읽고도 영어로 생각한다. 세 자리에 넣어 봤고 분포로 쟀다:

    시스템 맨 앞 지시 (5회)      한글  2%   (0% · 1% · 2% · 4%)
    다른 것 없이 한국어 지시만     한글  3%
    사고 채널을 한국어로 prefill  한글 47%

사고 첫 줄이 ``We need answer in Korean. User asks ...`` 였다 — **지시가 안 닿은
것이 아니라, 닿아도 사고 채널이 영어로 굳어 있다.**

유일하게 움직인 prefill 은 매 걸음 가짜 assistant 턴을 끼워야 한다. 그러면 도구
호출 흐름에 남의 턴이 섞이고, 접두사가 매 걸음 바뀌어 캐시가 깨진다(오늘 잰 값으로
걸음마다 재프리필). **절반짜리 한글을 얻자고 도구 흐름과 속도를 내주는 거래다.**

그래서 주 모델은 영어로 생각하게 두고 **화면에만** 한국어를 그린다.

## 규율

- **3060 정찰기**에게 시킨다. 3090 의 주 모델을 건드리지 않는다 — 태그가 갈리면
  서로 축출한다는 것을 이 저장소가 여러 번 겪었다.
- **절대 막지 않는다.** 실패하면 조용히 원문이 그대로 남는다. 사고 번역 때문에
  일이 늦어지면 그건 고장이다.
- 원문은 지우지 않는다. 화면이 둘 다 들고 있다가 사람이 고르게 한다 —
  식별자를 확인하려면 원문이 필요하다.

## 그래픽카드 한 장 PC (2026-09-16, 인수인계 H3)

정찰기가 없는 PC 가 대부분이다. 실시간 번역은 없고(주 모델을 판 중에 건드리지 않는다), 화면은 영어 원문과
「생각은 영어로 나옵니다」를 보여 준다. **판이 끝난 뒤** 사람이 「한국어로 보기」를 누르면 그때 주 모델로
옮긴다(`translate_after`) — 주 모델과 같은 태그·같은 컨텍스트로 부르므로 러너를 새로 띄우지 않는다.
일하는 중이면 거절한다. 같이 올린 작은 번역 모델로 실시간 번역하는 칸은 속도·탑재율 실측 전이라 안 만든다.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import httpx

from .config import JarvisConfig

#: 이만큼 쌓이면 한 덩이로 번역한다. 조각마다 부르면 문장이 토막 나고 호출만 는다.
SEGMENT_CHARS = 400

#: 판 하나에서 번역할 총량. 원문 상한(`agent._THINKING_STREAM_CHARS`)보다 작게 둔다 —
#: 사고가 길어질수록 사람은 끝만 읽는다.
BUDGET_CHARS = 12_000

_PROMPT = (
    "다음은 코딩 에이전트의 사고 기록이다. 한국어로 자연스럽게 옮겨라.\n"
    "규칙: 도구 이름·파일 경로·코드·오류 문자열·식별자는 **원문 그대로** 둔다"
    "(local_apply_edit, path_not_found, agent.py:412 처럼).\n"
    "설명이나 인사를 덧붙이지 말고 번역문만 답하라.\n\n"
)


#: 판 뒤 번역에서 한 번에 넘기는 크기. 주 모델 컨텍스트에 여유 있게 들어가는 만큼.
AFTER_CHUNK_CHARS = 3000


def split_for_translation(text: str, limit: int = AFTER_CHUNK_CHARS) -> list[str]:
    """문단 경계에서 자른다. 문단 하나가 너무 길면 문장 끝에서, 그래도 없으면 글자 수로."""
    chunks: list[str] = []
    current = ""
    for paragraph in (text or "").split("\n\n"):
        piece = paragraph if not current else "\n\n" + paragraph
        if len(current) + len(piece) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current)
        current = paragraph
        while len(current) > limit:
            cut = current.rfind(". ", 0, limit)
            cut = cut + 1 if cut > 0 else limit
            chunks.append(current[:cut])
            current = current[cut:].lstrip()
    if current.strip():
        chunks.append(current)
    return chunks


def translate_after(text: str, ask: Callable[[str], str]) -> str:
    """판이 끝난 사고 원문을 덩이로 나눠 옮긴다. 한 덩이가 실패하면 그 덩이는 원문으로 둔다."""
    out: list[str] = []
    for chunk in split_for_translation(text[:BUDGET_CHARS]):
        try:
            translated = ask(_PROMPT + chunk).strip()
        except Exception:  # noqa: BLE001 — 번역 실패가 화면을 망가뜨리면 안 된다
            translated = ""
        out.append(translated or chunk)
    return "\n\n".join(out)


class ThinkingTranslator:
    """사고 조각을 모아 두었다가 한 덩이씩 번역해 내보낸다."""

    def __init__(
        self,
        config: JarvisConfig,
        publish: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.config = config
        self.publish = publish
        self._lock = threading.Lock()
        self._buffers: dict[str, str] = {}
        self._spent: dict[str, int] = {}
        self._seq: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        # 정찰기가 꺼져 있으면 번역도 없다. 주 모델로 대신하지 않는다.
        return bool(getattr(self.config, "code_scout_enabled", False))

    def feed(self, job_id: str, delta: str) -> None:
        """사고 조각을 받는다. 충분히 모이면 그때 번역을 띄운다."""
        if not (self.enabled and job_id and delta):
            return
        with self._lock:
            if self._spent.get(job_id, 0) >= BUDGET_CHARS:
                return
            buffered = self._buffers.get(job_id, "") + delta
            if len(buffered) < SEGMENT_CHARS:
                self._buffers[job_id] = buffered
                return
            # 문장 끝에서 자른다. 반쪽 문장을 번역하면 다음 덩이와 안 이어진다.
            cut = max(buffered.rfind(". "), buffered.rfind(".\n"), buffered.rfind("\n\n"))
            if cut <= 0:
                cut = len(buffered)
            segment, self._buffers[job_id] = buffered[: cut + 1], buffered[cut + 1 :]
            self._spent[job_id] = self._spent.get(job_id, 0) + len(segment)
            self._seq[job_id] = self._seq.get(job_id, 0) + 1
            seq = self._seq[job_id]
        threading.Thread(
            target=self._translate, args=(job_id, seq, segment), daemon=True
        ).start()

    def finish(self, job_id: str) -> None:
        """판이 끝났다. 남은 조각을 마저 내보내고 자리를 비운다."""
        with self._lock:
            leftover = self._buffers.pop(job_id, "")
            self._spent.pop(job_id, None)
            seq = self._seq.get(job_id, 0) + 1
            if leftover.strip():
                self._seq[job_id] = seq
            else:
                self._seq.pop(job_id, None)
                return
        threading.Thread(
            target=self._translate, args=(job_id, seq, leftover), daemon=True
        ).start()

    def _translate(self, job_id: str, seq: int, segment: str) -> None:
        try:
            text = self._ask(segment)
        except Exception:
            # 조용히 접는다. 원문은 화면에 이미 있다.
            return
        if not text:
            return
        self.publish(
            "agent_thinking_ko",
            {"job_id": job_id, "seq": seq, "delta": text},
        )

    def _ask(self, segment: str) -> str:
        body = {
            "model": self.config.code_scout_model,
            "messages": [{"role": "user", "content": _PROMPT + segment}],
            "stream": False,
            # 정찰기도 thinking 모델일 수 있다. 켜 두면 예산이 내부 추론에 다 쓰이고
            # content 가 빈 문자열로 온다 — 이 저장소가 젬마에서 겪은 함정이다.
            "think": False,
            "keep_alive": self.config.code_scout_keep_alive,
            "options": {
                "num_ctx": max(4096, int(self.config.code_scout_num_ctx)),
                "num_predict": max(256, len(segment)),
                "temperature": 0.1,
            },
        }
        url = f"{self.config.code_scout_base_url.rstrip('/')}/api/chat"
        with httpx.Client(timeout=float(self.config.code_scout_timeout_sec)) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        message = payload.get("message")
        message = message if isinstance(message, dict) else {}
        return str(message.get("content") or "").strip()
