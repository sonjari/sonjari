"""까닭을 가르는 사실 둘이 실제 부르기 흐름에서 맞게 서고 지워지는가 (2026-11-13).

- 짧은 확인 부르기(도구 몇 개 · 짧은 지침)를 기록하면 `last_small` · 일하는 부르기면 아니다
- 다른 기기 부르기(`note_outside_call`)가 들어오면 `outside` · 우리 부르기를 하나 기록하면 지워진다
"""

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


def _client(tmp_path) -> OllamaClient:
    return OllamaClient(JarvisConfig(data_dir=tmp_path))


def _body(tools: int, system_chars: int) -> dict:
    return {"model": "m", "messages": [{"role": "system", "content": "가" * system_chars}, {"role": "user", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": f"t{i}"}} for i in range(tools)]}


def test_short_check_then_work_call(tmp_path) -> None:
    client = _client(tmp_path)
    client._log_call(_body(4, 4000), {}, 0.1)
    assert client._reread_facts() == {"last_small": True, "outside": False, "current_small": False}
    assert client._reread_facts(_body(4, 4000))["current_small"] is True
    assert client._reread_facts(_body(114, 17000))["current_small"] is False
    client._log_call(_body(114, 17000), {}, 0.1)
    assert client._reread_facts()["last_small"] is False


def test_outside_call_is_remembered_until_our_next_call(tmp_path) -> None:
    client = _client(tmp_path)
    client._log_call(_body(114, 17000), {}, 0.1)
    client.note_outside_call()
    assert client._reread_facts()["outside"] is True
    client._log_call(_body(114, 17000), {}, 0.1)
    assert client._reread_facts()["outside"] is False
