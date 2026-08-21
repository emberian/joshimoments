import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import OperationalGlassShell from "./operational/OperationalShell";
import CockpitV2InspectorShell from "./operational/CockpitV2Inspector";
import LiveSurfaceShell from "./operational/LiveSurfaceShell";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root application mount");

const inspectorMode = import.meta.env.VITE_JOSHI_G0_INSPECTOR === "1"
  ? "offline_fixture"
  : import.meta.env.VITE_JOSHI_ORDINARY_PAIRING === "1"
    ? "local_store"
    : null;
// One explicitly named immutable scene that a local core derived from a real catalog and is
// serving. It is a distinct mode because it names its launch scene instead of choosing one.
const liveSurface = import.meta.env.VITE_JOSHI_LIVE_SURFACE === "1";

createRoot(root).render(
  <StrictMode>
    {liveSurface
      ? <LiveSurfaceShell />
      : inspectorMode
        ? <CockpitV2InspectorShell sourceKind={inspectorMode} />
        : <OperationalGlassShell />}
  </StrictMode>,
);
