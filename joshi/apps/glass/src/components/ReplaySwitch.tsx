import { Eye, History, Radio } from "lucide-react";
import type { ReplayMode } from "../contract/v1";

export type ReplayLens = ReplayMode;

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
}: {
  value: ReplayLens;
  onChange(value: ReplayLens): void;
  pending: ReplayLens | null;
}) {
  return (
    <fieldset className="replay-switch" aria-describedby="replay-help">
      <legend>Replay lens</legend>
      <div className="segmented-control">
        {lenses.map(({ id, label, shortLabel, detail, Icon }) => (
          <label key={id} className="segment" data-active={value === id}>
            <input
              type="radio"
              name="replay-lens"
              value={id}
              checked={value === id}
              onChange={() => onChange(id)}
              disabled={pending !== null}
            />
            <Icon aria-hidden="true" size={18} />
            <span className="segment-copy">
              <span>{shortLabel}</span>
              <small>{detail}</small>
            </span>
            <span className="sr-only">{label}</span>
          </label>
        ))}
      </div>
      <span id="replay-help" className="sr-only">
        Each lens loads a distinct immutable snapshot. Press R outside a text field to cycle lenses.
      </span>
    </fieldset>
  );
}
