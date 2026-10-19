"""윈도우 경로가 든 명령 한 줄을 쪼갤 때 역슬래시를 지우지 않는다 (2026-10-19 맡기기 check 거절)."""

import os

import pytest

from alture_jarvis.local_computer import split_command_line

pytestmark = pytest.mark.skipif(os.name != "nt", reason="윈도우 경로 규칙")


def test_a_windows_python_path_survives():
    parts = split_command_line(r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe -m pytest -q tests/test_x.py")
    assert parts[0] == r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe"
    assert parts[1:] == ["-m", "pytest", "-q", "tests/test_x.py"]


def test_quoted_pieces_lose_only_their_quotes():
    parts = split_command_line(r'''"C:\Program Files\x\python.exe" -k "a and b" 'one two' ''')
    assert parts == [r"C:\Program Files\x\python.exe", "-k", "a and b", "one two"]


def test_forward_slashes_and_plain_words_are_unchanged():
    assert split_command_line("C:/a/b/python.exe -m pytest -q") == ["C:/a/b/python.exe", "-m", "pytest", "-q"]


def test_an_unclosed_quote_still_raises():
    with pytest.raises(ValueError):
        split_command_line('python -c "print(1)')
