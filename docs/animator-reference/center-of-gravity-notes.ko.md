> 2026-11-19 손자리가 웹 4곳을 읽고 정리한 것. 확인 날짜 2026-11-19.
> **검수:** 2번(Animator Island Part 4)과 4번(Cursa)은 클로드가 원문에서 같은 내용이 있음을 확인함. 1번(Weight Gain and Loss)과 3번(AWN)은 원문 확인 전 — 손자리 요약 그대로.
> 아래 「포즈 고칠 때 규칙」은 손자리가 만든 한 줄이며 큰누나 기준이 아님. 큰누나 원칙은 별도 메모(COM · Spine · Head 키 동일 프레임, 무게중심 이동이 핵심, COM 곡선) 참고.
> 출처: https://www.animatorisland.com/physics-in-animation-weight-gain-and-loss · https://www.animatorisland.com/principles-of-animation-physics-part-4 · https://www.awn.com/print/blog/animation-lesson-center-gravity-part-two · https://cursa.app/en/page/character-animation-starter-kit-balance-center-of-gravity-and-ground-contact

# 애니메이션 무게중심 자료

## 1. Weight Gain and Loss (Animator Island)

**핵심 세 줄:**
- 캐릭터가 중력과 같은 방향으로 가속하면 무게가 줄고, 중력과 반대 방향으로 가속하면 무게가 늘어난다.
- 중력과 같은 방향: 위로 올라가며 속도가 줄거나(상승 감속), 아래로 떨어지며 속도가 늘어난다(하강 가속).
- 중력과 반대 방향: 위로 올라가며 속도가 늘거나(상승 가속), 아래로 떨어지며 속도가 줄어든다(하강 감속).

**포즈 고칠 때 규칙 한 줄:**
- 캐릭터가 위로 가속하거나 아래로 감속할 때는 몸의 드레이퍼리·머리·살이 아래로 당겨지도록 무게 증가를 포즈에 반영하고, 위로 감속하거나 아래로 가속할 때는 가볍고 부유하는 느낌의 무게 감소를 반영한다.

## 2. Center of Gravity (Animator Island)

**핵심 세 줄:**
- 무게중심(CoG)은 물체 무게의 평균 위치로, 사람의 경우 배꼽 높이 복부 중앙에 있지만 포즈에 따라 이동한다.
- 캐릭터가 정적 균형으로 서려면 CoG가 지지대(Base of Support) 위에 있어야 하며, 중력선을 그려 발 안쪽에 떨어지는지 확인하면 된다.
- 캐릭터가 점프하면 CoG는 포물선 궤적을 따르고, 회전하는 망치의 CoG가 단일 궤적을 그리는 것처럼 몸통·팔·다리의 회전과 상관없이 CoG만 추적하면 자연스러운 이동이 된다.

**포즈 고칠 때 규칙 한 줄:**
- CoG가 지지대 위에 떨어지도록 hips를 조정하고, 무거운 물체를 들거나 무게를 옮길 때는 결합된 CoG가 발 위에 오도록 torso를 반동시켜counter-balance한다.

## 3. Center of Gravity Part Two (AWN)

**핵심 세 줄:**
- 캐릭터가 움직이면 균형을 유지하기 위해 무게중심을 보정하며, 팔·다리로 counter-balance한다.
- 점프·굴곡·타잔 swing 등 모든 이동에서 무게중심은 arc(path of action) 위에 중심을 둔다.
- 무게를 arc 위에 두지 않으면 움직임이 인위적이고 부자연스럽게 보인다.

**포즈 고칠 때 규칙 한 줄:**
- 이동의 arc(path of action) 위에 캐릭터 무게중심을 항상 중심을 두고, arm/leg으로 counter-balance하여 균형이 깨지지 않도록 포즈를 조정한다.

## 4. Balance, Center of Gravity, Ground Contact (Cursa)

**핵심 세 줄:**
- Base of Support(BoS)는 발이 바닥과 접촉하는 영역이며, CoG에서 수직선을 내려 BoS 안에 떨어지면 안정된 포즈로 읽힌다.
- 두 발 지지에서는 한쪽 다리에 무게를 실어 hip tilt를 주고, 한 발 지지에서는 CoG가 착지한 발 안쪽에 떨어지도록 hips를 이동시킨다.
- Planted foot은 world space에서 고정하고 hips/root로 무게 이동과 tilt를 만들어 traction을 유지하며, micro-slip을 막는다.

**포즈 고칠 때 규칙 한 줄:**
- CoG projection이 BoS 안에 떨어지도록 hips를 translate하고 tilt로 weight-bearing leg에 load를 주며, planted foot은 world space에서 고정해 micro-slip 없이 traction을 유지한다.
