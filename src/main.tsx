import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { trace, debug, info, warn, error, attachConsole } from "@tauri-apps/plugin-log";

// 将浏览器控制台日志转发到 Tauri 日志系统（最终写入 frontend.log）
function forwardConsole() {
  const originalLog = console.log;
  const originalDebug = console.debug;
  const originalInfo = console.info;
  const originalWarn = console.warn;
  const originalError = console.error;

  console.log = (...args) => {
    originalLog(...args);
    trace(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
  };
  console.debug = (...args) => {
    originalDebug(...args);
    debug(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
  };
  console.info = (...args) => {
    originalInfo(...args);
    info(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
  };
  console.warn = (...args) => {
    originalWarn(...args);
    warn(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
  };
  console.error = (...args) => {
    originalError(...args);
    error(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
  };
}

attachConsole().then(() => {
  forwardConsole();
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
