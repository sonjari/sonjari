"""검증 스크립트가 쓰는 일회용 폴더 — 진짜로 지워지는 것까지가 일이다.

## 왜 있나

2026-08-08 에 `%TEMP%` 에 `jarvis-*` 폴더가 **31개 / 691MB** 쌓여 있었다. 8월 1일부터
실행마다 20~30MB 씩 남은 것이다. 실행 PC(여수 사무실)는 원격으로만 닿으므로 이런 건
사람이 눈치채기 전까지 계속 자란다.

원인이 두 가지였고, 둘째가 이 파일이 있는 이유다.

**하나 — 아예 안 지우는 것.** `verify_blog_results` · `verify_deep_search` 가
`mkdtemp()` 만 하고 끝났다.

**둘 — 지우는 척하는 것.** 나머지 넷은 `TemporaryDirectory(ignore_cleanup_errors=True)`
를 썼다. 정리를 시도하긴 하는데, 크로미움이 프로필 파일을 아직 쥐고 있으면 실패하고
그 실패를 **조용히 삼킨다.** 겉보기엔 정리 코드가 있으니 아무도 의심하지 않는다.
`jarvis-agent-e2e-*` · `jarvis-uivision-*` · `jarvis-generic-*` 이 그렇게 남았다.

둘째가 이 저장소가 반복해서 데인 그 고장이다 — **조용한 성공.** 실패를 삼키는 정리는
정리가 아니라 정리한다는 주장일 뿐이다.

## 그래서 어떻게 하나

`worker.stop()` 이 돌아와도 크로미움 프로세스는 아직 죽는 중이라 파일 핸들이 남아
있다. 잠깐 기다렸다 다시 시도하면 대개 풀린다. 끝까지 안 되면 **얼마가 남았는지
말한다** — 삼키지 않는다. 그것만이 이 폴더가 다시 쌓이기 시작했을 때 알아챌 방법이다.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _size_mb(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return round(total / (1024 * 1024))


def purge(root: Path, *, attempts: int = 5, pause: float = 0.6) -> bool:
    """지워질 때까지 몇 번 다시 해 본다. 끝내 못 지우면 그렇다고 말하고 False.

    예외를 밖으로 내보내지 않는 것은 맞다 — 검증 스크립트가 뒷정리 때문에 실패로
    끝나면 정작 재려던 것의 판정이 묻힌다. 하지만 **조용히** 넘어가지는 않는다.
    """
    for attempt in range(1, max(1, attempts) + 1):
        if not root.exists():
            return True
        try:
            shutil.rmtree(root)
            return True
        except OSError:
            if attempt < attempts:
                # 브라우저가 프로필 파일을 놓을 때까지. stop() 이 돌아온 것과
                # 프로세스가 실제로 죽은 것은 다르다.
                time.sleep(pause)
    left = _size_mb(root)
    print(f"  ⚠ 임시 폴더를 못 지웠다: {root} ({left}MB) — 쌓이면 사람이 지워야 한다")
    return False


@contextmanager
def scratch_root(prefix: str) -> Iterator[Path]:
    """일회용 폴더를 주고, 나갈 때 **정말로** 지운다."""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield root
    finally:
        purge(root)
