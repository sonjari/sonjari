from __future__ import annotations

import math
import threading
import re
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class DeliveryMode(StrEnum):
    AUTO = "auto"
    VOICE = "voice"
    HYBRID = "hybrid"
    SCREEN = "screen"


@dataclass(slots=True)
class Presentation:
    mode: str
    spoken_text: str
    display_title: str
    display_content: str
    estimated_full_speech_sec: float
    reasons: list[str]
    speech: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PresentationPolicy:
    """Routes conversational output without asking the LLM to control the UI."""

    def __init__(
        self,
        *,
        short_max_chars: int = 90,
        short_max_sentences: int = 2,
        short_max_speech_sec: float = 12.0,
        chars_per_second: float = 5.0,
        hybrid_summary_max_chars: int = 72,
    ) -> None:
        self.short_max_chars = short_max_chars
        self.short_max_sentences = short_max_sentences
        self.short_max_speech_sec = short_max_speech_sec
        self.chars_per_second = chars_per_second
        self.hybrid_summary_max_chars = max(24, hybrid_summary_max_chars)
        self._acknowledgement_index = 0

    @staticmethod
    def _plain_text(markdown: str) -> str:
        text = re.sub(r"```[\s\S]*?```", " ", markdown)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"^[\s>#*+-]+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[*_`~]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _sentence_count(text: str) -> int:
        parts = [part for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if part.strip()]
        return max(1, len(parts)) if text.strip() else 0

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
        return (shortened or text[:limit]).rstrip() + "…"

    @staticmethod
    def _clean_summary_sentence(text: str) -> str:
        text = re.sub(
            r"^(?:\[\s*)?(?:핵심\s*)?(?:결론|요약)(?:\s*\])?(?:은|은요)?\s*[:：-]?\s*",
            "",
            text.strip(),
        )
        return text.strip(" -–—•|[]")

    @staticmethod
    def _is_meta_sentence(text: str) -> bool:
        compact = re.sub(r"\s+", " ", text).strip()
        return bool(
            re.search(r"(?:조사\s*)?결과(?:입니다|예요)[.!?]?$", compact)
            or re.fullmatch(r"(?:답변|결과)(?:입니다|이에요|예요)[.!?]?", compact)
            or compact.startswith(("자세한 내용은", "세부 내용은", "화면에"))
        )

    def _hybrid_summary(self, content: str, *, structured: bool) -> str:
        del structured
        plain = self._plain_text(content)
        raw_sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?。！？])\s+|\n+", plain)
            if part.strip()
        ]
        candidates: list[str] = []
        for raw in raw_sentences:
            cleaned = self._clean_summary_sentence(raw)
            if len(cleaned) < 4 or self._is_meta_sentence(cleaned):
                continue
            candidates.append(cleaned)

        if not candidates:
            fallback = self._clean_summary_sentence(plain)
            return (
                self._truncate(fallback, self.hybrid_summary_max_chars)
                if fallback
                else "확인할 내용이 없습니다."
            )

        # Prefer a complete sentence that fits the speech budget. Selecting a
        # longer "important" sentence and cutting it by character count sounds
        # broken and can leave Korean connective endings unfinished.
        fitting = [
            sentence for sentence in candidates if len(sentence) <= self.hybrid_summary_max_chars
        ]
        pool = fitting or candidates
        preferred = next(
            (
                sentence
                for sentence in pool
                if any(
                    signal in sentence
                    for signal in ("예상", "추천", "확인", "핵심", "가장", "정상", "필요", "가능")
                )
            ),
            pool[0],
        )
        if fitting:
            return preferred
        return self._truncate(preferred, self.hybrid_summary_max_chars)

    def research_acknowledgement(self, query: str) -> str:
        """Return a short, varied acknowledgement grounded in the spoken query."""
        topic = re.sub(
            r"\b(?:좀|한번|검색|조사|확인|찾아|찾아봐|찾아봐줘|알아봐|알아봐줘|해줘|해주세요)\b",
            " ",
            query,
        )
        topic = re.sub(r"\s+", " ", topic).strip(" ,.!?요")
        topic = self._truncate(topic or "요청한 내용", 34).rstrip("…")
        if any(word in query for word in ("날씨", "기온", "비", "미세먼지")):
            templates = (
                "{topic}부터 확인해볼게요. 최신 예보를 모으는 동안 잠시만 기다려주세요.",
                "{topic}를 정확히 비교해볼게요. 잠깐만 기다려주세요.",
                "{topic} 자료를 확인 중이에요. 금방 핵심만 정리해드릴게요.",
            )
        elif any(word in query for word in ("가격", "비교", "구매", "제품")):
            templates = (
                "{topic} 조건을 비교해볼게요. 괜찮은 선택지만 추리는 동안 잠시만 기다려주세요.",
                "{topic} 가격과 차이를 확인 중이에요. 핵심만 추려서 알려드릴게요.",
                "{topic} 선택지를 살펴볼게요. 조금만 기다려주세요.",
            )
        else:
            templates = (
                "{topic} 관련 자료부터 확인해볼게요. 잠시만 기다려주세요.",
                "{topic} 근거를 비교하고 있어요. 조금만 기다리면 핵심만 정리해드릴게요.",
                "{topic} 내용을 살펴볼게요. 확인되는 대로 바로 알려드릴게요.",
                "{topic}부터 차근차근 확인해볼게요. 잠깐만 기다려주세요.",
            )
        template = templates[self._acknowledgement_index % len(templates)]
        self._acknowledgement_index += 1
        return template.format(topic=topic)

    def decide(
        self,
        content: str,
        *,
        title: str = "손자리 답변",
        requested_mode: str = "auto",
        legacy_speak: bool | None = None,
        force_visual: bool = False,
    ) -> Presentation:
        content = content.strip()
        plain = self._plain_text(content)
        non_space_chars = len(re.sub(r"\s", "", plain))
        estimated = round(non_space_chars / max(1.0, self.chars_per_second), 1)
        sentence_count = self._sentence_count(plain)
        bullet_count = len(re.findall(r"^\s*(?:[-*+] |\d+[.)] )", content, flags=re.MULTILINE))
        url_count = len(re.findall(r"https?://\S+", content))
        has_code = "```" in content
        has_table = len(re.findall(r"^\s*\|.*\|\s*$", content, flags=re.MULTILINE)) >= 2

        reasons: list[str] = []
        if force_visual:
            reasons.append("analysis_or_research")
        if has_code:
            reasons.append("code")
        if has_table:
            reasons.append("table")
        if url_count:
            reasons.append("links" if url_count == 1 else "multiple_sources")
        if bullet_count >= 4:
            reasons.append("long_list")
        if non_space_chars > self.short_max_chars:
            reasons.append("character_length")
        if sentence_count > self.short_max_sentences:
            reasons.append("sentence_count")
        if estimated > self.short_max_speech_sec:
            reasons.append("speech_duration")

        try:
            requested = DeliveryMode(requested_mode)
        except ValueError as exc:
            raise ValueError(f"invalid_delivery_mode:{requested_mode}") from exc

        if legacy_speak is False:
            requested = DeliveryMode.SCREEN
            reasons.append("legacy_speak_disabled")

        structured = has_code or has_table or bullet_count >= 4 or url_count >= 2
        if requested == DeliveryMode.VOICE:
            mode = DeliveryMode.VOICE
        elif requested == DeliveryMode.HYBRID:
            mode = DeliveryMode.HYBRID
        elif requested == DeliveryMode.SCREEN:
            mode = DeliveryMode.SCREEN
        elif reasons:
            mode = DeliveryMode.HYBRID
        else:
            mode = DeliveryMode.VOICE

        if mode == DeliveryMode.VOICE:
            spoken = plain
        elif mode == DeliveryMode.HYBRID:
            spoken = self._hybrid_summary(content, structured=structured)
        else:
            spoken = ""

        return Presentation(
            mode=mode.value,
            spoken_text=spoken,
            display_title=title,
            display_content=content,
            estimated_full_speech_sec=estimated,
            reasons=list(dict.fromkeys(reasons)),
        )


# ── 쥐고 있던 답을 화면에 칠하기 ──────────────────────────────────────────────
#
# ★ 왜 공용인가 (2026-08-15). 이 규율은 원래 `runtime._held_stream_callback` 안에만
# 있었고, **에이전트 루프에는 없었다.** 그래서 도구를 타는 판에서는 예전 증상이
# 그대로 남아 있었다 — 젬마가 도구 호출을 메시지 끝에 붙이므로 "이제 검색하겠습니다"
# 가 화면에 다 타이핑된 뒤에야 도구가 있는 걸 알고 지운다. 도구를 여러 개 태우면
# 그 깜빡임이 매 걸음 반복된다.
#
# 두 벌로 두면 갈리고, 갈린 쪽은 조용히 틀린다. 그래서 한 자리에 둔다.

# 총 칠하는 시간과 한 칸의 간격. 긴 답을 한 글자씩 칠하다 도리어 느려지면
# 고치려던 것과 반대가 되므로, 전체를 이 시간 안쪽으로 묶는다.
# ★ 2026-08-23: 700ms 는 **너무 빨랐다.** 사용자 말 — "읽기 전에 지나간다".
#
# 답 전체를 0.7초에 칠하니, 긴 답일수록 한 칸에 실리는 글자가 늘어 뭉텅뭉텅
# 튀어나왔다(예: 1,400자면 한 칸에 50자). 눈이 따라갈 수가 없다.
#
# 그래서 **총 시간이 아니라 글자 속도**로 바꿨다. 사람이 편하게 읽는 속도가
# 대략 초당 20~25자인데, 스르륵 지나가는 맛을 살리려면 그보다 빨라야 하므로
# 초당 90자로 잡았다. 한 칸에 25ms 면 칸당 두세 글자다.
#
# ⚠ **답이 나오는 시각 자체는 안 늦춘다.** 글은 이미 다 만들어져 있고, 여기서
#   하는 것은 칠하기뿐이다. 그래도 아주 긴 답이 하염없이 칠해지면 안 되므로
#   위쪽에 상한을 둔다.
PAINT_CHARS_PER_SEC = 90
PAINT_MS_MAX = 6_000
PAINT_TICK_MS = 25


def paint_answer(events: Any, job_id: str, text: str, *, reset: bool = True, pace: bool = True) -> bool:
    """확정된 답을 **스르륵** 내놓는다. 실제로 칠했으면 True.

    ★ 통째로 한 번에 보내면 안 된다(2026-08-10 실측). 글이 한 덩어리로 튀어나오고,
    **화면이 따라 내려가는 것도 같이 죽는다** — 따라가기는 delta 가 올 때마다 도는
    것이라 delta 가 한 번이면 한 번만 돈다.

    글은 이미 다 만들어져 있으니 다시 만들 필요는 없다. 칠하기만 나눠서 한다.

    ★ ``pace=False`` — **기다리는 쪽이 사람 눈이 아닐 때**는 칸 사이를 쉬지 않는다 (2026-10-07 코딩 사다리).
      이 함수는 판을 도는 스레드에서 돈다. 칠하기가 끝나야 판이 끝나므로, 답이 길면 판마다 최대 6초가 더 붙는다
      (답 491~1,167자인 여덟 판에서 3.1~5.4초). 스택을 찍어 보니 마지막 모델 호출 뒤 5.6초 동안 18번 중 17번이 이 줄이었다.
      ※ 처음엔 「윈도우의 25ms 쉼은 31ms 라 더 길다」고 적었는데 재 보니 25.35ms 였다 — 꼬리는 설계한 길이 그대로다.
      바깥 AI(클로드·코덱스)가 MCP 로 맡긴 판은 결과를 기다리는 것이 그 호스트다 — 연출 때문에 4~6초 늦게 받았다.
      칸으로 나눠 보내는 것은 그대로다(화면이 따라 내려가는 것은 칸마다 돈다). 화면에서 직접 시킨 판은 예전 속도 그대로다.
    """
    if not job_id or not text:
        return False
    if reset:
        events.publish("agent_answer_reset", {"job_id": job_id})
    # 글자 수로 시간을 정하고, 그 시간을 칸으로 나눈다. 짧은 답은 짧게, 긴 답은
    # 상한까지만 — 글자 수와 무관하게 700ms 에 우겨넣던 것을 뒤집는다.
    paint_ms = min(PAINT_MS_MAX, int(len(text) / PAINT_CHARS_PER_SEC * 1000))
    steps = max(1, min(len(text), paint_ms // PAINT_TICK_MS))
    size = max(1, math.ceil(len(text) / steps))
    for index in range(0, len(text), size):
        events.publish("agent_answer_delta", {"job_id": job_id, "delta": text[index : index + size]})
        if pace and index + size < len(text):
            time.sleep(PAINT_TICK_MS / 1000)
    return True


def paint_answer_apart(events: Any, job_id: str, text: str) -> bool:
    """확정된 답을 **판 밖에서** 칠한다 — 부른 쪽은 기다리지 않는다. 시작했으면 True. (2026-10-07)

    `paint_answer` 는 부른 스레드에서 쉬어 가며 칠한다. 그 스레드가 판을 도는 스레드라, 칠하기가 끝나야 판이 끝났다
    (답 길이에 따라 3~5초 — 그동안 다음 판이 못 시작하고, 결과 카드도 안 뜬다). 연출은 그대로 두고 자리만 옮긴다.

    화면과의 약속:
      - 시작할 때 `agent_answer_reset` 에 `apart: true` 를 싣는다 — 「이 답은 판이 끝난 뒤에도 조각이 온다」.
      - 다 칠하면 `agent_answer_painted` 를 보낸다(실패해도 보낸다 — 화면이 기다리다 멈추면 안 된다).
    이 약속을 모르는 화면(옛 판)은 판이 끝나는 순간 완성된 답으로 바꿔 보여 준다 — 답은 온전하고 연출만 짧아진다.
    """
    if not job_id or not text:
        return False
    events.publish("agent_answer_reset", {"job_id": job_id, "apart": True})

    def run() -> None:
        try:
            paint_answer(events, job_id, text, reset=False)
        finally:
            events.publish("agent_answer_painted", {"job_id": job_id})

    threading.Thread(target=run, name=f"paint-{job_id[:8]}", daemon=True).start()
    return True
