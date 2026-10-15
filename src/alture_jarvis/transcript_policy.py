"""agent.py 에서 **전사·생각 예산** 묶음을 분리한다 (2026-10-09).

왜: agent.py 가 12,691줄로 커서 읽기 어려웠다. 이 묶음은 BrowserAgent 클래스와
순환 import가 없고, 시험이 ``inspect.getsource(agent)`` 로 요구하는 문자열도
포함하지 않아 그대로 옮길 수 있다.

이름 목록(25개):
  _TRANSCRIPT_BUDGET_CHARS, _CODE_CHARS_PER_TOKEN, _CODE_OUTPUT_RESERVE_TOKENS,
  _CODE_BUDGET_SHARE, code_transcript_budget, _CHAT_BUDGET_SHARE_SMALL,
  _CHAT_SMALL_MAX_TOKENS, _CHAT_BUDGET_SHARE, _CHAT_CHARS_PER_TOKEN,
  _CHAT_OUTPUT_RESERVE_TOKENS, _SMALL_MODEL_TAG, is_small_model,
  chat_transcript_budget, window_fitted_budget, _SYSTEM_BUDGET_CHARS, _TOOL_SCHEMA_CHARS_PER_TOKEN,
  _PER_JOB_SECTIONS, _THINKING_STREAM_CHARS, _THINKING_EMIT_SEC,
  _FORCED_READ_LIMIT, _FORCED_READ_GRACE_SEC, _OPEN_RESULT_TOOL, _EXTRACT_TOOL,
  _THINK_ALWAYS, _THINK_ADAPTIVE, _THINK_OFF, _model_time_summary,
  _final_answer_thinks, _REASONING_POLICY, _job_thinking_policy,
  _reasoning_escalated, _should_think, _TOOL_RESULT_MAX_CHARS, _bounded_tool_result
"""
from __future__ import annotations

import re
from typing import Any

# 모델 창에 실제로 들어가는 전사의 상한. **여기가 진짜 상한이다** —
# `ollama_num_ctx` 를 아무리 올려도 이 값을 안 올리면 아무것도 안 바뀐다.
# 한글·코드 실측 약 2자 = 1토큰이므로 180,000자 ≈ 90,000토큰이고, 이는
# `config.ollama_num_ctx`(131,072)와 **쌍이다.**
_TRANSCRIPT_BUDGET_CHARS = 180_000

# ── Code 전사 예산은 **창에서 파생한다** ────────────────────────────────
#
# 예전에는 여기 하드 상수를 적어 뒀다(balanced 128,000자). 그런데 코드 판의
# 실제 글자/토큰 비는 한글 산문(2자)이 아니라 **약 3.2자**다. 그래서 128,000자는
# 약 40,000 토큰이고, 코드 역할의 창(num_ctx 102,400)의 **39%** 였다.
#
# 2026-08-28 실측(66개 파일 저장소, 추론 21회): 프롬프트가 40K 토큰에 닿자마자
# 매 걸음 전사가 접혔고, 접히면 앞부분이 바뀌어 프리픽스 캐시가 죽는다.
# 21회 중 캐시 적중은 **1회**, 프리필에만 **435초**를 썼다. 창은 60%가 놀고
# 있는데 예산이 먼저 잘라서 생긴 손해다.
#
# 이 저장소가 네 번 당한 「상한이 여러 군데」의 다섯 번째다. 그래서 상수를 지우고
# 창에서 파생시킨다 — 창을 키우면 예산이 따라 오고, 둘이 갈릴 수가 없다.
_CODE_CHARS_PER_TOKEN = 3.2
#: 모델이 뱉을 자리 + 시스템/도구 정의가 쓸 자리. 이만큼은 전사에 안 준다.
_CODE_OUTPUT_RESERVE_TOKENS = 12_000
#: 프로필별로 창을 얼마나 쓸 것인가.
#
# ★ 2026-08-28, 두 번째 조정. 처음엔 0.9(≈81K 토큰)로 열었는데, 그건 **긴 컨텍스트
#   열화 구간 한복판**이다. 공개 연구 실측: 26개 모델을 32K↔128K 에서 재니 중앙값
#   10.4%p 하락, 나쁜 경우 28.3%p 붕괴. 그리고 정확도는 U자 곡선이라 앞과 뒤는
#   잘 보는데 **중간은 30% 넘게 떨어진다** — 128K 창이라도 40K~80K 구간을 놓친다.
#
#   우리 실측도 같은 방향이었다. 예산을 열자 프롬프트가 54,521 토큰까지 갔고,
#   프리필은 435초 → 71.5초(캐시 적중 5% → 86%)로 크게 줄었지만 **전체 시간은
#   806초 → 759초, 6% 밖에 안 줄었다.** 병목이 생성으로 옮겨갔고, 컨텍스트가
#   클수록 모델이 더 길게 생각한다(생성 3,248 토큰짜리 호출이 89초).
#
#   그래서 「창을 크게 여는 것」은 전략이 아니라 **안전밸브**로 되돌린다.
#   진짜 해법은 넣는 양을 줄이는 쪽(저장소 지도 · 목차 · 줄 범위 읽기 · 정찰기)
#   이고, 예산은 그것들이 실패했을 때만 쓰이는 보험이어야 한다.
#   balanced 0.55 ≈ 49,700 토큰 — 예전 40K 보다는 높아 압축을 덜 부르고,
#   열화 구간(40K~80K)의 깊은 쪽은 피한다.
#   ★ 2026-08-28 세 번째, 그리고 **되돌림.** 0.55(≈49K)로 조여 봤더니 더 나빴다:
#     캐시 적중 86% → 60%, 그리고 느려진 프리필 + 긴 생성이 Ollama 타임아웃을
#     넘겨 잡이 죽었다. 이유는 단순하다 — **상한을 낮추면 압축을 더 자주 부르고,
#     압축이 걸리는 순간 앞부분이 바뀌어 캐시가 죽는다.**
#
#     그래서 규칙은 이렇게 정리한다: **상한은 넉넉히 두어 압축이 안 걸리게 하고,
#     실제 컨텍스트는 ①목차·줄범위 ②정찰기 ③저장소 지도로 작게 유지한다.**
#     0.9 판의 실제 최대는 54K 로 상한(81K) 아래였고, 그래서 압축이 한 번도
#     안 걸렸다. 긴 컨텍스트 열화가 걱정되면 줄여야 할 것은 상한이 아니라
#     **실제 사용량**이다.
_CODE_BUDGET_SHARE = {"fast": 0.45, "balanced": 0.9, "medium": 0.9, "deep": 0.95}


def code_transcript_budget(num_ctx: int, profile: str = "balanced") -> int:
    """이 창에서 전사에 줄 수 있는 글자 수."""
    usable = max(4_000, int(num_ctx) - _CODE_OUTPUT_RESERVE_TOKENS)
    share = _CODE_BUDGET_SHARE.get(profile, 0.9)
    return int(usable * share * _CODE_CHARS_PER_TOKEN)

#: 대화 판의 전사 예산 — **모델 문맥 창의 비율**로 정한다 (2026-09-24 노트북 실측).
#:
#:   예전엔 모델과 상관없이 180,000자(≈9만 토큰)였다. 3090 의 35B·131K 에 맞춘 값이라, 노트북 4B(창 77,824)에서는
#:   사실상 상한이 없었다: 조사를 다시 하는 판에서 걸음마다 40K→53K→62K→**73.8K 토큰**을 밀어 넣었고, 4B 가 사고를
#:   되풀이했다(사용자: 「무한루프 띵킹」). 헤르메스는 창의 50% 에서 압축한다. 작은 모델은 긴 문맥에서 더 먼저
#:   무너지므로 35%, 큰 모델은 지금 값과 거의 같게(70%) 둔다. 넘으면 `transcript.py` 규칙대로 시킨 일은 고정하고
#:   오래된 페이지 본문부터 접는다. 한글은 약 2자 = 1토큰(2026-08-10 실측).
_CHAT_BUDGET_SHARE_SMALL = 0.35  # (옛 값 — 아래 _CHAT_SMALL_MAX_TOKENS 로 바뀜)
_CHAT_SMALL_MAX_TOKENS = 24_000
_CHAT_BUDGET_SHARE = 0.7
_CHAT_CHARS_PER_TOKEN = 2.0
_CHAT_OUTPUT_RESERVE_TOKENS = 8_192
#: 이름으로 본 **작은 모델**(대략 5B 이하): qwen3.5:4b · gemma3:4b · gemma4:e4b · llama3.2:3b · qwen3:1.7b …
#: 앞이 글자면 안 된다 — `qwen3.6:35b-a3b` 의 「a3b」는 **활성** 파라미터라 큰 모델이다(첫 판에서 잘못 잡았다).
_SMALL_MODEL_TAG = re.compile(r"(?<![\w.])(?:0\.\d+|1(?:\.\d+)?|2|3|4|5|e2|e4)b\b", re.I)


def is_small_model(model: str) -> bool:
    return bool(_SMALL_MODEL_TAG.search(str(model or "")))


def chat_transcript_budget(num_ctx: int, model: str = "") -> tuple[int, int]:
    """대화 판에서 전사에 줄 글자 수와, 도구 결과 한 건에 줄 글자 수. 둘 다 창을 넘지 않는다."""
    usable = max(4_000, int(num_ctx) - _CHAT_OUTPUT_RESERVE_TOKENS)
    if is_small_model(model):
        # 작은 모델은 **창 크기가 아니라 모델이 감당하는 양**으로 정한다 — 창을 32K 로 줄이면(8GB 카드 권장) 비율로는
        # 8천 토큰밖에 안 남는다. 2.4만 토큰(오늘 이어받기 판 최대 ~3.4만에서 페이지 접기로 줄어드는 양), 창의 75% 안.
        tokens = min(_CHAT_SMALL_MAX_TOKENS, usable * 0.75)
    else:
        tokens = usable * _CHAT_BUDGET_SHARE
    budget = min(_TRANSCRIPT_BUDGET_CHARS, max(12_000, int(tokens * _CHAT_CHARS_PER_TOKEN)))
    # 페이지 하나가 예산의 1/4 를 넘으면 두 페이지만 읽어도 앞이 다 접힌다.
    # ★ 2026-10-12 해 보고 되돌렸다 — 지우지 않고 적어 둔다. 그 「예산」에는 시스템 글도 들어 있어서(`transcript.bounded` 가
    #   거기서 뺀다) 창 32,768 에서는 한 건(8,600자)이 걸음에 쓸 자리(1만 4천 자)의 6할이다. 그래서 「시스템 글을 뺀 나머지의
    #   1/4」(창 32K 에서 4,000자)로 줄였더니, 같은 조건의 가격 조사 세 판 중 둘이 **2걸음 만에** 끝났다(eafd8622 · 8c382270):
    #   「검색 결과에 실제 쇼핑몰 링크가 없으므로」 · 「검색 결과 없음 → 아직 출시되지 않았거나」. 이 값은 읽은 화면뿐 아니라
    #   **검색 결과 목록**도 자른다 — 목록의 뒤쪽(가게 링크)이 잘려 나갔다. 읽은 화면이 밀려나는 것은 값의 크기가 아니라
    #   「밀려난 것을 통째로 버린다」 쪽에서 고쳤다(`transcript.read_ledger`). 이 셈을 다시 손댈 때는 목록 결과와 읽은 화면을
    #   가르고, 넣기 전에 판으로 잰다.
    return budget, max(4_000, min(_TOOL_RESULT_MAX_CHARS, budget // 4))


# ── 예산은 **서버가 알려 준 실제 프롬프트 크기**를 따른다 (2026-10-11) ──────────────────
#
# 위의 예산은 글자로 센다: 「창의 70% × 토큰당 2자」. 남긴 30% 가 도구 목록과 어림의 오차를 받아 주리라는 셈이다.
# 큰 창(131,072)에서는 그 30% 가 3만 6천 토큰이라 넉넉했다. 16GB 조건(창 49,152)에서는 1만 2천 토큰인데, 그날 잰
# 고정 앞부분(지침 + 도구 목록)이 **28,201토큰**이었고 읽은 글(주소 · 숫자 · 한글 본문)은 토큰당 2자보다 촘촘했다:
#
#     가격 조사 스킬팩 세 판(작은 27B 판 · 창 49,152)
#     91e91957  마지막 호출이 49,151토큰에서 끊김 — 쓸 자리 1,585토큰. 세 가게를 다 읽고 엑셀을 못 만들고 멈춤
#     2689e68c  48,983토큰 다음 호출에서 창을 넘음 → Ollama 가 앞쪽 메시지를 잘라 냄 → 시킨 말이 사라져 대화 틀이 거절(500)
#
# 도구 목록이 몇 토큰인지, 이 글이 토큰당 몇 자인지를 **미리 맞히지 않는다**(목록은 일마다 다르고 글은 페이지마다 다르다).
# 서버는 호출마다 프롬프트 토큰 수를 돌려준다(`prompt_eval_count` — 그 판의 큰 호출 16번 합 618,418 이 Ollama 기록의
# 「대화 전체」 합과 맞았다: 새로 읽은 만큼이 아니라 **전체 크기**다). 그 값으로 다음 호출의 예산을 정한다:
#
#     다음 예산 = 지난번에 보낸 글자 + (창 − 쓸 자리 − 지난번 프롬프트 토큰) × 1.5자
#
# 자리가 남았으면 남은 만큼 더 주고, 쓸 자리를 먹었으면 먹은 만큼 던다. 원래 예산을 넘지는 않는다 — 창이 넉넉하면
# 아무것도 안 바뀐다. 1.5 는 그날 본 가장 촘촘한 쪽에 맞춘 값이다(한글 본문 1.7자). 낮게 잡으면 덜 넣고, 높게 잡으면 넘친다.
#
# ※ 이것은 **넘치지 않게** 할 뿐이다. 창 49,152 에서 고정 앞부분이 57% 라는 사실은 그대로고, 접힌 페이지의 값을 모델이
#   기억하는지는 실제 판으로 봐야 한다. 걸음마다 접혀 앞부분을 다시 읽는 것(그 판 489초 중 214초)도 이것으로는 안 준다.
_WINDOW_FIT_CHARS_PER_TOKEN = 1.5


# ★ 자리가 남았으면 **넓히기도 한다** (2026-10-12 밤 · `widen`).
#
#   같은 공식 9B 로 같은 가격 조사를 돌렸는데 창 49,152 에서는 온전한 줄이 9 · 8 · 7 이고 창 32,768 에서는 고침 넷을 넣고도
#   3 · 1 · 2 · 1 · 2 였다. 판마다 서버가 알려 준 가장 큰 프롬프트를 나란히 놓으니:
#
#       창 49,152   40,180 ~ 41,838토큰   (쓸 자리 8,192 를 빼면 꽉 찼다)
#       창 32,768   20,115 ~ 20,961토큰   (쓸 자리를 빼고도 **3,600 ~ 4,400토큰이 비었다**)
#
#   글자로 센 예산(「창의 70% × 토큰당 2자」)이 창 32,768 에서는 34,406자인데, 조사 판의 글(주소 · 숫자 · JSON 이 섞인다)은
#   토큰당 3.8자쯤이어서 걸음에 돌아간 것이 9천 토큰뿐이었다 — 창 49,152 의 1만 5천 토큰과 견주면 6할이다. 위의 맞춤은
#   넘친 것만 좁혔고 「원래 예산을 넘지는 않는다」로 묶여 있어, 남은 자리는 그대로 버려졌다. 큰 창에서는 예산이 이미
#   상한(18만 자) 근처라 넓힐 것이 없다 — 이 고침이 닿는 곳은 작은 창이다.
#
#   넓히는 셈도 좁히는 셈과 같다(남은 토큰 × 1.5자). 걸음마다 다시 재니, 촘촘한 글이 들어와 넘치면 다음 호출에서 도로 좁힌다.
#   과녁(창 − 쓸 자리)은 안 바꿨다. 코드 판은 예산을 따로 셈하므로 넓히지 않는다.
#
#   아직 모르는 것: 걸음을 더 보여 주면 9B 가 셋째 가게까지 가는지 — 지금부터 잰다.
def window_fitted_budget(
    budget: int, *, num_ctx: int, sent_chars: int, prompt_tokens: int,
    reserve_tokens: int = _CHAT_OUTPUT_RESERVE_TOKENS, widen: bool = False,
) -> int:
    """지난 호출에서 잰 값에 맞춘 예산(글자). 잰 것이 없으면 받은 예산 그대로.

    `widen` 이 꺼져 있으면 좁히기만 한다(받은 예산이 천장). 켜면 자리가 남은 만큼 받은 예산을 넘어 넓힌다 — 천장은
    전사 전체 상한(`_TRANSCRIPT_BUDGET_CHARS`)이다.
    """
    if int(num_ctx) <= 0 or int(sent_chars) <= 0 or int(prompt_tokens) <= 0:
        return budget
    room = int(num_ctx) - int(reserve_tokens) - int(prompt_tokens)
    fitted = int(sent_chars) + int(room * _WINDOW_FIT_CHARS_PER_TOKEN)
    ceiling = max(int(budget), _TRANSCRIPT_BUDGET_CHARS) if widen else int(budget)
    return max(1, min(ceiling, fitted))


#: 화면으로 흘려보낼 사고 원문의 총량. 넘으면 그 판은 더 안 보낸다.
#: 웹소켓 예산이자 사람이 좇을 수 있는 양이다 — 잘린 사실은 화면이 말한다.
#: 시스템 메시지에 줄 자리. `transcript.bounded(system_max=)` 보다 **작아야** 한다 —
#: 여기서 목록 단위로 맞춰 보내면 뒤쪽 뭉텅 자르기는 발동할 일이 없다(마지막 안전망).
#: 실측(2026-08-31) 조립 합계 20,148자: 계약 12,109 · 코드계약 1,767 · 사고카드 2,531
#: · 저장소 지도 2,936 · 그 외. 24,000 은 거기서 19% 여유다.
_SYSTEM_BUDGET_CHARS = 24_000

#: 도구 정의(JSON) 한 토큰이 대략 몇 글자인가 — 2026-10-07 운영 모델에 직접 물어 잼: 등록부 전체 153개 65,345자 = 22,439토큰,
#: 웹 갈래 82개 33,836자 = 11,671토큰 → 차 31,509자 / 10,768토큰 = 2.93자. 정확할 필요는 없다(창의 5% 를 넘는지만 본다).
_TOOL_SCHEMA_CHARS_PER_TOKEN = 3.0

#: 판마다 바뀌는 칸 — 시스템 메시지가 아니라 **요청 메시지 앞**에 싣는다(`transcript.fit_system_split`).
#: 여기 없는 칸(말투·계약·코드 계약·중계·자사 데이터·사용자 프로필·사고 도구 목록)은 같은 모드의 판끼리 글자까지 같아야 한다.
#: ★ 「사용자 맥락」(`user_context`)은 여기 넣지 않는다 — 사용자가 관리하는 **프로필**이라 판이 바뀌어도 같은 글이다.
#:   처음엔 이름만 보고 옮겼더니 판마다 그 1천여 토큰을 다시 읽었다(새 판 첫 호출 4,556토큰 · 2.0초).
_PER_JOB_SECTIONS = frozenset({"skill_note", "repo_card", "now"})

_THINKING_STREAM_CHARS = 20_000

#: 조각마다 보내면 초당 수십 번이 된다. 시간으로 묶어 내보낸다.
_THINKING_EMIT_SEC = 0.25

_FORCED_READ_LIMIT = 6

# 예산이 끝난 뒤에도 이만큼은 더 쓴다.
#
# ★ 왜 유예가 필요한가 (2026-08-20 라이브). 다나와 판이 **3개 중 2개만 읽고**
# `model_stopped_early` 로 끝났는데 `forced_reads` 가 0이었다. 판정 함수는 rank 2 를
# 내놓고 있었다 — 걸러낸 것은 `time.monotonic() < deadline` 한 줄이었다.
# `elapsed_sec 181.27` · 예산 180초. **1.27초가 모자라 답이 미완성으로 나갔다.**
#
# 181초를 쓰고 나서 25초를 더 안 써서 틀린 답을 내보내는 것은 둘 중 나쁜 쪽이다.
# 그렇다고 무한정 열게 두면 예산이 뜻을 잃으므로, **한 항목을 더 채울 만큼만** 준다:
#
#     실측(3일·50판) 걸음당 중앙 13.3초 · 90p 25.0초
#     → 열기+읽기 한 쌍  중앙 27초 · 90p 50초
#
# 60초면 90퍼센타일에서도 한 쌍이 들어간다. 개수는 `_FORCED_READ_LIMIT` 가,
# 걸음은 `step_limit` 이 따로 막으므로 이 값이 유일한 상한은 아니다.
_FORCED_READ_GRACE_SEC = 60

# 읽기를 강제할 때 쓰는 두 칸. `_TEXT_READ_TOOLS` 와 달리 이건 **브라우저에서
# 목록→상세로 들어가는** 경로만 다룬다.
_OPEN_RESULT_TOOL = "browser_open_result"
_EXTRACT_TOOL = "browser_extract"


#: 걸음마다 생각할 것인가.
#:
#: ★ 2026-09-03 실측. 코워크 판당 **사고 11,712자 · 답 1,308자** — 답 1글자당
#:   사고 9글자다. 100토큰/초로 치면 판 133초 중 **78초가 사고**다. 프리필은
#:   204,883토큰을 15초에 끝낸다(프리픽스 캐시가 이미 잘 듣는다). 느린 원인은
#:   프리필도 도구도 아니라 **생각하는 시간**이었다.
#:
#: 그런데 12걸음 중 대부분은 기계적이다 — 「2번 결과 열기」, 「본문 추출」.
#: 도구 결과가 잘 나온 직후에 8초를 더 생각할 이유가 없다.
#:
#: ⚠ 기본은 `always` 다. **사고가 비싸다는 것만 쟀지, 값을 못 한다는 것은 안 쟀다.**
#:   통제 실험으로 확인한 뒤에 기본값을 바꾼다.
_THINK_ALWAYS = "always"
_THINK_ADAPTIVE = "adaptive"
_THINK_OFF = "off"


def _model_time_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """한 판의 모델 시간을 **프리필과 생성으로** 가른다 (2026-09-18).

    실측으로 확인한 것: 맥락 캐시는 잘 듣는다(20K 토큰 재프리필이 0.5~1.4초). 느린 판의 시간은
    거의 전부 **생성**이고, 그중에서도 예산 상한까지 쓴 턴 몇 개가 가져간다.
    이 줄이 없어서 「느리다」에 답할 때마다 손으로 더해야 했다.
    """
    prefill = generate = 0.0
    prompt_tokens = eval_tokens = capped = 0
    for item in observations:
        timing = item.get("telemetry") or item.get("timing") or {}
        prefill += float(timing.get("prompt_eval_duration") or 0) / 1e9
        generate += float(timing.get("eval_duration") or 0) / 1e9
        prompt_tokens += int(timing.get("prompt_eval_count") or 0)
        count = int(timing.get("eval_count") or 0)
        eval_tokens += count
        # 상한에 닿은 턴 — 「더 쓰고 싶었는데 잘린」 턴이다. 이 수가 곧 사고 폭주의 빈도다.
        if count >= 8000:
            capped += 1
    return {
        "turns": len(observations),
        "prefill_sec": round(prefill, 1),
        "generate_sec": round(generate, 1),
        "prompt_tokens": prompt_tokens,
        "generated_tokens": eval_tokens,
        "turns_at_predict_cap": capped,
    }


def _final_answer_thinks(config: Any, policy: str | None = None) -> bool:
    """마무리 답을 쓸 때 생각할 것인가. 설정 「생각 깊이 › 빠르게」(`off`)면 안 한다.

    ★ 2026-09-24 부산 노트북(「너무 느리다」): 걸음마다의 생각은 정책을 따랐지만 마무리 답은 `agent_thinking_enabled`
      하나만 봐서, 「빠르게」를 골라도 마지막 답에서 생각을 다 했다.
    """
    if not getattr(config, "agent_thinking_enabled", True):
        return False
    return str(policy or getattr(config, "agent_thinking_policy", _THINK_ALWAYS) or _THINK_ALWAYS) != _THINK_OFF


#: 입력창의 「추론」 칩 → 걸음마다의 생각 정책 (2026-09-28 사장님 제안 — 헤르메스 입력창의 Med 칩).
_REASONING_POLICY = {"fast": _THINK_OFF, "normal": _THINK_ADAPTIVE, "deep": _THINK_ALWAYS}


def _job_thinking_policy(config: Any, reasoning: str, *, escalated: bool) -> str:
    """이 판의 생각 정책. 칩이 비었으면 설정(「생각 깊이」)을 따른다.

    **자동** = 싼 것부터 → 막히면 올림(전략안 「예측 라우팅 금지 · 실패하면 승급」). 요청 문장으로 난이도를 미리 맞히지 않는다.
    「보통」(막힌 자리에서만 생각)으로 시작하고, 이 판에서 되받기가 나오거나 실패가 두 번 쌓이면(`escalated`) 끝까지 「깊게」로 간다.
    """
    choice = str(reasoning or "").strip().lower()
    if choice == "auto":
        return _THINK_ALWAYS if escalated else _THINK_ADAPTIVE
    if choice in _REASONING_POLICY:
        return _REASONING_POLICY[choice]
    return str(getattr(config, "agent_thinking_policy", _THINK_ALWAYS) or _THINK_ALWAYS)


def _reasoning_escalated(steps: list[dict[str, Any]], pushbacks: int) -> bool:
    """「자동」이 깊게로 올라갈 때인가 — 되받기가 한 번이라도 났거나, 실패한 걸음이 둘 이상."""
    return pushbacks > 0 or sum(1 for step in steps if not step.get("ok")) >= 2


def _should_think(
    config: Any, steps: list[dict[str, Any]], *, artifact_focus: bool = False, policy: str | None = None
) -> bool:
    """이 걸음에서 생각할 것인가.

    `adaptive` 는 **막힌 자리에서만** 생각한다:

        · 첫 걸음        무엇을 할지 아직 아무것도 안 정했다
        · 직전 걸음 실패  왜 실패했는지 따져야 새 수가 나온다
        · 같은 도구 반복  같은 손을 또 뻗고 있으면 멈춰서 생각해야 한다

    그 밖의 걸음 — 열고 읽고 다음 것 열고 — 은 도구 결과가 다음 수를 정해 준다.
    """
    if not getattr(config, "agent_thinking_enabled", True):
        return False
    if artifact_focus:
        # 산출물 전환은 추론보다 구조화된 인자가 필요하다(예전부터 껐다).
        return False
    policy = str(policy or getattr(config, "agent_thinking_policy", _THINK_ALWAYS) or _THINK_ALWAYS)
    if policy == _THINK_OFF:
        return False
    if policy != _THINK_ADAPTIVE:
        return True
    if not steps:
        return True
    if not steps[-1].get("ok"):
        return True
    if len(steps) >= 2 and steps[-1].get("tool") == steps[-2].get("tool"):
        return True
    return False


#: 같은 탭에 새 페이지를 올리는 도구 — 연달아 부르면 앞 페이지가 **읽히기 전에 덮인다.**
_PAGE_OPEN_TOOLS = frozenset({"browser_open", _OPEN_RESULT_TOOL})
#: 지금 떠 있는 페이지를 읽는 도구 — 어느 페이지인지는 인자가 아니라 **순서**가 정한다.
_PAGE_READ_TOOLS = frozenset({_EXTRACT_TOOL, "browser_read"})



#
# `browser._extract` 의 상한과 쌍이다 — 저쪽이 30,000 을 돌려줘도 여기가 20,000 이면
# 10,000 이 조용히 날아간다. 상한이 여러 군데면 낮은 쪽만 일한다(2026-08-13 세 번째).
#
# 세 장을 읽어도 90,000 자로, 전사 예산 110,000 안에 든다. 그보다 크게 잡으면
# 앞부분이 밀려나면서 Ollama 프리픽스 캐시가 무효가 되고(실측 11배 차이) 오히려
# 느려진다 — `_bounded_transcript` 주석의 그 절벽이다.
_TOOL_RESULT_MAX_CHARS = 30_000

def _bounded_tool_result(text: str, limit: int = _TOOL_RESULT_MAX_CHARS) -> str:
    """도구 결과를 상한에 맞춘다 — **잘랐으면 잘랐다고 적는다.**

    예전에는 `[:30_000]` 로 조용히 잘랐다. 잘린 뒤쪽에 목록의 끝과 안내문이 있었는데(2026-10-07 스냅샷 32,011자),
    모델에게는 「그게 전부」로 보였다. 목록에서 빠진 것과 화면에 없는 것은 모델 눈에 똑같다.
    """
    if len(text) <= limit:
        return text
    note = f" …(도구 결과가 길어 여기서 잘렸다 — 전체 {len(text):,}자. 뒤에 더 있다. 필요한 것은 이름으로 찾거나 범위를 좁혀 다시 불러라.)"
    return text[: max(0, limit - len(note))] + note



# 그리고 **한 번 실패하면 그만둔다.** 목록이 없는 화면이었다면 `no_result_list` 가
# 오고, 같은 것을 다시 밀어 봐야 같은 실패다 — 커밋 쪽의 `attempted` 규칙과 같다.

def _call_position(calls: list[Any], current: Any) -> int:
    """이 호출이 묶음의 몇 번째인가 — **같은 물건**으로 찾는다(-1 = 없음).

    `list.index` 는 같은 값을 찾는다. 인자가 똑같은 읽기 넷(`browser_extract {}`)이 든 묶음에서는 넷 다 첫 자리로 읽힌다.
    """
    for index, item in enumerate(calls):
        if item is current:
            return index
    return -1


def _reads_beside_their_opens(calls: list[Any], name_of: Any) -> list[Any]:
    """한 턴에 「열기 여러 번 → 읽기 여러 번」을 묶어 보냈으면, 읽기를 **제 열기 바로 뒤로** 옮긴다.

    ★ 2026-10-06 실사용(코드 서명 가격 조사 19be07a1). 모델이 한 턴에 이렇게 불렀다:

        browser_open(A) · browser_open(B) · browser_open(C) · browser_open(D)
        browser_extract · browser_extract · browser_extract · browser_extract

    열기는 같은 탭을 덮는다. 읽기 넷이 전부 D 를 읽었고(본문 지문이 넷 다 같다) A·B·C 는 한 글자도 안 읽혔다.
    걸음 상한 12 를 77초에 다 쓰고 「세 페이지를 다시 읽겠습니다」로 끝났다 — 읽은 D 의 값도 답에 없었다.

    뜻은 분명하다: 넷을 열어 넷을 읽으려던 것이다. 안내문으로 「하나씩 열고 읽어라」를 적는 대신(안 먹는다 — 사고 R)
    **순서를 바로잡는다.** 내용은 안 바꾼다 — 모델이 부른 호출을 그대로, 자리만 옮긴다.

    운영 14일(브라우저 판 432): 같은 묶음에서 덮인 열기 38판 · 98쪽, 그중 66쪽은 그 판에서 끝내 안 읽혔다.

    - 짝은 **뒤에서부터** 짓는다. 읽기가 모자라면(열기 3 · 읽기 1) 마지막 열기가 읽기를 갖는다 — 원래 순서에서
      읽히던 페이지를 못 읽게 만들지 않는다. 앞에 남은 열기는 `_fused_read_call` 이 덮이기 전에 읽힌다.
    - 읽기가 남으면(열기 2 · 읽기 3) 남는 읽기는 원래대로 맨 뒤에 둔다.
    - 바꿀 것이 없으면 **받은 목록 그대로** 돌려준다(`is` 로 가릴 수 있다).
    """
    names = [name_of(call) for call in calls]
    out: list[Any] = []
    index = 0
    while index < len(calls):
        if names[index] not in _PAGE_OPEN_TOOLS:
            out.append(calls[index])
            index += 1
            continue
        start = index
        while index < len(calls) and names[index] in _PAGE_OPEN_TOOLS:
            index += 1
        opens = calls[start:index]
        read_start = index
        while len(opens) >= 2 and index < len(calls) and names[index] in _PAGE_READ_TOOLS:
            index += 1
        reads = calls[read_start:index]
        if not reads:
            out.extend(opens)
            continue
        lead = max(0, len(opens) - len(reads))
        out.extend(opens[:lead])
        paired = opens[lead:]
        for opened, read in zip(paired, reads):
            out.extend((opened, read))
        out.extend(reads[len(paired):])
    if len(out) == len(calls) and all(a is b for a, b in zip(out, calls)):
        return calls
    return out


def _read_completes_an_open(steps: list[dict[str, Any]], name: str) -> bool:
    """이 읽기가 **바로 앞 걸음에서 연 페이지**의 읽기인가 — 걸음 상한이 그 사이를 끊지 않게.

    ★ 2026-10-07 실기(코드 서명 가격 판 c4b26962). 모델이 `browser_open(네 번째 판매처)` · `browser_extract` 를 한 턴에
      불렀는데, 열기에서 걸음 상한이 차서 읽기가 잘렸다. 판은 「목표 달성」으로 접혔고 답은 「페이지는 열어두었으니
      본문 가격을 바로 읽어 완성하겠습니다」였다. 열어 놓고 안 읽은 페이지는 근거가 아니다 — 상한은 **짝의 가운데**가
      아니라 짝이 끝난 자리에서 끊는다. 한 번(그 읽기 하나)만이라 판이 길어지지 않는다.
    """
    if name not in _PAGE_READ_TOOLS or not steps:
        return False
    last = steps[-1]
    return bool(last.get("ok")) and str(last.get("tool") or "") in _PAGE_OPEN_TOOLS


def _fused_read_call(
    name: str,
    observation: dict[str, Any],
    calls: list[Any],
    current: Any,
    *,
    enabled: bool,
    available: Any,
    next_name: Any,
) -> bool:
    """열었으면 **같은 걸음에서** 읽을 것인가.

    ★ 실측(2026-09-03, 코워크 90판). 걸음의 58%가 `browser_open_result` +
      `browser_extract` 짝이고, 열기 355번 중 317번(89%)이 추출로 이어진다.
      그 사이의 모델 턴은 **아무것도 정하지 않는다** — 열었으면 읽는 것 말고
      할 일이 없다. 붙이면 걸음 중앙 12 → 7.

    조건을 함수로 뺀 이유: 원래는 루프 안에 인라인이었는데, 그러면 검사가
    「이 코드가 있다」밖에 못 본다. 도는지를 봐야 한다.
    """
    if name not in _PAGE_OPEN_TOOLS:
        return False
    if not observation.get("ok"):
        # 실패한 열기 뒤에 읽으면 **빈 화면을 읽는다.** 그건 근거가 아니다.
        return False
    if available is not None and _EXTRACT_TOOL not in available:
        return False
    position = _call_position(calls, current)
    upcoming = calls[position + 1 :] if position >= 0 else []
    following = next_name(upcoming[0]) if upcoming else ""
    # ★ **다음 호출이 또 열기면, 지금이 이 페이지를 읽을 수 있는 마지막 순간이다** (2026-10-06).
    #   열기는 같은 탭을 덮는다. 모델이 한 턴에 열기를 여럿 묶어 보내면 마지막 것만 남는다 — 운영 14일에 38판 · 98쪽이
    #   그렇게 덮였고 66쪽은 끝내 안 읽혔다. 이건 켜고 끄는 최적화(`enabled`)가 아니라 **읽을 수 있느냐**의 문제라
    #   설정과 무관하게, `browser_open` 에도 건다. 읽기는 부른 쪽이 이 호출 **바로 뒤에** 끼운다(맨 끝이 아니라).
    if following in _PAGE_OPEN_TOOLS:
        return True
    if not enabled or name != _OPEN_RESULT_TOOL:
        return False
    # 모델이 이미 추출을 이어 붙였으면 또 붙이지 않는다.
    return following != _EXTRACT_TOOL


def _forced_read_call(
    plan_results: list[tuple[Any, bool, str]],
    steps: list[dict[str, Any]],
    *,
    answer_admits_shortfall: bool = False,
) -> tuple[str, dict[str, Any]] | None:
    """개수 요구가 남았으면, **다음에 열거나 읽어야 할 한 칸.**

    한 번에 한 칸만 준다(커밋 사슬과 같은 이유). 순서는 언제나 열기 → 읽기다:
    열어 놓고 본문을 안 받으면 `_sources_actually_read` 가 세지 않으므로,
    "열기만 반복하고 개수는 그대로"인 판이 생긴다.

    ★ `answer_admits_shortfall` — **답이 계획보다 더 잘 안다** (2026-08-20 라이브).

        계획   3개 이상 직접 열어 읽기 = 3개 읽음 (충족)
        답     "현재까지 총 **1개**의 자료를 직접 읽었습니다. (1. 브랜드로그)
                … 아까 확인한 **검색 결과 목록**의 정보를 바탕으로 정리해 드립니다"

    다나와에서 rank 1·2·3 을 열었는데 그중 둘이 상품 상세가 아니라 **브랜드 소개
    페이지**였다. 계획 대조는 "서로 다른 주소 셋을 읽었다"만 세므로 충족으로 봤고,
    자비스는 스스로 미달이라고 답에 적었다. **두 층 중 정직한 쪽은 답이었다.**

    이 저장소가 이미 아는 모양이다 — "개수는 세는데 조건은 아무도 안 봤다"
    (정규직 공고 3개 사건, `plan.py`). 지금은 주소 개수는 세는데 그것이 상세
    페이지인지는 아무도 안 본다.

    그 자리를 여기서 메운다: 답이 스스로 모자라다고 말하면 개수 요구를 **미달로
    되돌리고** 한 칸을 더 연다. 무한히 돌지 않는 이유는 `_FORCED_READ_LIMIT` 이고,
    매번 **새 순위**를 열므로 같은 자리를 맴돌지도 않는다.

    "셋을 읽었지만 조건에 맞는 것이 둘"인 경우에도 답은 같다 — 더 열어 보는 것이
    맞다.
    """
    if not any(
        (not ok or answer_admits_shortfall)
        and (
            (
                getattr(req, "kind", "") == "count"
                and getattr(req, "source_scope", "") != "local"
            )
            or (
                getattr(req, "kind", "") == "observe"
                and getattr(req, "target", "") == "browser"
            )
        )
        for req, ok, _saw in plan_results
    ):
        return None

    opens = [s for s in steps if str(s.get("tool") or "") == _OPEN_RESULT_TOOL]
    if any(not s.get("ok") for s in opens):
        # 열어 보려다 거절당한 적이 있다(목록이 없는 화면이라든지). 모델이 안 부른
        # 것이 아니라 도구가 안 된 것이므로 대신 밀지 않는다.
        return None

    # 마지막으로 연 상세의 본문을 아직 안 받았으면, 그것부터 읽는다.
    last_open = max((i for i, s in enumerate(steps) if s in opens), default=-1)
    if last_open >= 0:
        read_after = any(
            str(s.get("tool") or "") in _TEXT_READ_TOOLS and s.get("ok")
            for s in steps[last_open + 1 :]
        )
        if not read_after:
            if any(
                str(s.get("tool") or "") == _EXTRACT_TOOL and not s.get("ok")
                for s in steps[last_open + 1 :]
            ):
                return None
            return _EXTRACT_TOOL, {}

    # 아직 안 열어 본 다음 순위. 순위는 1부터고, 이미 부른 것은 건너뛴다.
    tried = {
        int((s.get("arguments") or {}).get("rank") or 0)
        for s in opens
    }
    rank = next(n for n in range(1, 100) if n not in tried)
    return _OPEN_RESULT_TOOL, {"rank": rank}


def _redirect_redundant_extract(
    name: str,
    arguments: dict[str, Any],
    plan_results: list[tuple[Any, bool, str]],
    steps: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """같은 정적 본문을 또 읽으려 하면 아직 안 연 다음 결과로 옮긴다."""
    if name != _EXTRACT_TOOL or not steps:
        return name, arguments
    last = steps[-1]
    if not last.get("ok") or str(last.get("tool") or "") != _EXTRACT_TOOL:
        return name, arguments
    forced = _forced_read_call(plan_results, steps)
    if forced and forced[0] == _OPEN_RESULT_TOOL:
        return forced
    return name, arguments


# ── 자기 진단을 시켰는데 아무것도 안 보고 답하는 판 ──────────────────────────
#
# ★ 2026-08-21 실측. 라우팅을 고쳐 에이전트 루프까지는 들어왔는데 **걸음 0** 으로
# 끝났다. 답은 이랬다:
#
#     "논리 엔진 [정상] · 도구 가용성 [정상] · 데이터 무결성 [주의]"
#
# 아무것도 안 보고 지어냈다. 카메라 얘기를 지어낸 것보다 **나쁘다** — 그럴듯해서
# 안 믿을 이유가 없다.
#
# 오늘 같은 자리를 셋째로 만난다(커밋 · 상세 읽기 · 이것). 처방도 같다:
# **안내문은 안 먹는다. 결정론으로 박을 수 있으면 코드로 옮긴다.**
#
# 왜 지어내기가 아닌가 — `self_check` 는 **인자가 없어도 되는** 도구다(`organ` 은
# 비우면 전부 본다). 지어낼 자리가 아예 없다. 커밋 사슬·강제 읽기와 같은 근거다.
_SELF_CHECK_TOOL = "self_check"


def _forced_self_check_call(
    steps: list[dict[str, Any]], *, asked_for_self_check: bool
) -> tuple[str, dict[str, Any]] | None:
    """자기 진단을 시켰는데 한 번도 안 봤으면, **대신 본다.**

    이미 불렀으면 실패했더라도 다시 밀지 않는다 — 같은 실패가 반복될 뿐이다.
    커밋 쪽 `attempted` 규칙과 같다.
    """
    if not asked_for_self_check:
        return None
    if any(str(step.get("tool") or "") == _SELF_CHECK_TOOL for step in steps):
        return None
    return _SELF_CHECK_TOOL, {}


_OPEN_ASK = re.compile(r"열어|열고|열기|띄워|들어가|접속|이동해|\bopen\b|go to|navigate", re.I)
_OPEN_REFUSED = re.compile(r"열지\s*(?:마|말)|접속하지\s*(?:마|말)|열\s*필요\s*없|don'?t open", re.I)
_PROMPT_URL = re.compile(r"https?://[^\s)\]」'\"<>]+")


def _forced_open_call(prompt: str, steps: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """주소를 주고 열라고 했는데 **브라우저를 한 번도 안 썼으면** 대신 연다 (2026-09-29).

    ★ 같은 날 두 판: 「AWS 할당량 화면(주소)을 열고 …」에 걸음 0 으로 거절(e8603a4d), 「browser_open 으로 깃허브 조직 만들기
      (주소)를 열어라」에 걸음 0 으로 「화면이 열렸습니다 · 칸 이름은 …」을 **지어냈다**(2884740b). 과거 전 판 역검증: 이 조건에
      걸리는 판은 정확히 이 둘. 인자가 사람이 준 주소 하나라 지어낼 자리가 없다(강제 점검·커밋 사슬과 같은 근거).
      한 번이라도 브라우저를 불렀으면(실패했어도) 다시 밀지 않는다.
    """
    text = str(prompt or "")
    if any(str(step.get("tool") or "").startswith("browser_") for step in steps):
        return None
    urls = _PROMPT_URL.findall(text)
    if not urls or not _OPEN_ASK.search(text) or _OPEN_REFUSED.search(text):
        return None
    return "browser_open", {"url": urls[0].rstrip(".,")}


# 예고만 하고 끝나는 답변. 라우터(runtime._general_route)와 이 루프가 같은 판정을 쓴다.
#
# 도구 호출 없이 "지금 바로 조사하겠습니다. 잠시만 기다려 주십시오"라고 답하면, 그 말이
# 그대로 최종 답이 되고 아무 일도 일어나지 않는다. 2026-08-05에 마케팅 경쟁사 조사가
# 세 턴 연속 예고만 하고 실행 0회로 끝난 게 이것이다.
#
# 프롬프트로 "예고하지 마라"라고 적어 두는 것만으로는 부족했다(그 지시는 이미 있다).
# 말을 막을 수는 없어도 말로 끝나는 것은 막을 수 있다.
#
# 2026-08-05 2차: "말씀하시면 바로 실행하겠습니다!" 가 여기를 그냥 통과했다. 조사·검색
# 계열만 보고 있었기 때문이다. 실제로 무언가를 **하겠다**는 약속도 같은 종류의 실패다 —
# 편집기는 빈 채였고 화면에는 도구 이름 목록만 남았다.
#
# 대신 "~할까요?" 같은 질문은 일부러 넣지 않는다. 물어보는 것은 정당한 행동이고,
# 그것까지 되받으면 확인이 필요한 순간에 자비스가 묻지 못하게 된다.
PROMISED_ACTION = re.compile(
    r"(잠시만\s*기다|조금만\s*기다|바로\s*(확인|조사|검색|찾아|시작|진행|실행)|"
    r"지금\s*(바로\s*)?(확인|조사|검색|찾아)|"
    r"(조사|검색|확인|탐색|분석|정리)(해|해서)?\s*(보겠|오겠|드리겠|하겠)|"
    r"(실행|처리|반영|입력|등록|제출|저장)(해|해서)?\s*(보겠|드리겠|하겠)|"
    r"(찾아|알아)\s*(보겠|보고|오겠)|"
    r"(시작|진행)하겠습니다)"
)

# ★ 2026-09-26 A/B 벤치(위시켓 · 바꾼 뒤): 공고 4개를 다 읽고 나서 최종 답이
#   「목록 화면에서 … 더 찾기 위해 browser_load_more를 호출하겠습니다.」 **한 줄**이었다(도구 호출 없이).
#   PROMISED_ACTION 은 「호출」을 몰랐고, 이미 일을 한 판이라 되받기 조건(`_nothing_done_yet`)도 꺼져 있었다.
#   말투로 잡으면 또 뚫린다. 결정론으로 잡을 수 있는 표식이 있다: **사람에게 주는 답에 내부 도구 이름**이 있으면
#   그건 답이 아니라 다음 걸음 예고다. 표·목록이 있는 긴 답은 도구 이름을 설명으로 쓸 수 있으니 짧은 답만 본다.
_TOOLISH_WORD = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")  # 한글 조사가 붙어도(「…more를」) 잡는다
_ANSWER_BODY_LINE = re.compile(r"^\s*(?:\||\d+[.)]\s|[-*•]\s)", re.M)


def _announces_a_tool(answer: str, tool_names: frozenset[str] | set[str]) -> str:
    """짧은 답이 내부 도구 이름을 부르며 끝났으면 그 이름. 아니면 빈 문자열."""
    text = str(answer or "").strip()
    if not text or len(text) > 400 or _ANSWER_BODY_LINE.search(text):
        return ""
    for word in _TOOLISH_WORD.findall(text):
        if word in tool_names:
            return word
    return ""


_STEER_MARK = "[사용자가 작업 도중에 덧붙인 말]"


def _steer_notes_block(messages: list[dict[str, Any]]) -> str:
    """이 판에서 전한 덧붙인 말을 최종 정리 지시에 다시 싣는다 — 정리가 처음 질문만 보고 덧붙인 말을 빠뜨리지 않게."""
    notes = []
    for item in messages:
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str) and content.startswith(_STEER_MARK):
            notes.append(content[len(_STEER_MARK):].strip().split("\n\n", 1)[0].strip())
    if not notes:
        return ""
    return "\n\n[작업 도중 사용자가 덧붙인 말 — 이것도 함께 반영해라]\n" + "\n".join(f"- {note[:600]}" for note in notes)


# ── 여기가 그 사이트가 맞나 ──────────────────────────────────────────────────
#
# ★ 2026-08-13. 오늘 가장 위험한 고장이 여기서 나왔다.
#
# "다나와에서 무선마우스 상위 3개"에 자비스는 **실제로 갔고, 실제로 읽었고, 값도
# 진짜였다.** 그런데 다른 가게 값이었다. 검색 결과의 다나와 링크가 다나와의
# **광고 브리지**(`prod.danawa.com/bridge/loadingBridgePowerShopping.php`)였고,
# 열자마자 `smartstore.naver.com` 으로 넘어갔다. 거기서 읽은 판매가를 "다나와에서
# 확인한"이라고 답했다.
#
# 창 제목이 계속 "행복쇼핑의 시작 ! 다나와 (가격비교)"로 찍혀서 로그만 봐서는
# 정상으로 보였다. 지어낸 답보다 이게 더 나쁘다 — 근거가 실재해서 검증을 안 하게 된다.
#
# 판정은 **제목에 그 이름이 있나**로 한다. 사이트 목록에 기대지 않아 처음 보는 곳에도
# 그대로 걸린다(범용이 목적이므로 이게 중요하다). 오늘 세 판 전수 대조에서 이 신호가
# 스마트스토어 두 줄만 정확히 갈라냈다.
# **본문 글자를 손에 쥐여 주는** 도구. `browser_open`·`browser_open_result` 는 여기
# 없다 — 그건 이동이지 읽기가 아니다. 다나와 판이 정확히 그 차이로 샜다: 브리지
# **열기**는 다나와였고 **읽기**는 스마트스토어였다.
#: 검색 답 상자를 「읽은 본문」으로 셀 최소 글자 수 — 제목 한 줄이 아니라 값이 든 본문일 때만(`_sources_actually_read`).
_ANSWER_BOX_MIN_CHARS = 40

_TEXT_READ_TOOLS = frozenset(
    {
        "browser_extract", "browser_read",
        "local_read_text_file", "local_read_document",
        "google_drive_read",
        # ★ 유니티 레시피(2026-09-27)는 유니티가 에셋을 **실제로 열어 읽은** 결과다. 여기 없어서 18판 중 12판이
        #   맞게 해 놓고 답 끝에 「❌ 근거가 되는 대상 실제로 읽기 — 0개」를 달았다(검증된 판만 센다 — 아래).
        "unity_run_recipe",
        # 프로젝트 정보의 큰 파일 상위 10개도 실제로 잰 값이다(2026-10-01 테스터 시험 — evidence.MANIFEST 와 같이).
        "unity_project_info",
    }
)
