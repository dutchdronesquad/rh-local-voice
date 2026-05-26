import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { App } from "./index";

const container = document.getElementById("root")!;

const root: ReturnType<typeof createRoot> =
  (import.meta.hot?.data as { root?: ReturnType<typeof createRoot> } | undefined)?.root ??
  createRoot(container);

if (import.meta.hot) {
  (import.meta.hot.data as { root: ReturnType<typeof createRoot> }).root = root;
}

root.render(
  <StrictMode>
    <TooltipProvider>
      <App />
    </TooltipProvider>
  </StrictMode>,
);
