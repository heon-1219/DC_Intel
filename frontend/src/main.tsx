import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { LangProvider } from "./hooks/useT";
import "./styles/tokens.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LangProvider>
      <App />
    </LangProvider>
  </StrictMode>,
);
