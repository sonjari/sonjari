/**
 * 화면 검사 모음 — 브라우저 콘솔(또는 미리보기 도구의 javascript_exec)에 붙여 넣고 쓴다.
 *
 * 왜 파일로 남기나: 이 검사들은 2026-08-19 재설계 중에 만들었고, 그중 셋은 **처음에
 * 틀린 것을 재고 있었다.** 다시 만들면 같은 실수를 다시 한다. 고쳐 놓은 판을 남긴다.
 *
 * 쓰는 법
 *   1) 미리보기 서버를 띄운다:  npm run dev   (127.0.0.1:1420)
 *   2) 아무 리허설 장면이나 연다: /?mode=workspace&fixture=long-table
 *   3) 아래 함수 중 하나를 콘솔에 통째로 붙여 넣는다
 *
 * 전제: 리허설 하네스(`src/fixtures/`)가 개발 빌드에서 켜져 있어야 한다.
 */

/* ────────────────────────────────────────────────────────────────────────────
 * 1) 잘림 검사 — 10장면 전수
 *
 * ★ 함정: `overflow: visible` 인 요소에서 scrollHeight > clientHeight 를 세면
 *   그건 **잘림이 아니라 넘침**이다. visible 은 상자 밖으로 나가도 그대로 그려진다.
 *   진짜 잘림은 overflow 가 hidden 인데 내용이 넘칠 때다. ellipsis 는 일부러
 *   자른 것이므로 뺀다.
 * ──────────────────────────────────────────────────────────────────────────── */
async function checkClipping(sizes = [[1320, 840]]) {
  // ★ 새 장면을 만들면 여기에 넣어라. 안 넣으면 그 장면은 **조용히 안 세어진다**
  //   (P8 눈금이 세 번 틀렸던 것이 전부 이 모양이었다 — 분모를 먼저 보라).
  const names = ["welcome", "streaming", "agent-running", "approval",
                 "continuation", "attention", "error", "long-table", "jobs",
                 "browser-blocked"];
  const out = {};
  for (const [w, h] of sizes) {
    for (const n of names) {
      const f = document.createElement("iframe");
      f.style.cssText = `position:fixed;left:-9999px;width:${w}px;height:${h}px;border:0`;
      document.body.appendChild(f);
      f.src = `/?mode=workspace&fixture=${n}`;
      await new Promise((r) => { f.onload = r; setTimeout(r, 4000); });
      await new Promise((r) => setTimeout(r, 900));
      const d = f.contentDocument;
      const clipped = [];
      d.querySelectorAll("main.jarvis-workspace *").forEach((el) => {
        if (el.clientWidth === 0) return;
        const cs = getComputedStyle(el);
        const dw = el.scrollWidth - el.clientWidth;
        const dh = el.scrollHeight - el.clientHeight;
        const deliberate = cs.textOverflow === "ellipsis" || cs.webkitLineClamp !== "none";
        if (!deliberate && ((cs.overflowX === "hidden" && dw > 1) || (cs.overflowY === "hidden" && dh > 1))) {
          clipped.push(`${(el.className || el.tagName).toString().slice(0, 30)}|w+${dw}|h+${dh}`);
        }
      });
      out[`${w}x${h} ${n}`] = {
        clipped: clipped.length,
        sample: clipped.slice(0, 3),
        hScroll: d.documentElement.scrollWidth > d.documentElement.clientWidth,
      };
      f.remove();
    }
  }
  return out;
}

/* ────────────────────────────────────────────────────────────────────────────
 * 2) 색이 뜻을 지키는지 — 화면에 실제로 칠해진 유채색을 센다
 *
 * ★ 함정: HSV 채도로 판정하면 **어두운 색이 전부 "파랑"으로** 세어진다
 *   (검정에 가까울수록 HSV 채도가 뻥튀기된다). Lab 채도로 재야 한다.
 *
 * 기대값: 보라(자비스) · 주황(승인) · 초록(됐다) · 빨강(안 됐다) 넷뿐.
 * 그 밖의 계열이 잡히면 뜻 없는 장식색이 들어온 것이다.
 * ──────────────────────────────────────────────────────────────────────────── */
async function checkColorMeaning(fixtures = ["welcome", "agent-running", "approval", "attention", "long-table"]) {
  const lab = (r, g, b) => {
    const f = (u) => { u /= 255; return u <= 0.04045 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4; };
    const R = f(r), G = f(g), B = f(b);
    const x = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
    const y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
    const z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
    const q = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const fx = q(x), fy = q(y), fz = q(z);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  };
  const family = (r, g, b) => {
    const [, A, B2] = lab(r, g, b);
    if (Math.hypot(A, B2) < 12) return null;           // 무채
    let h = (Math.atan2(B2, A) * 180) / Math.PI;
    if (h < 0) h += 360;
    if (h < 40) return "빨강";
    if (h < 95) return "주황";
    if (h < 170) return "초록";
    if (h < 250) return "파랑";
    if (h < 330) return "보라";
    return "분홍";
  };
  const out = {};
  for (const n of fixtures) {
    const f = document.createElement("iframe");
    f.style.cssText = "position:fixed;left:-9999px;width:1320px;height:840px;border:0";
    document.body.appendChild(f);
    f.src = `/?mode=workspace&fixture=${n}`;
    await new Promise((r) => { f.onload = r; setTimeout(r, 4000); });
    await new Promise((r) => setTimeout(r, 700));
    const tally = {};
    f.contentDocument.querySelectorAll("main.jarvis-workspace *").forEach((el) => {
      const s = getComputedStyle(el);
      for (const v of [s.color, s.backgroundColor, s.borderTopColor, s.borderLeftColor, s.backgroundImage]) {
        for (const m of String(v).matchAll(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/g)) {
          if (m[4] !== undefined && Number(m[4]) === 0) continue;   // 투명은 안 센다
          const k = family(+m[1], +m[2], +m[3]);
          if (k) tally[k] = (tally[k] || 0) + 1;
        }
      }
    });
    out[n] = tally;
    f.remove();
  }
  return out;
}

/* ────────────────────────────────────────────────────────────────────────────
 * 3) 화면 지문 — "고쳐도 화면은 안 바뀐다"를 증명할 때
 *
 * 리팩터링 전에 snapshot("before") 를 부르고, 고친 뒤 diff() 를 부른다.
 * 새로고침을 견디도록 sessionStorage 에 넣는다.
 *
 * ★ 주의: dev 서버가 파일 변경을 못 알아채는 일이 있다(특히 셸 `cp` 로 덮었을 때).
 *   지문이 안 바뀌면 서버를 껐다 켜고 다시 재라 — 안 바뀐 게 아니라 안 읽힌 것일 수 있다.
 * ──────────────────────────────────────────────────────────────────────────── */
function snapshot(key = "snapBefore") {
  const rows = [];
  document.querySelectorAll("main.jarvis-workspace, main.jarvis-workspace *").forEach((el, i) => {
    const s = getComputedStyle(el);
    const cls = el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className;
    rows.push([i, el.tagName, cls, s.color, s.backgroundColor, s.backgroundImage,
      s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor,
      s.boxShadow, s.outlineColor, s.fill, s.stroke, s.caretColor].join("|"));
  });
  sessionStorage.setItem(key, JSON.stringify(rows));
  return { saved: rows.length };
}

function diff(key = "snapBefore") {
  const before = JSON.parse(sessionStorage.getItem(key) || "[]");
  const after = [];
  document.querySelectorAll("main.jarvis-workspace, main.jarvis-workspace *").forEach((el, i) => {
    const s = getComputedStyle(el);
    const cls = el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className;
    after.push([i, el.tagName, cls, s.color, s.backgroundColor, s.backgroundImage,
      s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor,
      s.boxShadow, s.outlineColor, s.fill, s.stroke, s.caretColor].join("|"));
  });
  const diffs = [];
  for (let i = 0; i < Math.min(before.length, after.length); i++) {
    if (before[i] !== after[i]) diffs.push({ i, b: before[i].slice(0, 130), a: after[i].slice(0, 130) });
  }
  return { before: before.length, after: after.length, diffCount: diffs.length, first: diffs.slice(0, 5) };
}

/* ────────────────────────────────────────────────────────────────────────────
 * 4) 궤적이 답보다 오래 사는지 — P4 가 고친 그 버그의 회귀 검사
 *
 * 예전에는 job_completed 직후 걸음이 0으로 지워졌다. 아래를 돌리면
 * 마지막 표본에서도 걸음 수가 유지되어야 한다.
 * ──────────────────────────────────────────────────────────────────────────── */
async function checkTrajectorySurvives() {
  // agent-running 장면에서 실행할 것
  document.querySelector(".fixture-replay")?.click();
  const t0 = performance.now();
  const out = [];
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 900));
    out.push({
      t: Math.round((performance.now() - t0) / 100) / 10,
      steps: document.querySelectorAll(".trajectory-steps li").length,
      head: document.querySelector(".trajectory-head > span")?.textContent ?? "-",
      nowIdle: !!document.querySelector(".now-idle"),
    });
  }
  return out;
}

/* ────────────────────────────────────────────────────────────────────────────
 * 5) 가만히 있을 때 도는 애니메이션 — 연출 계약 1번(정지가 기본)
 *    0 이어야 한다. 0 이 아니면 배경이나 장식이 프레임을 계속 쓰고 있다.
 * ──────────────────────────────────────────────────────────────────────────── */
function checkIdleFrames() {
  const running = [...document.querySelectorAll("main.jarvis-workspace *")]
    .filter((el) => el.getAnimations && el.getAnimations().some((a) => a.playState === "running"));
  return { animating: running.length, sample: running.slice(0, 5).map((el) => el.className) };
}
