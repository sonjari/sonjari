-- ============================================================================
-- 손자리 애니메이터 팩 · 보정 A: COM 키 프레임에 Spine · Spine1 · Neck · Head · COM 회전 키 맞추기 (v1)
-- 만든 날: 2026-11-19 · 3ds Max 2026 · 바이패드 Bip001 기준
--
-- 현업 원칙: COM 에 키가 있는 프레임에는 Spine · Spine1 · Neck · Head 에도 키가 있어야 한다.
-- 두 가지로 돈다 (같은 파일):
--   · 제안(doApply = false, 기본) — 읽기 전용. 어느 프레임에 어떤 키를 찍을지만 알려 준다. 장면을 바꾸지 않는다.
--   · 적용(doApply = true) — 빠진 프레임에만 「그 프레임의 현재 값 그대로」 키를 찍는다. 사람이 「해」 한 뒤에만.
-- 지키는 것: 기존 키는 지우지 않는다 · COM 에 없는 키(예: Head 6 · 12 · 18)는 남긴다 · 값은 바꾸지 않는다(키만 찍음)
--          · 적용 뒤 모든 프레임의 회전 차이(도)와 키 시간을 보고한다. 키를 찍으면 맥스가 곡선을 다시 계산해 0 은 아니다(시험: 최대 약 2°).
-- 되돌리기: 적용 직전에 holdMaxFile() 로 장면을 보관한다 — 편집 › 가져오기(Fetch) 또는 Ctrl+Z.
-- 주의: MAXScript 는 변수 이름의 대소문자를 구분하지 않는다. off · on 같은 예약어를 변수로 쓰지 않는다.
-- ============================================================================
(
local doApply = false
local bipName = "Bip001"

fn sjKeyTimes c = (local r = #(); try (for k in c.keys do append r (k.time.frame as integer)) catch (append r -1); r)
fn sjQAngle a b = ((acos (amin 1.0 (abs ((a.x*b.x) + (a.y*b.y) + (a.z*b.z) + (a.w*b.w))))) * 2.0)

local com = getNodeByName bipName
if com == undefined then ("손자리 키 정렬: 바이패드를 못 찾았다 (" + bipName + ")") else (
local fS = animationRange.start.frame as integer; local fE = animationRange.end.frame as integer
local comKeys = sjKeyTimes com.controller.vertical.controller
local targets = #()      -- #(노드, 이름, 키 목록, 빠진 프레임)
for nm in #("Spine", "Spine1", "Neck", "Head") do (
  local nd = getNodeByName (bipName + " " + nm)
  if nd != undefined then (
    local ks = sjKeyTimes nd.controller; local miss = #(); for f in comKeys do if (findItem ks f) == 0 then append miss f
    append targets #(nd, nm, ks, miss)
  )
)
local comRotMiss = #()
try (local tk = sjKeyTimes com.controller.turning.controller; for f in comKeys do if (findItem tk f) == 0 then append comRotMiss f) catch ()

local rep = "COM 키 프레임: " + (comKeys as string) + "\n"
local total = comRotMiss.count
for tg in targets do total += tg[4].count
if total == 0 then (
  rep += "이미 맞다 — COM 키 프레임에 Spine · Spine1 · Neck · Head · COM 회전 키가 모두 있다. 할 일 없음.\n"
) else (
  rep += "제안: 빠진 키 " + (total as string) + "개를 그 프레임의 현재 값 그대로 찍는다 (기존 키는 지우지 않음)\n"
  for tg in targets do if tg[4].count > 0 then rep += "  " + tg[2] + ": " + (tg[4] as string) + "\n"
  if comRotMiss.count > 0 then rep += "  COM 회전: " + (comRotMiss as string) + "\n"
  if not doApply then rep += "(제안만 — 장면은 바꾸지 않았다. 적용하려면 사람이 「해」 한 뒤 doApply = true 로 다시 돌린다)\n"
  else (
    -- 적용 전 자세 기록
    local nodes = #(); for tg in targets do append nodes tg[1]
    local beforeRot = #(); for nd in nodes do (local arr = #(); for t = fS to fE do (at time t (append arr nd.transform.rotation)); append beforeRot arr)
    local comBefore = #(); for t = fS to fE do (at time t (append comBefore com.transform.rotation))
    local keepTime = sliderTime
    holdMaxFile()
    for i = 1 to targets.count do (
      local nd = targets[i][1]
      for f in targets[i][4] do (sliderTime = f; local q = nd.transform.rotation; biped.setTransform nd #rotation q true)
    )
    for f in comRotMiss do (sliderTime = f; local cq = com.transform.rotation; biped.setTransform com #rotation cq true)
    sliderTime = keepTime
    rep += "적용했다 (적용 직전 장면 보관됨 — 편집 › 가져오기(Fetch) 로 되돌릴 수 있다).\n키 시간 (적용 후):\n"
    for tg in targets do rep += "  " + tg[2] + ": " + ((sjKeyTimes tg[1].controller) as string) + "\n"
    try (rep += "  COM 회전: " + ((sjKeyTimes com.controller.turning.controller) as string) + "\n") catch ()
    rep += "  COM 수직: " + ((sjKeyTimes com.controller.vertical.controller) as string) + " (바뀌지 않아야 한다)\n"
    local worst = 0.0; local whr = ""
    for i = 1 to nodes.count do (for t = fS to fE do (local q2; at time t (q2 = nodes[i].transform.rotation); local d = sjQAngle beforeRot[i][t - fS + 1] q2; if d > worst then (worst = d; whr = targets[i][2] + " " + (t as string) + "프레임")))
    for t = fS to fE do (local q2; at time t (q2 = com.transform.rotation); local d = sjQAngle comBefore[t - fS + 1] q2; if d > worst then (worst = d; whr = "COM " + (t as string) + "프레임"))
    rep += "자세 변화(적용 전 대비) 최대 " + (formattedPrint worst format:".2f") + "° (" + whr + ") — 키를 찍으면 곡선이 다시 계산돼 0 은 아니다. 눈으로 확인할 것.\n"
  )
)
rep
)
)
