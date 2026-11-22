#!/bin/bash
# 손자리 Peekaboo 시험 1판 — 결과는 ~/sonjari_peekaboo_test/out1/ 에 남는다(저장 · 전송 없음)
P=~/sonjari_peekaboo_test/peekaboo-macos-arm64/peekaboo; O=~/sonjari_peekaboo_test/out1; rm -rf $O; mkdir -p $O; cd $O
t(){ local n=$1; shift; local s=$(python3 -c "import time;print(time.time())"); "$@" > $n.out 2>&1; local rc=$?; echo "$n rc=$rc $(echo "$(python3 -c "import time;print(time.time())") - $s" | bc)초" | tee -a log.txt; }
echo "== 1 텍스트편집기: 새 문서 열고 한글 타자"
t te_launch $P app launch TextEdit --no-remote
sleep 2; t te_new $P press cmd,n --app TextEdit --no-remote; sleep 1
t te_see1 $P see --app TextEdit --json --path $O/te1.png --no-remote
t te_type $P type "손자리 시험입니다 hello 123" --app TextEdit --no-remote
sleep 1; t te_see2 $P see --app TextEdit --tree --no-screenshot --no-remote
echo "== 2 Finder: 화면 읽고 '다운로드' 누르기"
t fi_launch $P app launch Finder --no-remote; sleep 1
t fi_see $P see --app Finder --json --path $O/fi.png --no-remote
t fi_click $P click "다운로드" --app Finder --no-remote
sleep 1; t fi_see2 $P see --app Finder --tree --no-screenshot --no-remote
echo "== 3 크롬: 화면 읽기만(누르지 않음)"
t ch_see $P see --app "Google Chrome" --json --path $O/ch.png --no-remote
echo "끝 — 결과 폴더 $O"
