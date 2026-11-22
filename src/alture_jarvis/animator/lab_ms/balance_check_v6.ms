-- ============================================================================
-- 손자리 애니메이터 팩 · 균형 / 디딤발 / 키 정렬 점검 v6   (읽기 전용 — 장면을 바꾸지 않는다)
-- 만든 날: 2026-11-19 · 3ds Max 2026 · 바이패드 Bip001 기준
--
-- 쓰는 법: 점검할 동작이 입혀진 장면에서 이 파일 전체를 실행한다. 결과 글이 돌아온다.
--          (execute_maxscript 로 부를 때는 execute ((dotNetClass "System.IO.File").ReadAllText @"경로") 로 불러 문자열을 돌려받는다)
-- 점검:  ① COM 앞뒤 어긋남   ② 홀딩 구간 안 딛은 발 밀림   ③ 애매하게 뜬 발   ④ COM 좌우 균형   ⑤ 키 정렬 · COM 곡선
-- 이 숫자는 「어디를 볼지 짚어 주는 표」다 — 문제인지는 사람이 재생해 보고 정한다.
-- 기준 숫자는 현업 수정본 · 원본 동작 몇 개로 맞춘 임시값이다(아래 변수). 다른 동작에서 맞는지는 확인 전.
-- 현업 원칙: ① COM · Spine · Head 키는 같은 프레임 ② 무게중심 이동이 핵심 ③ COM 그래프는 곡선(강한 움직임은 1프레임 급변도 정상)
-- 주의: MAXScript 는 변수 이름의 대소문자를 구분하지 않는다(s 와 S 가 같다). off · on 같은 예약어를 변수로 쓰지 않는다.
-- ============================================================================
(
-- ── 기준 숫자 (임시값) ─────────────────────────────────────────────────────
local bipName = "Bip001"           -- 바이패드 COM 이름
local groundTol = 6.0              -- 발끝이 지면(구간 최저)보다 이만큼 이내면 「딛음」
local fwdTol = 25.0                -- ① COM 앞뒤 어긋남 기준
local holdSpeed = 2.0              -- 홀딩: COM 이 프레임당 이보다 적게 움직임
local slideRatio = 0.1             -- ② 밀림 기준 = 다리 길이 x 이 값
local slideMinFrames = 3           -- ② 홀딩이 이만큼 이어질 때만
local floatLo = 1.5                -- ③ 애매하게 뜬 발: 발끝 높이 하한
local floatMinFrames = 5           -- ③ 이만큼 이어지고
local floatAvg = 3.0               -- ③ 평균이 이를 넘을 때
local latTol = 15.0                -- ④ 좌우 범위 밖 기준
local accTol = 30.0                -- ⑤ COM 위치 가속(참고 표시) 기준

-- ── 노드 ───────────────────────────────────────────────────────────────────
local com = getNodeByName bipName
local rf = getNodeByName (bipName + " R Foot"); local lf = getNodeByName (bipName + " L Foot")
local rt = getNodeByName (bipName + " R Toe0"); local lt0 = getNodeByName (bipName + " L Toe0")
local lth = getNodeByName (bipName + " L Thigh"); local lca = getNodeByName (bipName + " L Calf")
if com == undefined or rf == undefined or lf == undefined or rt == undefined or lt0 == undefined or lth == undefined or lca == undefined then (
  "손자리 점검: 바이패드 노드를 못 찾았다 (" + bipName + ") — 점검하지 않았다"
) else (
local fS = animationRange.start.frame as integer; local fE = animationRange.end.frame as integer
local n = fE - fS + 1
local legLen = 0.0
at time fS (legLen = (distance lth.transform.pos lca.transform.pos) + (distance lca.transform.pos lf.transform.pos))
local minZ = 1e9
for t = fS to fE do at time t (minZ = amin minZ (amin rt.transform.pos.z lt0.transform.pos.z))

-- ── 프레임마다 읽기 ────────────────────────────────────────────────────────
local cp = #(); local rz = #(); local lz = #(); local rp = #(); local lp = #()
local fwdOff = #(); local supp = #(); local latOut = #(); local latTag = #()
for t = fS to fE do at time t (
  local c = com.transform.pos; append cp c
  local rTo = rt.transform.pos.z - minZ; local lTo = lt0.transform.pos.z - minZ
  append rz rTo; append lz lTo; append rp rf.transform.pos; append lp lf.transform.pos
  local rG = rTo < groundTol; local lG = lTo < groundTol
  local fr = normalize [rt.transform.pos.x - rf.transform.pos.x, rt.transform.pos.y - rf.transform.pos.y, 0]
  local fl = normalize [lt0.transform.pos.x - lf.transform.pos.x, lt0.transform.pos.y - lf.transform.pos.y, 0]
  local rPos = [rf.transform.pos.x, rf.transform.pos.y, 0]; local lPos = [lf.transform.pos.x, lf.transform.pos.y, 0]; local cPos = [c.x, c.y, 0]
  if rG and lG then (
    -- 두 발 딛음: 두 발 사이 범위를 기준으로 (앞뒤 / 좌우 각각)
    local ax = normalize (fr + fl); local lat = [0 - ax.y, ax.x, 0]
    local pc = dot cPos ax; local pr = dot rPos ax; local pl = dot lPos ax
    append fwdOff (if pc < (amin pr pl) then pc - (amin pr pl) else if pc > (amax pr pl) then pc - (amax pr pl) else 0.0); append supp "두 발 딛음(두 발 사이 기준)"
    local qc = dot cPos lat; local qr = dot rPos lat; local ql = dot lPos lat
    append latOut (if qc < (amin qr ql) then qc - (amin qr ql) else if qc > (amax qr ql) then qc - (amax qr ql) else 0.0); append latTag " (두 발 딛음)"
  )
  else if rG or lG then (
    local sup = if rG then rPos else lPos; local ax = if rG then fr else fl; local lat = [0 - ax.y, ax.x, 0]
    append fwdOff (dot (cPos - sup) ax); append supp (if rG then "오른발만" else "왼발만")
    append latOut (dot (cPos - sup) lat); append latTag (if rG then " (오른발만)" else " (왼발만)")
  )
  else (append fwdOff undefined; append supp ""; append latOut undefined; append latTag "")
)
local isHold = #()
for i = 1 to n do (local a = amax 1 (i - 1); local b = amin n (i + 1); append isHold ((distance cp[a] cp[b]) / (b - a) < holdSpeed))

-- ── 보고 ───────────────────────────────────────────────────────────────────
local rep = "다리 길이 " + (formattedPrint legLen format:".0f") + " · 발끝 지면 기준 " + (formattedPrint minZ format:".1f") + " · 구간 " + (fS as string) + "~" + (fE as string) + "\n"
local holdTxt = ""; for i = 1 to n do if isHold[i] then holdTxt += ((fS + i - 1) as string) + " "
rep += "홀딩 프레임(COM 거의 안 움직임): " + (if holdTxt == "" then "없음" else holdTxt) + "\n"
local cnt1 = 0; local cnt2 = 0; local cnt3 = 0; local cnt4 = 0; local cnt5 = 0

rep += "== ① COM 앞뒤 어긋남 (딛은 발 기준 +앞 · -뒤, 기준 ±" + (formattedPrint fwdTol format:".0f") + ") ==\n"
for i = 1 to n do if fwdOff[i] != undefined and (abs fwdOff[i]) >= fwdTol then (rep += ((fS + i - 1) as string) + ": " + (formattedPrint fwdOff[i] format:".1f") + " (" + supp[i] + ")\n"; cnt1 += 1)

rep += "== ② 홀딩 구간 안에서 딛은 발이 밀린 양 (발끝 지면 " + (formattedPrint groundTol format:".0f") + " 이내 · 홀딩 " + (slideMinFrames as string) + "프레임 이상 · 기준 " + (formattedPrint (legLen * slideRatio) format:".1f") + ") ==\n"
local refs = ""
for side in #(#R, #L) do (
  local zz = if side == #R then rz else lz; local ps = if side == #R then rp else lp
  local nm = if side == #R then "오른" else "왼"
  local i = 1
  while i <= n do (
    if zz[i] < groundTol then (
      local j = i; local worstAll = 0.0
      while j <= n and zz[j] < groundTol do (worstAll = amax worstAll (distance [ps[j].x, ps[j].y, 0] [ps[i].x, ps[i].y, 0]); j += 1)
      local k = i
      while k < j do (
        if isHold[k] then (
          local m = k; local w = 0.0
          while m < j and isHold[m] do (w = amax w (distance [ps[m].x, ps[m].y, 0] [ps[k].x, ps[k].y, 0]); m += 1)
          if (m - k) >= slideMinFrames and w > legLen * slideRatio then (rep += nm + "발 " + ((fS + k - 1) as string) + "~" + ((fS + m - 2) as string) + "프레임(홀딩): 최대 " + (formattedPrint w format:".1f") + " (" + (formattedPrint (w / legLen * 100) format:".0f") + "%) 밀림\n"; cnt2 += 1)
          k = m
        ) else k += 1
      )
      if (j - i) >= 3 and worstAll > legLen * slideRatio then refs += nm + "발 " + ((fS + i - 1) as string) + "~" + ((fS + j - 2) as string) + ": 딛은 채 이동 " + (formattedPrint worstAll format:".0f") + "\n"
      i = j
    ) else i += 1
  )
)
rep += "(참고: 딛은 채 이동한 구간 — 홀딩 밖의 이동은 스텝일 수 있어 문제로 세지 않음)\n" + refs

rep += "== ③ 애매하게 뜬 발 (발끝 " + (formattedPrint floatLo format:".1f") + "~" + (formattedPrint groundTol format:".0f") + " 위가 " + (floatMinFrames as string) + "프레임 이상 · 평균 " + (formattedPrint floatAvg format:".0f") + " 초과) ==\n"
for side in #(#R, #L) do (
  local zz = if side == #R then rz else lz
  local i = 1
  while i <= n do (
    if zz[i] > floatLo and zz[i] < groundTol then (
      local j = i; local sm = 0.0
      while j <= n and zz[j] > floatLo and zz[j] < groundTol do (sm += zz[j]; j += 1)
      if (j - i) >= floatMinFrames and (sm / (j - i)) > floatAvg then (rep += (if side == #R then "오른" else "왼") + "발 " + ((fS + i - 1) as string) + "~" + ((fS + j - 2) as string) + "프레임: 발끝이 평균 " + (formattedPrint (sm / (j - i)) format:".1f") + " 위에 떠 있음\n"; cnt3 += 1)
      i = j
    ) else i += 1
  )
)

rep += "== ④ 좌우 균형 (COM 이 딛은 발(들)의 좌우 범위 밖으로 " + (formattedPrint latTol format:".0f") + " 이상) ==\n"
for i = 1 to n do if latOut[i] != undefined then (
  -- 한 발 딛음은 그 발 위치와의 차이, 두 발은 두 발 사이 범위 밖 양
  if (abs latOut[i]) >= latTol then (rep += ((fS + i - 1) as string) + ": 범위 밖 " + (formattedPrint (abs latOut[i]) format:".0f") + latTag[i] + "\n"; cnt4 += 1)
)

fn sjKeyTimes c = (local r = #(); try (for k in c.keys do append r (k.time.frame as integer)) catch (append r -1); r)
rep += "== ⑤ 키 정렬 · COM 곡선 ==\n"
local comKeys = sjKeyTimes com.controller.vertical.controller
for nm in #("Spine", "Spine1", "Neck", "Head") do (
  local nd = getNodeByName (bipName + " " + nm)
  if nd != undefined then (
    local ks = sjKeyTimes nd.controller; local miss = ""; for f in comKeys do if (findItem ks f) == 0 then miss += (f as string) + " "
    local extra = ""; for f in ks do if (findItem comKeys f) == 0 then extra += (f as string) + " "
    if miss != "" then (rep += "키 빠짐 " + nm + ": COM 키 프레임 " + miss + "에 키 없음\n"; cnt5 += 1)
    if extra != "" then rep += "참고 " + nm + ": COM 에 없는 키 " + extra + "\n"
  )
)
try (local tk = sjKeyTimes com.controller.turning.controller; local miss = ""; for f in comKeys do if (findItem tk f) == 0 then miss += (f as string) + " "; if miss != "" then (rep += "키 빠짐 COM 회전: COM 키 프레임 " + miss + "에 키 없음\n"; cnt5 += 1)) catch ()
local accTxt = ""
for i = 2 to (cp.count - 1) do (local a = length (cp[i+1] - 2*cp[i] + cp[i-1]); if a > accTol then accTxt += ((fS + i - 1) as string) + "(" + (formattedPrint a format:".0f") + ") ")
rep += "참고: COM 위치가 급하게 꺾이는 프레임(가속 " + (formattedPrint accTol format:".0f") + " 이상): " + (if accTxt == "" then "없음" else accTxt) + " — 강한 움직임을 위한 의도일 수 있음, 판단은 사람\n"

rep += "== 요약 (짚힌 곳 수 — 어디를 볼지 알려 주는 표일 뿐, 문제 여부는 재생해서 사람이 정한다) ==\n"
rep += "① " + (cnt1 as string) + " · ② " + (cnt2 as string) + " · ③ " + (cnt3 as string) + " · ④ " + (cnt4 as string) + " · ⑤ 키 빠짐 " + (cnt5 as string) + "\n"
rep
)
)
