// 개발용 연습 화면 — `/레시피`(해 보여서 가르치기)의 화면 부분을 본체 없이 띄워 본다. 앱 빌드에는 안 들어간다.
//   ?state=menu      입력창에 `/` 를 친 모습(명령 목록)
//   ?state=offer     「막혔습니다 · 보여 주시겠어요?」 답 아래 [보여 주기]
//   ?state=learning  배우는 중 칸(걸음이 쌓이는 모습)
//   ?state=review    「이렇게 배웠습니다」 + 단추 셋
//   ?state=replaying 저장 전 한 번 해 보는 중
//   ?state=failed    틀린 걸음 + 단추 셋        (?lang=en 이면 영어판)
import ReactDOM from "react-dom/client";
import "../styles.css";
import "../workspace.css";
import { setLangForTest } from "../i18n";
import { applyLearnEvent, idleLearn, slashMenu, type LearnState } from "../recipeLearn";
import type { ConversationMessage } from "../types";
import { MessageView } from "../workspace/MessageView";
import { RecipeLearnPanel, SlashMenu } from "../workspace/RecipeLearnPanel";

const params = new URLSearchParams(location.search);
const state = params.get("state") ?? "learning";
const language = params.get("lang") === "en" ? "en" : "ko";
setLangForTest(language);

const message = (id: number, role: "user" | "assistant", content: string, metadata: Record<string, unknown> = {}): ConversationMessage => ({
  id, session_id: "demo", role, content, kind: "chat", metadata, created_at: Date.now() / 1000,
});

const ko = language === "ko";
const OFFER = ko
  ? "쿠팡에서 장바구니 담기를 끝까지 하지 못했습니다.\n\n---\nwww.coupang.com 에서 누르거나 고르는 데서 막혔습니다. 한 번 보여 주시면 다음부터 그대로 하겠습니다. 보여 주시겠어요? (응 / 아니)"
  : "I couldn't finish adding to the cart on Coupang.\n\n---\nI got stuck clicking or choosing on www.coupang.com. Show me once and I'll do it the same way next time. Want to show me? (yes / no)";
const REVIEW = ko
  ? "이렇게 배웠습니다.\n배운 것: 쿠팡 장바구니 · 4걸음 · coupang.com 안에서만\n 1. https://www.coupang.com/ 을 연다\n 2. 「상품명, 카테고리명 으로 검색」 칸에 {찾을 말} 을 넣는다\n 3. Enter 를 누른다  → 확인: 주소가 바뀐다\n 4. 「장바구니 담기」 을 누른다  → 확인: 주소가 바뀐다\n\n바꾸는 것: 화면에서 누르고 입력합니다 — 저장하려면 확인이 필요합니다\n\n저장하기 전에 한 번 그대로 해 볼까요? 손자리 크롬이 위 걸음을 그대로 누르고 입력하면서 걸음마다 확인합니다. 확인이 모두 맞아야 「검증된 레시피」라고 부릅니다."
  : "This is what I learned.\nLearned: Coupang cart · 4 steps · stays on coupang.com\n 1. Open https://www.coupang.com/\n 2. Type {search words} into 「Search」\n 3. Press Enter  → check: the address changes\n 4. Click 「Add to cart」  → check: the address changes\n\nWant me to try it once before saving? The Sonjari browser will click and type these steps as they are and check each one — I only call it \"verified\" if every check passes.";
const FAILED = ko
  ? "4번째 걸음에서 틀렸습니다 — 기대한 변화가 화면에 나타나지 않았습니다\n(앞 3걸음은 맞았습니다.)\n\n다시 보여 주시겠어요, 그래도 저장할까요(「미검증」으로 남습니다), 아니면 버릴까요?"
  : "It went wrong at step 4: the expected change did not show up\n(Steps 1-3 were fine.)\n\nShow me again, save it anyway (it stays marked unverified), or discard it?";

const buttons = {
  offer: [{ label: ko ? "보여 주기" : "Show me", say: "/레시피 www.coupang.com 에서 막혔던 일" }],
  review: ko
    ? [{ label: "한 번 해 볼게요", say: "x" }, { label: "검증 없이 저장", say: "x" }, { label: "버리기", say: "x" }]
    : [{ label: "Try it once", say: "x" }, { label: "Save without checking", say: "x" }, { label: "Discard", say: "x" }],
  failed: ko
    ? [{ label: "다시 보여 주기", say: "x" }, { label: "그래도 저장", say: "x" }, { label: "버리기", say: "x" }]
    : [{ label: "Show again", say: "x" }, { label: "Save anyway", say: "x" }, { label: "Discard", say: "x" }],
};

let learn: LearnState = idleLearn;
if (state === "learning") {
  learn = applyLearnEvent(idleLearn, "demo_started", { label: ko ? "쿠팡 장바구니" : "Coupang cart" });
  const steps = [
    { n: 1, kind: "fill", name: ko ? "상품명, 카테고리명 으로 검색" : "Search", where: "coupang.com" },
    { n: 2, kind: "press", name: ko ? "상품명, 카테고리명 으로 검색" : "Search", where: "coupang.com" },
    { n: 3, kind: "click", name: ko ? "장바구니 담기" : "Add to cart", where: "coupang.com/vp/products/123" },
  ];
  for (const step of steps) learn = applyLearnEvent(learn, "demo_step", step);
}
if (state === "replaying") {
  learn = applyLearnEvent(idleLearn, "demo_replay_started", { total: 4 });
  learn = applyLearnEvent(learn, "demo_replay_step", { n: 1, text: "https://www.coupang.com/ 을 연다", ok: true });
  learn = applyLearnEvent(learn, "demo_replay_step", { n: 2, text: "「상품명, 카테고리명 으로 검색」 칸에 닌텐도 을 넣는다", ok: true });
  learn = applyLearnEvent(learn, "demo_replay_step", { n: 3, text: "Enter 를 누른다  → 확인: 주소가 바뀐다", ok: null });
}

const draft = state === "menu" ? "/" : "";
const shown: ConversationMessage[] = [];
if (state === "offer") shown.push(message(1, "user", ko ? "쿠팡에서 장바구니에 담아 줘" : "Add it to my Coupang cart"), message(2, "assistant", OFFER, { quick_replies: buttons.offer }));
if (state === "review") shown.push(message(1, "user", ko ? "다 했어" : "done"), message(2, "assistant", REVIEW, { quick_replies: buttons.review }));
if (state === "failed") shown.push(message(1, "user", ko ? "한 번 해 볼게요" : "try it once"), message(2, "assistant", FAILED, { quick_replies: buttons.failed }));

function Harness() {
  return (
    <main className="jarvis-workspace mode-cowork" style={{ display: "block", minHeight: "100vh" }}>
      <div style={{ width: "min(820px, 100%)", margin: "0 auto", padding: "24px 16px 12px" }}>
        <div className="message-column">
          {shown.map((item, index) => (
            <MessageView key={item.id} message={item} onSay={index === shown.length - 1 ? () => undefined : undefined} />
          ))}
        </div>
      </div>
      <footer style={{ width: "min(820px, 100%)", margin: "0 auto", padding: "0 16px 24px" }}>
        <RecipeLearnPanel state={learn} onDone={() => undefined} onCancel={() => undefined} />
        <form className="workspace-composer" onSubmit={(event) => event.preventDefault()}>
          <SlashMenu items={slashMenu(draft, language)} index={0} onPick={() => undefined} />
          <textarea defaultValue={draft} rows={1} placeholder="Sonjari에게 메시지를 보내거나 파일을 맡겨보세요" />
        </form>
      </footer>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Harness />);
