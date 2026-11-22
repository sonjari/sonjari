# 맥 업데이트 시험 자료 (2026-11-16)

`tauri signer generate`(CLI 2.11.4)로 **시험용 임시 열쇠**를 만들어 `tauri signer sign` 으로 `tauri_data.bin` 에 서명한 것.
파이썬 확인기(`update_sign.py`)가 **실제 타우리 서명**을 읽는지 보는 자료다. 비밀 열쇠는 여기 없다(만든 자리에서 버림) —
이 공개 열쇠는 운영 열쇠가 아니며, 운영 `update_pubkey.txt` 에 넣으면 안 된다.
