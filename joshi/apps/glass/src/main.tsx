import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import OperationalGlassShell from "./operational/OperationalShell";
import CockpitV2InspectorShell from "./operational/CockpitV2Inspector";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root application mount");

createRoot(root).render(
  <StrictMode>
    {import.meta.env.VITE_JOSHI_G0_INSPECTOR === "1"
      ? <CockpitV2InspectorShell />
      : <OperationalGlassShell ordinaryPairingEnabled={import.meta.env.VITE_JOSHI_ORDINARY_PAIRING === "1"} />}
  </StrictMode>,
);
