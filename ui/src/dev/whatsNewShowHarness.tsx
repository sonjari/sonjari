// 개발용 연습 화면 — 업데이트 「바뀐 것」 슬라이드의 쇼(WhatsNewShow)를 본체 없이 띄워 본다. 앱 빌드에는 안 들어간다.
// 글꼴은 이 PC 에서 도는 본체(127.0.0.1:8091)의 `/v1/slides/fonts/` 에서 받는다 — 본체가 꺼져 있으면 윈도우 글꼴로 그린다.
import ReactDOM from "react-dom/client";
import "../styles.css";
import notes from "../../../src/alture_jarvis/whats_new/0.4.34.0.json";
import type { WhatsNewSlide } from "../types";
import { WhatsNewDeck } from "../workspace/WhatsNewDeck";
import { setSlideFontBase } from "../workspace/slideFonts";

setSlideFontBase("http://127.0.0.1:8091");
const lang = new URLSearchParams(location.search).get("lang") === "en" ? "en" : "ko";
const pack = notes[lang];
const start = Number(new URLSearchParams(location.search).get("at") ?? 0);

function Harness() {
  return (
    <WhatsNewDeck key={start} version="0.4.34.0" slides={pack.slides as WhatsNewSlide[]} changes={pack.changes} tour={pack.tour}
      onLater={() => undefined} onDone={() => undefined} />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Harness />);
