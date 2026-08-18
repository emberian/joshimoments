import { useEffect } from "react";

type ShortcutOptions = {
  onOpenCommands(): void;
  onFocusSearch(): void;
  onMoveSelection(direction: 1 | -1): void;
  onToggleDensity(): void;
  onCycleReplay(): void;
  onToggleProvenance(): void;
  onOpenInspector(): void;
  onRecordFocus(): void;
  onOpenHypothesisLab(): void;
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.matches("input, textarea, select") ||
    target.isContentEditable ||
    target.closest("[role='dialog']") !== null ||
    target.closest("[data-shortcuts-disabled='true']") !== null
  );
}

export function useGlobalShortcuts(options: ShortcutOptions): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        options.onOpenCommands();
        return;
      }
      if (isTypingTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;

      switch (event.key.toLowerCase()) {
        case "/":
          event.preventDefault();
          options.onFocusSearch();
          break;
        case "j":
        case "arrowdown":
          event.preventDefault();
          options.onMoveSelection(1);
          break;
        case "k":
        case "arrowup":
          event.preventDefault();
          options.onMoveSelection(-1);
          break;
        case "d":
          event.preventDefault();
          options.onToggleDensity();
          break;
        case "r":
          event.preventDefault();
          options.onCycleReplay();
          break;
        case "p":
          event.preventDefault();
          options.onToggleProvenance();
          break;
        case "i":
          event.preventDefault();
          options.onOpenInspector();
          break;
        case "f":
          event.preventDefault();
          options.onRecordFocus();
          break;
        case "h":
          event.preventDefault();
          options.onOpenHypothesisLab();
          break;
        case "?":
          event.preventDefault();
          options.onOpenCommands();
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [options]);
}
