/**
 * 이어받기 화면 리허설 — **개발 빌드 전용**, 동적 import 로만 불린다.
 *
 * `fixtureTakeover.json` 은 진짜 `TakeoverService` 에 **지어낸 대화 기록과 임시 git 저장소**를 넣고
 * 가지 만들기 → 검토 대기까지 실제로 돌려 뽑은 출력이다. 화면용으로 지어낸 값이 아니다.
 *
 *     ?mode=takeover&takeoverFixture=1
 */
import data from "./fixtureTakeover.json";
import type { AcceptResult, TakeoverApi, TakeoverCard, TakeoverRecord } from "./takeoverApi";

type Fixture = {
  sessions: { sessions: TakeoverCard[]; cursor_supported: boolean; note: string };
  records: TakeoverRecord[];
  card_answer: string;
};

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function createFixtureTakeoverApi(): TakeoverApi {
  const fx = data as unknown as Fixture;
  let records = [...fx.records];
  let nextId = 900;
  return {
    async sessions() {
      await wait(600);
      return fx.sessions;
    },
    async list() {
      await wait(150);
      return { items: records };
    },
    async pick(sessionPath) {
      await wait(200);
      const card = fx.sessions.sessions.find((c) => c.session_path === sessionPath);
      if (!card) return { ok: false, error: "session_not_found" };
      nextId += 1;
      return { ok: true, takeover_id: nextId };
    },
    async accept(id): Promise<AcceptResult> {
      await wait(900);
      return { answer: fx.card_answer, kind: "card", takeover_id: id };
    },
    async discard(id) {
      await wait(400);
      records = records.map((r) => (r.id === id ? { ...r, status: "discarded" } : r));
      return { ok: true };
    },
  };
}
