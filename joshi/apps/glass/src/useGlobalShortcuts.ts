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
  onHoldCandidate(): void;
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

/**
 * Why the hold key is `;` and not a letter.
 *
 * Every other single-key shortcut in this shell is a letter, and a screen reader in browse mode
 * eats letters before the page ever sees them: `h`, `d`, `f`, `i`, `k` and `p` are all quick-nav
 * commands in NVDA and JAWS, and VoiceOver's Quick Nav claims letters too. That is a live defect
 * for the rest of this scheme and it is reported as one -- but the hold gesture is the one that
 * has to work while she is racing, so it must not be a letter at all.
 *
 * `;` is claimed by no major screen reader's quick navigation, sits on the home row under one
 * finger, and needs no modifier and no second hand. `:` is accepted alongside it so a held or
 * sticky Shift never costs her the coin.
 */
const HOLD_KEYS = new Set([";", ":"]);

export function useGlobalShortcuts(options: ShortcutOptions): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        options.onOpenCommands();
        return;
      }
      if (isTypingTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;

      // Held first, and before the lowercase fold, so a shifted press still holds.
      if (HOLD_KEYS.has(event.key)) {
        event.preventDefault();
        options.onHoldCandidate();
        return;
      }

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
