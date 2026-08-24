import { Eye, History, Radio } from "lucide-react";
import type { ReplayMode } from "../contract/v1";

export type ReplayLens = ReplayMode;

/**
 * Lenses the current scene structurally cannot serve, with the one reason why.
 *
 * A live scene exists only as witnessed: separate as-known and retrospective reconstructions do
 * not exist for it, so offering those lenses as clickable controls would manufacture a request
 * that can only fail (the core answers it 409 mode_mismatch). The unavailable lenses render
 * disabled with the reason attached — a fact about the scene, presented as one, not a failure.
 */
export type LensAvailability = {
  modes: ReplayLens[];
  reason: string;
};

const lenses: Array<{
  id: ReplayLens;
  label: string;
  shortLabel: string;
  detail: string;
  Icon: typeof Eye;
}> = [
  {
    id: "knowledge_cutoff",
    label: "Earlier knowledge cutoff",
    shortLabel: "As known",
    detail: "Separately served earlier cutoff",
    Icon: Radio,
  },
  {
    id: "witnessed",
    label: "Witnessed replay",
    shortLabel: "Witnessed",
    detail: "Only what was knowable then",
    Icon: Eye,
  },
  {
    id: "retrospective",
    label: "Retrospective replay",
    shortLabel: "Later",
    detail: "Includes later evidence",
    Icon: History,
  },
];

export function ReplaySwitch({
  value,
  onChange,
  pending,
  unavailable,
}: {
  value: ReplayLens;
  onChange(value: ReplayLens): void;
  pending: ReplayLens | null;
  unavailable?: LensAvailability;
}) {
  const unavailableModes = new Set(unavailable?.modes ?? []);
  return (
    <fieldset className="replay-switch" aria-describedby="replay-help">
      <legend>Replay lens</legend>
      <div className="segmented-control">
        {lenses.map(({ id, label, shortLabel, detail, Icon }) => {
          const lensUnavailable = unavailableModes.has(id) && id !== value;
          return (
            <label
              key={id}
              className="segment"
              data-active={value === id}
              data-unavailable={lensUnavailable || undefined}
            >
              <input
                type="radio"
                name="replay-lens"
                value={id}
                checked={value === id}
                onChange={() => onChange(id)}
                disabled={pending !== null || lensUnavailable}
                aria-describedby={lensUnavailable ? "replay-unavailable" : undefined}
              />
              <Icon aria-hidden="true" size={18} />
              <span className="segment-copy">
                <span>{shortLabel}</span>
                <small>{lensUnavailable ? "Does not exist for this scene" : detail}</small>
              </span>
              <span className="sr-only">
                {label}
                {lensUnavailable ? ` — unavailable: ${unavailable?.reason ?? ""}` : ""}
              </span>
            </label>
          );
        })}
      </div>
      {unavailable && unavailableModes.size > 0 && (
        <p id="replay-unavailable" className="replay-unavailable">
          {unavailable.reason}
        </p>
      )}
      <span id="replay-help" className="sr-only">
        Each lens loads a distinct immutable snapshot. Press R outside a text field to cycle
        available lenses.
      </span>
    </fieldset>
  );
}
