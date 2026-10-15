#!/bin/bash
# 사용: run_backend.sh <모델> <num_ctx>
S="$(cd "$(dirname "$0")" && pwd)/work"; mkdir -p "$S"
export PYTHONPATH="C:/work/monorepo/tools/alture-jarvis/src"
export JARVIS_RUNTIME_ROOT="$S/root" JARVIS_DATA_DIR="$S/data_${1//[:.]/_}" JARVIS_OUTPUT_DIR="$S/out"
export JARVIS_PORT=8097 JARVIS_CONTROL_TOKEN="$(cat "$S/token")"
export JARVIS_BROWSER_CDP_PORT=9335 JARVIS_BROWSER_PROFILE_DIR="$S/profile"
export JARVIS_OLLAMA_MODEL="$1" JARVIS_OLLAMA_CHAT_MODEL="$1" JARVIS_OLLAMA_CODE_MODEL="$1"
export JARVIS_OLLAMA_NUM_CTX="$2" JARVIS_OLLAMA_CODE_NUM_CTX="$2"
export JARVIS_VOICE_ENABLED=0 JARVIS_TTS_ENABLED=0 JARVIS_HOTKEY_ENABLED=0 JARVIS_SCHEDULER_ENABLED=0
cd "C:/work/monorepo/tools/alture-jarvis"
exec "C:/work/monorepo/tools/alture-jarvis/.venv/Scripts/python.exe" -m alture_jarvis
