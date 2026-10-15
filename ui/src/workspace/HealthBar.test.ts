import { describe, expect, it } from "vitest";
import healthBar from "./HealthBar.tsx?raw";

/**
 * 점검 줄 회귀 (2026-09-18).
 *
 * 폴링 효과가 `status` 에 걸려 있어 결과가 올 때마다 **즉시 또 물었다** — 리허설 실측 5초에 232번,
 * 고친 뒤 16초에 1번. 눈에 안 보이는 고장이라(화면은 멀쩡하다) 소스로 지킨다.
 */
describe("HealthBar", () => {
  it("does not re-poll every time a result arrives", () => {
    expect(healthBar).not.toMatch(/\[read,\s*status\]/);
    expect(healthBar).toMatch(/statusRef\.current/);
  });

  it("keeps the diagnostics notice on its own line, not glued to the fault", () => {
    expect(healthBar).not.toContain("` — ${note}`");
    expect(healthBar).toContain("health-bar-note");
  });
  // 머리 위 줄의 그리드 행 규칙은 CSS 라 tests/test_self_check_on_boot.py 가 지킨다(여기선 node 타입이 없다).
});
