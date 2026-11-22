# Peekaboo v4.9.8 실측 출력 (2026-11-16 · 맥미니 · 대표 터미널)

맥 `~/sonjari_peekaboo_test/out1~3` 와 `run1~3.sh` 를 **읽기만 해서** 가져왔다(scp). `tests/test_mac_automation.py` 가 이 출력을 그대로 맞댄다.

- `out3/wins.json` — `window list --app com.apple.TextEdit --json`. 창 이름이 **NFD**(「무제 2」 길이 6).
- `out3/see1.json` — `see --window-id 3785 --json`. `target_receipt` 는 `data` **밖**(맨 위)에 있다.
- `out3/type.out` · `after.txt` — 타자 rc=1(「확인 안 됨」)인데 다시 읽으니 글자가 들어가 있었다.
- `out1/te_see1.out` — `--app TextEdit` 로 찍었을 때 WINDOW_NOT_FOUND, 후보에 기존 문서 창 `버그막이_설계.md`.
- `out1/te_new.out` — `cmd,n` 거절(키는 `+` 로 잇는다).

**뺀 것(개인 정보)**: Finder 트리(다운로드 폴더 파일 이름) · 크롬 트리(탭 · 북마크) · `버그막이_설계.md` 본문이 찍힌 텍스트 편집기 트리 둘
(`out1/te_see2.out` · `out2/te_tree.out` — 시험 글자는 그 문서에 들어가지 않았음을 빼기 전에 확인). 맥 홈 경로는 `/Users/tester` 로 바꿨다.
