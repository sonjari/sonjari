"""메신저(디스코드)로 이 PC 의 손자리에게 일을 시키는 **따로 도는 작은 프로세스** (2026-10-17).

## 무엇이고 왜 따로인가

손자리 본체(8091)는 그대로 두고, 이 패키지가 디스코드에 **밖으로만** 붙는다(들어오는 포트를 열지 않는다).
받은 말은 본체의 `/v1/chat` 에 맡기고, `/v1/jobs/{id}` 를 물어 진행과 답을 디스코드로 돌려준다.
MCP 다리(`mcp_server.py`)와 같은 이유다 — 런타임을 새로 띄우면 승인 대기열·기억·브라우저가 둘로 갈린다.

    python -m alture_jarvis.messaging setup   # 봇 토큰 확인 · 초대 링크 · 허용 목록
    python -m alture_jarvis.messaging         # 다리 실행

설계는 Hermes Agent(NousResearch, MIT)의 디스코드 어댑터 · 온보딩을 본떴다. 옮겨 온 코드는 `base.py` 머리에
출처와 라이선스를 적었다(`packaging/public/NOTICE` 에도 한 줄).

★ 이 패키지는 `discord` 를 **함수 안에서만** 부른다. 본체 · 나머지 시험은 discord.py 없이 돈다.
"""
