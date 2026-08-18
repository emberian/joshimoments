import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import OperationalGlassShell from "./operational/OperationalShell";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root application mount");

createRoot(root).render(
  <StrictMode>
    <OperationalGlassShell />
  </StrictMode>,
);
