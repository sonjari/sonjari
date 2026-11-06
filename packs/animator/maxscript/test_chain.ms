-- 손자리 애니메이터 팩: 첫 시험용 장면 (실제 작업 장면에서 돌리지 말고 「새 장면」에서)
-- 포인트 5개를 부모-자식 줄로 만들고, 0~24 프레임에 Z 회전으로 흔드는 루프 키를 넣는다(마디 모두 같은 박자).
-- 이걸 고른 채로 엇박자 루프(anim_offset_read → anim_offset_plan → 쓰기)를 돌리면 끝으로 갈수록 늦게 흔들려야 한다.
(
  local prev = undefined
  local made = #()
  for i = 1 to 5 do (
    local p = Point name:("SJ_Tail" + (formattedPrint i format:"02d")) size:6 box:true
    p.pos = [0, (i - 1) * 10, 0]
    if prev != undefined do p.parent = prev
    append made p
    prev = p
  )
  animate on (
    -- 자식 마디는 p.rotation 이 월드 값이라 거기 쓰면 부모 기준 회전이 안 들어간다(11-02 맥스 2027 실측) → Z 곡선에 직접
    for p in made do (
      local zc = p.rotation.controller[3].controller
      at time 0f zc.value = 0
      at time 6f zc.value = 20
      at time 12f zc.value = 0
      at time 18f zc.value = -20
      at time 24f zc.value = 0
    )
  )
  animationRange = interval 0f 24f
  select made
  "sonjari: test chain SJ_Tail01..05 ready (0-24f, Z rotation)"
)
