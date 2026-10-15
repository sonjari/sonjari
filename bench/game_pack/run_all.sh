#!/bin/bash
# 게임 팩 3모델 비교: 시험용 백엔드(8097, 운영 8091 과 분리)를 모델마다 새로 띄워 과제 둘×3회.
# ★ 멈출 때는 이 스크립트·bench.py·8097 백엔드를 **모두** 끈다 — 2026-09-27 에 옛 스크립트가 살아남아
#   새 백엔드를 내리고 다음 모델을 올려, 두 벤치가 한 백엔드에 섞였다.
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HERE/work"; mkdir -p "$S"
[ -f "$S/token" ] || python -c "import secrets;print(secrets.token_urlsafe(24))" > "$S/token"
stop() { powershell -NoProfile -Command "\$c = Get-NetTCPConnection -LocalPort 8097 -State Listen -EA SilentlyContinue | Select-Object -First 1; if (\$c) { Stop-Process -Id \$c.OwningProcess -Force }"; sleep 3; }
for spec in "qwen3.6:35b-a3b 131072" "qwen3.5:9b 32768" "qwen3.5:4b 32768"; do
  set -- $spec
  stop
  (bash "$HERE/run_backend.sh" "$1" "$2" > "$S/backend_${1//[:.]/_}.log" 2>&1 &)
  for i in $(seq 1 60); do c=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8097/health); [ "$c" = "200" ] && break; sleep 3; done
  echo "== $1 up"
  cd "$HERE" && PYTHONIOENCODING=utf-8 python bench.py "$1" 3
done
stop
echo ALL_DONE
