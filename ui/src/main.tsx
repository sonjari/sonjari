import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import { isMac } from "./platform";

// 맥 판 표시 — tokens.css 의 :root[data-os="mac"] (짙은 바탕 디더링 물결 · 11-04).
if (isMac) document.documentElement.dataset.os = "mac";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
