import { useEffect, useMemo, useRef, useState } from "react";
import { Command, Search, X } from "lucide-react";

import type { Candidate } from "../contract/v1";

export type ShellCommand = {
  id: string;
  label: string;
  detail: string;
  shortcut?: string;
  run(): void;
};

export function CommandPalette({
  open,
  commands,
  candidates,
  onClose,
  onSelectCandidate,
}: {
  open: boolean;
  commands: ShellCommand[];
  candidates: Candidate[];
  onClose(): void;
  onSelectCandidate(candidateId: string): void;
}) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    requestAnimationFrame(() => inputRef.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key === "Tab") {
        const dialog = inputRef.current?.closest<HTMLElement>("[role='dialog']");
        const focusable = dialog?.querySelectorAll<HTMLElement>("button, input, [href], [tabindex]:not([tabindex='-1'])");
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first && last) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last && first) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, open]);

  const normalized = query.trim().toLowerCase();
  const matchingCommands = useMemo(
    () => commands.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(normalized)),
    [commands, normalized],
  );
  const matchingCandidates = useMemo(
    () => candidates.filter((item) => `${item.symbol} ${item.name} ${item.tags.join(" ")}`.toLowerCase().includes(normalized)).slice(0, 6),
    [candidates, normalized],
  );

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section className="command-dialog" role="dialog" aria-modal="true" aria-labelledby="command-title">
        <header>
          <span><Command aria-hidden="true" /><strong id="command-title">Navigate the glass</strong></span>
          <button ref={closeRef} type="button" className="icon-button" aria-label="Close command menu" onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <label className="command-search">
          <Search aria-hidden="true" />
          <span className="sr-only">Filter commands and coins</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Type a command or coin"
          />
        </label>
        <div className="command-results">
          <section aria-labelledby="shell-command-heading">
            <h3 id="shell-command-heading">View commands</h3>
            {matchingCommands.map((item) => (
              <button type="button" key={item.id} onClick={() => { item.run(); onClose(); }}>
                <span><strong>{item.label}</strong><small>{item.detail}</small></span>
                {item.shortcut && <kbd>{item.shortcut}</kbd>}
              </button>
            ))}
          </section>
          <section aria-labelledby="coin-command-heading">
            <h3 id="coin-command-heading">Focus a coin</h3>
            {matchingCandidates.map((candidate) => (
              <button type="button" key={candidate.id} onClick={() => { onSelectCandidate(candidate.id); onClose(); }}>
                <span><strong>${candidate.symbol}</strong><small>{candidate.name} · {candidate.attentionReason}</small></span>
              </button>
            ))}
          </section>
          {matchingCommands.length + matchingCandidates.length === 0 && <p className="empty-command">No matching view command or coin.</p>}
        </div>
        <footer>Evidence-only shell · no capital actions are available</footer>
      </section>
    </div>
  );
}
