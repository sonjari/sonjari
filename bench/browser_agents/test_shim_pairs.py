"""껍데기 시험 — 전사가 접혀도 앤트로픽이 받아들이는 모양이 나오는가.

★ 2026-09-07: 이 시험이 없어서 arm D 첫 두 판이 통째로 400 이었다. 그런데 겉으로는
   「8걸음 33.6초 부족신고 False」로 **성공처럼 보였다.** 어제 배운 그 모양 그대로다.

    python test_shim_pairs.py
"""
from __future__ import annotations

import sys

import ollama_anthropic_shim as shim


def ids_of(msgs, kind):
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if b.get("type") == kind:
                    out.append(b.get("id") or b.get("tool_use_id"))
    return out


def check(name, messages):
    _system, conv = shim.to_anthropic_messages(messages)
    uses = set(ids_of(conv, "tool_use"))
    results = [r for r in ids_of(conv, "tool_result")]
    orphans = [r for r in results if r not in uses]
    # 짝 없는 tool_result 가 하나라도 남으면 앤트로픽이 400 을 준다.
    assert not orphans, f"{name}: 짝 없는 tool_result {orphans}"
    # 빈 메시지도 400 이다.
    for m in conv:
        c = m.get("content")
        assert c, f"{name}: 빈 내용"
    assert conv and conv[0]["role"] == "user", f"{name}: 첫 메시지가 user 가 아님"
    print(f"  OK  {name}  (메시지 {len(conv)} · tool_use {len(uses)} · tool_result {len(results)})")


# ★ arm D 를 두 번 죽인 진짜 모양 — 한 턴에 도구 둘, 결과는 하나만 온다
check("한 턴에 도구 둘 + 다음 턴에도 호출", [
    {"role": "user", "content": "질문"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "a", "arguments": {}}},
        {"function": {"name": "b", "arguments": {}}}]},
    {"role": "tool", "tool_name": "a", "content": "결과a"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "c", "arguments": {}}}]},
    {"role": "tool", "tool_name": "c", "content": "결과c"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "d", "arguments": {}}}]},
])

check("긴 판: 호출-결과 열 바퀴", [{"role": "user", "content": "질문"}] + sum(
    [[{"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "t%d" % i, "arguments": {"n": i}}}]},
      {"role": "tool", "tool_name": "t%d" % i, "content": "결과%d" % i}] for i in range(10)], []))

# ★ arm D 를 세 번째로 죽인 모양 — 도구 결과 사이에 지시문이 끼어 있다
_m = [
    {"role": "user", "content": "질문"},
    {"role": "assistant", "content": "생각", "tool_calls": [
        {"function": {"name": "a", "arguments": {}}},
        {"function": {"name": "b", "arguments": {}}},
        {"function": {"name": "c", "arguments": {}}}]},
    {"role": "tool", "tool_name": "a", "content": "결과a"},
    {"role": "user", "content": "★ 지시문이 끼어든다"},
    {"role": "tool", "tool_name": "b", "content": "결과b"},
    {"role": "user", "content": "★ 또 끼어든다"},
    {"role": "tool", "tool_name": "c", "content": "결과c"},
]
check("도구 결과 사이에 글이 끼어듦", _m)
_s, _conv = shim.to_anthropic_messages(_m)
for _msg in _conv:
    _c = _msg.get("content")
    if isinstance(_c, list) and any(b.get("type") == "tool_result" for b in _c):
        _first_text = next((i for i, b in enumerate(_c) if b.get("type") != "tool_result"), len(_c))
        _last_res = max(i for i, b in enumerate(_c) if b.get("type") == "tool_result")
        assert _last_res < _first_text, "tool_result 가 맨 앞에 안 몰렸다"
print("  OK  tool_result 가 사용자 메시지 맨 앞에 몰린다")

print("껍데기 짝짓기 시험")

check("정상 한 바퀴", [
    {"role": "system", "content": "시스템"},
    {"role": "user", "content": "질문"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "browser_open", "arguments": {"url": "https://x"}}}]},
    {"role": "tool", "tool_name": "browser_open", "content": '{"ok":true}'},
])

# ★ 진짜 문제 — 전사가 접혀 tool_use 는 사라지고 결과만 남은 모양
check("전사가 접힘: 결과만 남음", [
    {"role": "system", "content": "시스템"},
    {"role": "user", "content": "질문"},
    {"role": "tool", "tool_name": "browser_extract", "content": '{"text":"본문"}'},
    {"role": "tool", "tool_name": "browser_extract", "content": '{"text":"본문2"}'},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "browser_open_result", "arguments": {"rank": 2}}}]},
    {"role": "tool", "tool_name": "browser_open_result", "content": '{"ok":true}'},
])

check("호출은 있는데 결과가 안 옴", [
    {"role": "user", "content": "질문"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "a", "arguments": {}}},
        {"function": {"name": "b", "arguments": {}}}]},
    {"role": "tool", "tool_name": "a", "content": "결과1"},
])

check("어시스턴트로 시작", [
    {"role": "assistant", "content": "먼저 말함"},
    {"role": "user", "content": "질문"},
])

check("빈 것 투성이", [
    {"role": "system", "content": "  "},
    {"role": "assistant", "content": ""},
    {"role": "user", "content": "질문"},
])

print("\n전부 통과.")
sys.exit(0)
