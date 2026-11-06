# animator/ 안의 남의 코드 · 모델 출처

## 옮겨 온 코드

`pose_onnx.py` 의 전처리 · 후처리는 아래 코드를 줄여 옮겼다.

- **rtmlib 0.0.16** — Tau-J, https://github.com/Tau-J/rtmlib
- 라이선스: Apache License 2.0
- 옮긴 파일: `tools/base.py` · `tools/object_detection/yolox.py` · `tools/pose_estimation/rtmpose.py` · `rtmpose3d.py` · `pre_processings.py` · `post_processings.py`
- 바꾼 것:
  - 상자 좌표를 64비트로 계산한다.
  - 사람 찾기 출력은 [N, 5] 꼴만 받는다.
  - 내려받기 · opencv · openvino 백엔드를 뺐다.
- 까닭: rtmlib 은 `opencv-contrib-python` 을 같이 요구한다. 이 꾸러미가 손자리 운영 · 스토어 판의 `opencv-python` 과 부딪친다.
- 대조: 2026-11-03 같은 사진 20장으로 2D · 3D 관절이 rtmlib 과 같은지 확인했다. 상자 좌표 정밀도를 맞추면 차이는 0 이었다.

## 모델 파일 — 손자리에 넣지 않는다

모델 파일은 사람이 안내문을 읽고 동의한 뒤에만 `parts.py` 가 받는다. 받은 뒤에는 sha256 지문을 확인한다.

| 부품 | 받는 곳 | 표기 라이선스 |
|---|---|---|
| YOLOX-m HumanArt(사람 찾기) | download.openmmlab.com | Apache-2.0 |
| RTMPose-m body7(2D 관절) | download.openmmlab.com | Apache-2.0 |
| RTMW3D-x(3D 관절) | huggingface.co/Soykaf/RTMW3D-x (개인 계정이 올린 판) | Apache-2.0 표기 |

세 모델 모두 학습 데이터 일부가 연구 · 비상업 조건이다.

- RTMW3D 의 H3WB 는 「이미지는 Human3.6M 라이선스를 따른다」고 적혀 있다.
- body7 에는 AI Challenger · PoseTrack 등이 들어 있다.

이렇게 학습된 모델의 결과를 상업 작업에 써도 되는지는 정리되지 않았다. 그래서 2026-11-03 대표가 이렇게 정했다.

- 손자리가 모델을 배포하지 않는다.
- 사용자가 직접 받는다.
- 영상에서 나온 동작은 「영상 변환 초안」으로 표시한다.
