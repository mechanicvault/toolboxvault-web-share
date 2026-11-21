import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { installChunkRecovery } from "./lib/chunkRecovery";

// If a deploy rotated the hashed chunk files while this tab was
// open, Vite's failed-preload event reloads us once into the fresh
// build instead of leaving a blank page (see lib/chunkRecovery).
installChunkRecovery();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
