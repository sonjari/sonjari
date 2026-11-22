#!/bin/bash
# 손자리 Peekaboo 시험 3판 — 새 「제목 없음」 창을 정확히 집었을 때만 타자. 못 찾으면 치지 않는다.
P=~/sonjari_peekaboo_test/peekaboo-macos-arm64/peekaboo; O=~/sonjari_peekaboo_test/out3; rm -rf $O; mkdir -p $O; cd $O
TE=com.apple.TextEdit
open -b $TE; sleep 1.5
$P press cmd+n --app $TE --foreground --no-remote > new.out 2>&1; sleep 1.5
$P window list --app $TE --json --no-remote > wins.json 2>&1
WID=$(python3 - <<'PY'
import json,unicodedata as U
N=lambda x:U.normalize("NFC",str(x))
d=json.load(open("wins.json")); d=d.get("data",d)
ws=d.get("windows",d) if isinstance(d,dict) else d
c=[w for w in ws if N(w.get("window_title",w.get("title",""))).startswith(("무제","제목 없음","Untitled"))]
c.sort(key=lambda w:(not w.get("is_frontmost",False),-int(w.get("window_id",0) or 0)))
print(c[0].get("window_id",c[0].get("id")) if c else "")
PY
)
echo "새 창 id=[$WID]" | tee log.txt
if [ -z "$WID" ]; then echo "새 창을 못 찾음 — 타자 안 함" | tee -a log.txt; exit 0; fi
$P see --window-id $WID --json --path $O/before.png --no-remote > see1.json 2>&1
SNAP=$(python3 -c "import json,unicodedata as U;d=json.load(open('see1.json'));d=d.get('data',d);print(d.get('snapshot_id',''),U.normalize('NFC',d.get('window_title','')),sep='|')")
echo "찍은 창: $SNAP" | tee -a log.txt
case "$SNAP" in *"|무제"*|*"|제목 없음"*|*"|Untitled"*) ;; *) echo "찍은 창이 새 문서가 아님 — 타자 안 함" | tee -a log.txt; exit 0;; esac
$P type "손자리 시험입니다 hello 123" --snapshot "${SNAP%%|*}" --no-remote > type.out 2>&1; echo "타자 rc=$?" | tee -a log.txt
sleep 1; $P see --window-id $WID --tree --no-screenshot --fresh --no-remote 2>&1 | python3 -c "import sys,unicodedata as U;sys.stdout.write(U.normalize('NFC',sys.stdin.read()))" > after.txt
grep -q "손자리 시험입니다 hello 123" after.txt && echo "확인: 새 문서에 글자 들어감" | tee -a log.txt || echo "확인 실패: 글자 안 보임" | tee -a log.txt
echo "끝"
