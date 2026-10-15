"""아는 비밀 값은 도구 결과에서 가린다 — 값으로 찾고, 모르는 것은 지우지 않는다 (2026-10-11).

양방향 표본이다: 가려야 하는 것과 **가리면 안 되는 것**을 같이 본다. `secret_scrub` 을 처음 만들 때 한쪽만 봐서
멀쩡한 글 74곳을 걷어 냈다 — 한 번 배운 값은 모든 도구 결과에서 가려지므로 여기서는 「배우지 않는 것」이 더 중요하다.

표본의 값은 전부 여기서 지어 붙인 글자다(실제 키의 앞부분도 쓰지 않는다).
"""
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

from alture_jarvis.known_secrets import (
    KnownSecrets,
    count_secret_looking,
    dotenv_like,
    learnable_value,
    marker,
    secret_name,
)

FAKE_KEY = "zz-" + "Qr7Lm2Xp" * 5            # 지어낸 값 — 어떤 서비스의 키 모양도 아니다
FAKE_PASSWORD = "Tr0ub4dor&3-fixture"


# --- 이름 ---------------------------------------------------------------------

def test_names_that_hold_secrets() -> None:
    for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "client-secret", "githubToken", "HF_TOKEN", "MY_PAT"):
        assert secret_name(name), name


def test_names_that_only_look_like_it() -> None:
    for name in ("KEYBOARD_LAYOUT", "TOKEN_URL", "PASSWORD_FILE", "AWS_ACCESS_KEY_ID", "SECRET_NAME", "PATH", "MONKEY",
                 "TOKENIZERS_PARALLELISM", "KEY_PREFIX", "SESSION_TTL"):
        assert not secret_name(name), name


def test_the_shells_working_directory_is_not_a_password() -> None:
    """`PWD` · `OLDPWD` 는 셸이 「지금 있는 폴더」를 적어 두는 변수다(2026-10-11 환경을 세다가 나옴).

    `PWD` 를 비밀번호의 줄임말로 읽어 그 값(폴더 경로)을 비밀로 배우면, 명령 결과에 나오는 그 경로가 전부 가려진다.
    줄임말로 쓰인 이름(`DB_PWD`)은 그대로 비밀이다.
    """
    for name in ("PWD", "OLDPWD", "pwd"):
        assert not secret_name(name), name
    for name in ("DB_PWD", "ADMIN_PWD", "MYSQL_PWD"):
        assert secret_name(name), name


# --- 배워도 되는 값 -------------------------------------------------------------

def test_values_we_refuse_to_learn() -> None:
    for value in ("", "short", "changeme", "${OPENAI_API_KEY}", "<your key here>", "12345678901", "development",
                  "https://api.example.com/v1/token", r"C:\Users\someone\keys\id_rsa", "/etc/ssl/private/key.pem",
                  " padded-value-123 ", "line one\nline two"):
        assert not learnable_value(value), repr(value)


def test_values_we_learn() -> None:
    for value in (FAKE_KEY, FAKE_PASSWORD, "postgres://app:Tr0ub4dor@db.internal/main", "correct horse battery"):
        assert learnable_value(value), value


# --- 가리기 ---------------------------------------------------------------------

def test_a_known_value_is_hidden_and_named() -> None:
    secrets = KnownSecrets()
    assert secrets.learn(FAKE_KEY, "OPENAI_API_KEY")

    text, count = secrets.hide(f"Error: request failed with key {FAKE_KEY} (401)\nretry with {FAKE_KEY}")

    assert count == 2 and FAKE_KEY not in text
    assert text.count(marker("OPENAI_API_KEY")) == 2
    assert "Error: request failed with key" in text and "(401)" in text, "값만 가리고 둘레의 글은 그대로다"


def test_common_encodings_of_the_value_are_hidden_too() -> None:
    secrets = KnownSecrets()
    secrets.learn(FAKE_PASSWORD, "DB_PASSWORD")
    encoded = base64.b64encode(FAKE_PASSWORD.encode()).decode()
    quoted = quote(FAKE_PASSWORD, safe="")

    text, count = secrets.hide(f"Authorization: Basic {encoded}\nurl=?p={quoted}")

    assert count == 2 and encoded not in text and quoted not in text


def test_text_without_known_values_comes_back_untouched() -> None:
    secrets = KnownSecrets()
    secrets.learn(FAKE_KEY, "OPENAI_API_KEY")
    plain = "tokens = re.compile(r'\\w+')\ncommit 9f2c1e7a4b8d0c3e5f6a7b8c9d0e1f2a3b4c5d6e\n\"password_fields\": len(found)"

    assert secrets.hide(plain) == (plain, 0), "모양이 비슷해도 아는 값이 아니면 건드리지 않는다"


def test_a_tool_result_is_walked_and_keeps_its_shape() -> None:
    secrets = KnownSecrets()
    secrets.learn(FAKE_KEY, "API_KEY")
    result = {"stdout": f"key={FAKE_KEY}", "exit_code": 0, "rows": [{"line": FAKE_KEY}, {"line": "ok"}], "pair": ("a", FAKE_KEY)}

    hidden, count = secrets.hide_in(result)

    assert count == 3 and FAKE_KEY not in repr(hidden)
    assert hidden["exit_code"] == 0 and hidden["rows"][1] == {"line": "ok"} and isinstance(hidden["pair"], tuple)
    assert set(hidden) == set(result), "칸 이름은 건드리지 않는다"


def test_a_clean_result_is_returned_as_is() -> None:
    secrets = KnownSecrets()
    secrets.learn(FAKE_KEY, "API_KEY")
    result = {"stdout": "3 passed", "rows": [{"line": "ok"}]}

    hidden, count = secrets.hide_in(result)

    assert count == 0 and hidden is result, "가린 것이 없으면 결과를 베끼지 않는다"


def test_pictures_are_passed_over() -> None:
    secrets = KnownSecrets()
    secrets.learn(FAKE_KEY, "API_KEY")
    picture = "data:image/jpeg;base64," + FAKE_KEY

    assert secrets.hide(picture) == (picture, 0)


def test_nothing_is_hidden_before_anything_is_learned() -> None:
    assert KnownSecrets().hide_in({"stdout": FAKE_KEY}) == ({"stdout": FAKE_KEY}, 0)


# --- 환경 · .env ----------------------------------------------------------------

def test_the_environment_teaches_only_secret_named_values() -> None:
    secrets = KnownSecrets()
    learned = secrets.learn_environment({
        "OPENAI_API_KEY": FAKE_KEY, "PATH": r"C:\Windows;C:\Tools", "TOKEN_URL": "https://auth.example.com/token",
        "KEYBOARD_LAYOUT": "korean-101-fixture", "DB_PASSWORD": "changeme", "GITHUB_TOKEN": "short",
    })

    assert learned == 1
    text, count = secrets.hide(f"{FAKE_KEY} korean-101-fixture https://auth.example.com/token changeme")
    assert count == 1 and "korean-101-fixture" in text and "changeme" in text


def test_dotenv_files_are_recognised_but_samples_are_not() -> None:
    for name in (".env", ".env.local", ".env.production", "staging.env"):
        assert dotenv_like(name), name
    for name in (".env.example", ".env.sample", "env.py", "environment.yml", ".envrc.template", "README.md"):
        assert not dotenv_like(name), name


def test_a_dotenv_file_teaches_its_secrets_and_leaves_plain_settings(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# 지어낸 설정\n"
        f"API_KEY=\"{FAKE_KEY}\"\n"
        "export DB_PASSWORD=" + FAKE_PASSWORD + "   # 줄 끝 주석\n"
        "PORT=3000\nDEBUG=true\nAPP_NAME=fixture-service\n"
        "PAYMENT=zz" + "9aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2u" + "\n",
        encoding="utf-8",
    )
    secrets = KnownSecrets()

    assert secrets.learn_dotenvs_in(tmp_path) == 3
    shown, count = secrets.hide((tmp_path / ".env").read_text(encoding="utf-8"))

    assert count == 3 and FAKE_KEY not in shown and FAKE_PASSWORD not in shown
    assert "PORT=3000" in shown and "APP_NAME=fixture-service" in shown, "비밀이 아닌 설정은 그대로 보인다"
    assert "API_KEY=" in shown and marker("API_KEY") in shown, "이름은 남는다 — 어떤 열쇠가 있는지는 알아야 한다"
    assert secrets.learn_dotenvs_in(tmp_path) == 0, "파일이 그대로면 다시 읽지 않는다"


def test_a_sample_dotenv_teaches_nothing(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(f"API_KEY={FAKE_KEY}\n", encoding="utf-8")
    secrets = KnownSecrets()

    assert secrets.learn_dotenvs_in(tmp_path) == 0 and len(secrets) == 0


# --- 모르는 것은 세기만 ----------------------------------------------------------

def test_random_looking_strings_are_counted_not_touched() -> None:
    unknown = "Zx9Kq2Lm8Vb4Nc7Xd1Fg6Hj3Pk5Rt0Ws" + "Ay8Bu2"
    text = f"token: {unknown}\nok"

    assert count_secret_looking(text) == 1


def test_hashes_ids_and_code_are_not_counted() -> None:
    text = "\n".join([
        "commit 9f2c1e7a4b8d0c3e5f6a7b8c9d0e1f2a3b4c5d6e",
        "id 123e4567-e89b-12d3-a456-426614174000",
        "integrity sha512-" + "Zx9Kq2Lm8Vb4Nc7Xd1Fg6Hj3Pk5Rt0Ws" * 2,
        "tests/test_research_jobs_see_the_same_tool_list_1007.py::test_the_whole_list_is_shown PASSED",
        "ConversationMemoryBackendWithAVeryLongClassNameIndeed",
        marker("OPENAI_API_KEY"),
    ])

    assert count_secret_looking(text) == 0
