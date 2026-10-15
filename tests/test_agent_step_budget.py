"""시킨 일의 **크기**에 맞춰 걸음 예산을 잡는다 — 그리고 왜 끝났는지 남긴다.

2026-08-12 실측. "공고 4개는 직접 열어 읽어라"를 일곱 번 시켰는데 한 번도 4개를
못 채웠다. 끈기가 모자란 줄 알았는데 산수가 안 맞았다:

    드라이브 검색+읽기 2 · 검색 1~2 · 공고 4개 × (열기+추출) 8  =  11~12걸음
    기본 예산                                                    =  12걸음

여유가 0이다. 실패 한 번, 헛클릭 한 번이면 개수를 절대 못 채운다. 실제 7차는
11걸음을 쓰고 3개만 읽었다. **예산이 모자란 것을 모델 탓으로 읽을 뻔했다.**

그리고 그걸 알아내려고 코드를 뒤져야 했다 — 끝난 판을 놓고 "왜 끝났나"를 물을
곳이 없었기 때문이다(`agent_wrapping_up` 은 이벤트로만 나가고 장부에 안 남는다).
그래서 `stop_reason` 을 검증 블록에 적는다.

여기서 지키는 것 넷:

  1. "N개 읽어라"면 N에 비례해 예산을 준다
  2. 개수 요구가 없으면 예전 그대로 — 모르는 일을 크게 잡지 않는다
  3. 자율 상한(30걸음)을 넘지 않는다
  4. 끝난 이유를 답과 함께 남긴다
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.plan import extract as extract_plan


def _budget(tmp_path: Path, prompt: str) -> int:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
    )
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.config = config  # type: ignore[attr-defined]
    return agent._step_budget(extract_plan(prompt))


def test_four_postings_get_more_than_the_flat_twelve(tmp_path: Path) -> None:
    """4개 × (열기+추출) = 8걸음. 준비까지 하면 12에 여유가 없다."""
    budget = _budget(tmp_path, "공고를 최소 4개는 직접 열어서 읽고 정리해줘")

    assert budget >= 14, f"4개를 읽으라는데 예산이 {budget}걸음이면 못 채운다"


def test_ten_postings_get_even_more(tmp_path: Path) -> None:
    budget = _budget(tmp_path, "블로그 10개는 직접 들어가서 읽어줘")

    assert budget >= 26


def test_the_autonomous_ceiling_is_never_exceeded(tmp_path: Path) -> None:
    """예산이 커도 자율 상한을 넘지 않는다 — 헛도는 판이 길어지기만 한다.

    ★ 2026-09-01: 상한을 숫자로 박아 뒀더니, 상한을 30→48 로 올릴 때 **이 검사가
      틀린 이유로 실패했다.** 재는 것은 「상한이 얼마인가」가 아니라 「예산이 상한을
      넘지 않는가」다. 설정을 보게 고쳤다 — 그래야 상한을 조정해도 의미가 유지된다.
    """
    from alture_jarvis.config import JarvisConfig

    ceiling = JarvisConfig.from_env().agent_autonomous_max_steps
    budget = _budget(tmp_path, "공고를 30개는 직접 열어서 읽어줘")

    assert budget <= ceiling


def test_a_request_without_a_count_keeps_the_old_budget(tmp_path: Path) -> None:
    """모르는 일을 크게 잡지 않는다. 큰 예산은 헛도는 판을 길게 만든다(11.7분 판)."""
    budget = _budget(tmp_path, "오늘 서울 날씨 알려줘")

    assert budget == 12


def test_a_duration_is_not_a_count(tmp_path: Path) -> None:
    """'3박4일'·'4개월'을 개수로 읽으면 엉뚱한 예산이 잡힌다."""
    budget = _budget(tmp_path, "제주도 3박4일 여행 경비 정리해줘")

    assert budget == 12
