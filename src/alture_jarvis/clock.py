"""What time it is, in the one form the models are told about.

The model has no clock. Left to itself it answers "오늘 며칠이야?" from whatever
its training data suggests -- confidently and wrongly -- and that date then
spreads into anything it schedules, writes or files.

Lives in its own module because two callers need the identical string: the
assistant that talks to the user, and the agent it dispatches work to. They used
to build their own, in different formats and different timezones, so the agent
could be working on a different "today" than the assistant that sent it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# The office is in Korea and the operator asks in Korean, so this is Seoul's
# clock -- not the host's local zone, which would silently change the answer if
# this machine ever travelled.
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS_KO = ("월", "화", "수", "목", "금", "토", "일")


def now_line_ko(now: datetime | None = None) -> str:
    """The current date, weekday and time in Korean, as labelled fields.

    Written as a short list rather than one flowing sentence because of what
    happened with the sentence version: asked the date, the model copied the
    date and the time correctly out of the prompt and then stated the *weekday*
    wrong -- it worked the weekday out for itself instead of reading it. Giving
    each field its own label, and saying outright not to derive the weekday,
    leaves nothing to recompute.

    Truncated to the minute so the system prompt is stable between consecutive
    requests: a second-by-second string invalidates the model's cached prefix on
    literally every message, for no gain in usefulness.
    """
    now = now or datetime.now(KST)
    weekday = WEEKDAYS_KO[now.weekday()]
    return (
        "현재 한국 시각 (KST)\n"
        f"- 날짜: {now.year}년 {now.month}월 {now.day}일\n"
        f"- 요일: {weekday}요일\n"
        f"- 시각: {now.hour:02d}:{now.minute:02d}\n"
        "날짜·요일·시각을 물으면 위 값을 그대로 쓴다. "
        "특히 요일은 직접 계산하지 마라 — 위에 적힌 요일이 정답이다.\n\n"
        + upcoming_days_ko(now)
    )


def upcoming_days_ko(now: datetime | None = None, *, days: int = 8) -> str:
    """앞으로 며칠의 날짜를 **요일 이름으로 찾을 수 있게** 펼쳐 둔다.

    요일을 계산하지 말라고 적어 둔 것과 같은 처방이다. 오늘 요일을 알려 줘도
    「이번 주 토요일이 며칠인가」는 여전히 모델이 더해야 하는 값이고, 실제로
    틀렸다 — 2026-09-04(금)에 「이번 주 토·일」을 묻자 **9/6~9/7** 이라고 답했다
    (맞는 값은 9/5~9/6). 그 날짜로 숙소를 찾으면 엉뚱한 밤을 예약한다.

    날짜 계산은 코드가 이미 정확히 하는 일이다. 모델에게는 **찾아 쓰라고** 준다.
    """
    now = now or datetime.now(KST)
    today = now.date()
    lines = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        label = {0: " (오늘)", 1: " (내일)", 2: " (모레)"}.get(offset, "")
        lines.append(
            f"- {day.month}월 {day.day}일 {WEEKDAYS_KO[day.weekday()]}요일{label}"
        )
    return (
        "앞으로의 날짜 ('이번 주 토요일'·'주말'·'내일' 같은 말은 여기서 찾아 쓴다. "
        "직접 더하지 마라)\n" + "\n".join(lines)
    )
