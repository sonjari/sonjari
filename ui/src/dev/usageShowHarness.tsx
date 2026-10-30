// 개발용 연습 화면 — 「쓰는 법」 쇼(UsageShowGate 의 네 장)를 본체 없이 띄워 본다. 앱 빌드에는 안 들어간다.
// ?at=N 시작 장(0~3) · ?lang=en 영어 · ?freeze=N 장면을 N번째 박자에 세워 둠(스크린샷용 · 움직임을 줄인 모습은 N 을 크게).
import ReactDOM from "react-dom/client";
import "../styles.css";
import "../workspace.css";
import { WhatsNewDeck } from "../workspace/WhatsNewDeck";
import { usageSlides } from "../workspace/UsageShowGate";
import { freezeBeats } from "../workspace/showKit";
import { setLangForTest } from "../i18n";

const query = new URLSearchParams(location.search);
if (query.get("lang") === "en") setLangForTest("en");
if (query.has("freeze")) freezeBeats(Number(query.get("freeze")));
const start = Number(query.get("at") ?? 0);

function Harness() {
  return (
    <WhatsNewDeck key={start} version="" slides={usageSlides()} changes="" tour="" initialIndex={start} eyebrow={start >= 0 ? "손자리 쓰는 법" : ""}
      onLater={() => undefined} onDone={() => undefined} onOpenSettings={(section) => console.log("open settings", section)} />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Harness />);
