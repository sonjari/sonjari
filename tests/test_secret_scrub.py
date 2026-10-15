"""비밀 걷어 내기 — **양방향** 역검증 (전략안 §43, P4).

이 저장소는 게이트를 붙였다 오탐으로 적재율을 96%→19% 로 떨어뜨린 적이 있다.
그래서 「잡아야 할 것을 다 잡는다」와 「건드리면 안 되는 것을 하나도 안 건드린다」를
같은 무게로 시험한다.

★ 표본은 전부 **지어낸 가짜**다. 그리고 실행 중에 조립한다 — 진짜 키 모양의 글자가
  파일에 그대로 있으면 GitHub 푸시 보호가 막고, 복사해 쓰는 사람이 생긴다.
"""

from __future__ import annotations

import random

import pytest

from alture_jarvis.secret_scrub import looks_random, marker, scrub

_RNG = random.Random(20260914)
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _fake(n: int, alphabet: str = _ALNUM) -> str:
    return "".join(_RNG.choice(alphabet) for _ in range(n))


FAKE_RANDOM = _fake(43)  # 운영 API 키와 같은 길이·모양의 가짜

MUST_CATCH = [
    ("sk-" + "ant-api03-" + _fake(40), "API 키"),
    ("sk-" + "proj-" + _fake(48), "API 키"),
    ("gh" + "p_" + _fake(36), "GitHub 토큰"),
    ("github" + "_pat_" + _fake(22) + "_" + _fake(59), "GitHub 토큰"),
    ("xo" + "xb-" + "1234567890-" + _fake(24), "Slack 토큰"),
    ("AK" + "IA" + _fake(16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"), "AWS 키"),
    ("AI" + "za" + _fake(35), "Google API 키"),
    ("live" + "_sk_" + _fake(24), "결제 키"),
    ("ey" + "J" + _fake(20) + ".ey" + "J" + _fake(30) + "." + _fake(43), "토큰(JWT)"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\n" + _fake(70) + "\n" + _fake(70) + "\n-----END OPENSSH PRIVATE KEY-----",
     "개인 키"),
]


@pytest.mark.parametrize(("secret", "label"), MUST_CATCH, ids=[label for _, label in MUST_CATCH])
def test_known_shapes_are_caught_and_never_echoed(secret: str, label: str) -> None:
    result = scrub(f"배포 전에 이걸로 확인한다: {secret} 끝.")
    assert secret not in result["text"]
    assert marker(label) in result["text"]
    assert all(secret not in seg["v"] for seg in result["segments"])
    assert result["secret_total"] == 1


@pytest.mark.parametrize(
    ("line", "keeps"),
    [
        (f'curl -s https://api.example.com/v1/status -H "X-EXAMPLE-API-KEY: {FAKE_RANDOM}"', "X-EXAMPLE-API-KEY"),
        (f"Authorization: Bearer {_fake(40)}", "Authorization: Bearer"),
        (f"WORKER_AUTH_TOKEN={_fake(43)}  # 토큰만 (prefix 없이)", "WORKER_AUTH_TOKEN="),
        (f'{{"client_secret": "{_fake(24)}"}}', "client_secret"),
        (f"password = {_fake(12)}", "password = "),
        (f"비밀번호: {_fake(10)}", "비밀번호: "),
        (f"https://admin:{_fake(12)}@db.example.com/prod", "https://admin:"),
        (f"https://hooks.example.com/run?token={_fake(30)}&mode=1", "&mode=1"),
    ],
)
def test_header_and_assignment_keep_the_name_and_drop_the_value(line: str, keeps: str) -> None:
    result = scrub(line)
    assert keeps in result["text"], result["text"]
    assert result["secret_total"] == 1, result["text"]


def test_a_bare_random_token_is_caught() -> None:
    result = scrub(f"키는 `{FAKE_RANDOM}` 이다")
    assert FAKE_RANDOM not in result["text"]
    assert result["secrets"] == {"긴 무작위 문자열": 1}


# ── 건드리면 안 되는 것 ─────────────────────────────────────────────────────────
MUST_NOT_TOUCH = [
    "커밋 0892ab4983e9 에서 고쳤다",
    "전체 해시 28aeb7880d33f1c2a9b8e7d6c5b4a3928170615f",
    "모델 digest sha256:" + "a3f1" * 16,
    "Notion Client ID: 11111111-2222-4333-8444-555555555555",
    r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider",
    "tools/alture-jarvis/bench/browser_agents/results/content_grade_20260912_r3_77pct.json",
    "파이썬 3.11.9 · 버전 v1.2.3-beta.4 · Ollama 0.12.10",
    "| 컨테이너 | 역할 | 건드려도 되는가 |\n|---|---|---|\n| `web_server-app-proxy-1` | 실제 운영 API | ✅ |",
    "```python\ndef test_the_same_file_under_our_existing_name_keeps_our_name() -> None:\n    pass\n```",
    "class ConversationMemoryRetrievalBackend2 는 아직 없다",
    "RoboMetaFit-Alture-Jarvis 작업 스케줄러 · OLLAMA_MAX_LOADED_MODELS=1 · num_ctx: 65536",
    "max_tokens: 1000000 로 두면 된다",
    "API_KEY=${OPENAI_API_KEY} 처럼 환경변수로 받는다",
    "Authorization: Bearer ${token}",
    "password: <your password>",
    "api_key = os.environ[\"ANTHROPIC_API_KEY\"]",
    "token = config.control_token",
    'headers.set("X-JARVIS-TOKEN", bootstrap.controlToken);',
    "`NAS_SSH_PRIVATE_KEY` | GitHub Actions → NAS SSH 접속용 (`~/.ssh/id_github_actions`)",
    "?mode=setup&setupFixture=4080-laptop 로 띄운다",
    "https://api.robometafit.com/v1/admin/infra/status",
    "눈금이 먼저 틀린다. 새 규칙은 과거 판에 대 보고 불일치를 읽는다.",
    "base64 로 감싸라: python -c 'import base64,sys; exec(base64.b64decode(sys.argv[1]).decode())'",
    # ↓ 실제 파일 역검증(2026-09-14)에서 잘못 걷었던 모양 셋
    "https://www.example.co.kr/search?type=ACCOMMODATION\n    ?filter=" + "7" + _fake(69),
    "sudo sed -i 's|^TOSS_SECRET_KEY=.*|TOSS_SECRET_KEY=NEW|' .env",
    'TOKEN_URI = "https://oauth2.example.com/token"',
    # ↓ 역검증에서 코드 속 이름을 비밀로 착각했던 모양들
    "tokens = re.compile(r'\\w+')",
    'headers={"X-JARVIS-TOKEN": self.control_token})',
    '"password_fields": len(fields),',
    "const thinkingTokens = usage?.thinking ?? 0;",
]


@pytest.mark.parametrize("text", MUST_NOT_TOUCH)
def test_ordinary_repository_text_is_left_alone(text: str) -> None:
    result = scrub(text)
    assert result["secret_total"] == 0, result["secrets"]
    assert result["text"] == text


@pytest.mark.parametrize(
    "token",
    ["ConversationMemoryRetrievalBackend2Extra", "a3f1" * 16, "test_the_same_file_under_our_existing_name"],
)
def test_long_identifiers_do_not_look_random(token: str) -> None:
    assert not looks_random(token)


# ── 연락처: 표시만, 걷을지는 사람이 ────────────────────────────────────────────────
def test_contacts_are_marked_not_removed_unless_asked() -> None:
    text = "문의는 someone@example.com 또는 010-1234-5678 로"
    kept = scrub(text)
    assert kept["text"] == text
    assert kept["contacts"] == {"이메일": 1, "전화번호": 1}
    assert kept["secret_total"] == 0
    assert [seg["t"] for seg in kept["segments"]].count("contact") == 2

    removed = scrub(text, redact_contacts=True)
    assert "someone@example.com" not in removed["text"] and "010-1234-5678" not in removed["text"]
    assert removed["secret_total"] == 2


def test_segments_rebuild_the_scrubbed_text_exactly() -> None:
    text = f"앞 {FAKE_RANDOM} 가운데 x@example.com 뒤"
    result = scrub(text)
    assert "".join(seg["v"] for seg in result["segments"]) == result["text"]


def test_one_secret_hit_by_two_rules_is_counted_once() -> None:
    """머리줄 규칙과 무작위 문자열 규칙이 같은 값을 잡아도 하나다."""
    result = scrub(f"X-EXAMPLE-API-KEY: {FAKE_RANDOM}")
    assert result["secret_total"] == 1
