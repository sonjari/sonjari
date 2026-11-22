#!/bin/bash
# 손자리 Peekaboo 시험 2판 — 1판 실패 고침(앱은 번들 ID · 단축키는 cmd+n 꼴). 결과 ~/sonjari_peekaboo_test/out2/
P=~/sonjari_peekaboo_test/peekaboo-macos-arm64/peekaboo; O=~/sonjari_peekaboo_test/out2; rm -rf $O; mkdir -p $O; cd $O
now(){ python3 -c "import time;print(time.time())"; }
t(){ local n=$1; shift; local s=$(now); "$@" > $n.out 2>&1; local rc=$?; python3 -c "print('$n rc=$rc', round($(now)-$s,2),'초')" | tee -a log.txt; }
TE=com.apple.TextEdit; FI=com.apple.finder; CH=com.google.Chrome
echo "== 1 텍스트편집기"
t te_open open -b $TE; sleep 2
t te_new $P press cmd+n --app $TE --foreground --no-remote; sleep 1.5
t te_shot $P see --app $TE --json --path $O/te.png --no-remote
t te_type $P type "손자리 시험입니다 hello 123" --app $TE --no-remote
sleep 1; t te_tree $P see --app $TE --tree --no-screenshot --fresh --no-remote
echo "== 2 Finder: 응용 프로그램으로 갔다가 '뒤로' 누르기"
t fi_open open -b $FI; sleep 1
t fi_go $P press cmd+shift+a --app $FI --foreground --no-remote; sleep 1.5
t fi_tree1 $P see --app $FI --tree --no-screenshot --fresh --no-remote
t fi_back $P click "뒤로" --app $FI --no-remote; sleep 1.5
t fi_tree2 $P see --app $FI --tree --no-screenshot --fresh --no-remote
t fi_shot $P see --app $FI --json --path $O/fi.png --no-remote
echo "== 3 크롬: 읽기만"
t ch_tree $P see --app $CH --tree --no-screenshot --no-remote
echo "끝 — 결과 폴더 $O"
