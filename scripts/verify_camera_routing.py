from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient
from alture_jarvis.runtime import (
    CAMERA_DENIAL_PHRASES,
    LOOK_AT_CAMERA_TOOL,
    SYSTEM_PROMPT,
    VISUAL_ROUTING_PROMPT,
    JarvisRuntime,
)


CASES = [
    ("내 앞에 놓인 물건이 뭔지 확인해줘", True),
    ("지금 카메라에 사람이 몇 명 보이노", True),
    ("이거 무슨 색이고", True),
    ("저기 모니터 화면에 오류가 떠 있나", True),
    ("내 표정이 피곤해 보이나", True),
    ("책상 위 불이 켜져 있나", True),
    ("지금도 그 물건이 거기 있나", True),
    ("내가 들고 있는 게 뭔지 봐줘", True),
    ("사무실 문이 열려 있는지 알려줘", True),
    ("이 컵 안에 뭐가 보이노", True),
    ("GPU 최적화 결론을 두 문장으로 말해줘", False),
    ("파이썬 리스트와 튜플의 차이를 알려줘", False),
    ("아까 네가 설명한 구조를 다시 요약해줘", False),
    ("내 이름을 기억하고 있나", False),
    ("오늘 할 일을 우선순위로 정리해줘", False),
    ("카메라 보지 말고 일반적인 웹캠 원리만 설명해줘", False),
    ("빨간색과 보라색의 일반적인 차이는 뭐고", False),
    ("서울 날씨를 확인하려면 어떤 정보가 필요해", False),
    ("이 문장을 영어로 번역해줘: 오늘 회의는 세 시다", False),
    ("방금 답변을 두 문장으로 줄여줘", False),
]


def main() -> int:
    config = JarvisConfig.from_env()
    client = OllamaClient(config)
    passed = 0
    failures: list[str] = []
    for prompt, expected in CASES:
        tools = [] if any(phrase in prompt for phrase in CAMERA_DENIAL_PHRASES) else [LOOK_AT_CAMERA_TOOL]
        message = client.chat_message(
            prompt,
            system=f"{SYSTEM_PROMPT}\n{VISUAL_ROUTING_PROMPT}",
            tools=tools,
            temperature=0.0,
        )
        actual = JarvisRuntime._camera_tool_call(message) is not None
        ok = actual == expected
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} expected={expected} actual={actual} | {prompt}")
        if not ok:
            failures.append(prompt)
    print(f"camera-routing: {passed}/{len(CASES)} passed")
    if failures:
        print("failures:")
        for prompt in failures:
            print(f"- {prompt}")
    return 0 if passed >= 18 else 1


if __name__ == "__main__":
    raise SystemExit(main())
