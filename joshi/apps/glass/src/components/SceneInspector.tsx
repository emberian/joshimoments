import * as Dialog from "@radix-ui/react-dialog";
import { Database, ShieldCheck, X } from "lucide-react";

import type { GlassSnapshotV1 } from "../contract/v1";
import type { JournalEntry } from "../operator/useOperatorJournal";
import type { PresentationEventReceiptV1, PresentationSceneReceiptV1, PresentationSceneV1 } from "../presentation/contract";
import type { ChoiceSets } from "./OperatorCapture";

export function SceneInspector({
  open,
  onOpenChange,
  snapshot,
  choiceSets,
  sceneEntries,
  presentationScene,
  presentationReceipt,
  presentationEventReceipts,
  presentationGap,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  snapshot: GlassSnapshotV1;
  choiceSets: ChoiceSets;
  sceneEntries: JournalEntry[];
  presentationScene: PresentationSceneV1 | null;
  presentationReceipt: PresentationSceneReceiptV1 | null;
  presentationEventReceipts: PresentationEventReceiptV1[];
  presentationGap: string | null;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="capture-overlay" />
        <Dialog.Content className="scene-inspector" aria-describedby="scene-inspector-description" data-shortcuts-disabled="true">
          <header>
            <span><Database aria-hidden="true" /><Dialog.Title>Scene provenance inspector</Dialog.Title></span>
            <Dialog.Close className="icon-button" aria-label="Close scene provenance inspector"><X aria-hidden="true" /></Dialog.Close>
          </header>
          <Dialog.Description id="scene-inspector-description">
            Exact identity, choice context, source clocks, and command receipts for only the currently rendered immutable scene.
          </Dialog.Description>
          <div className="inspector-scroll">
            <section aria-labelledby="scene-identity-title">
              <h3 id="scene-identity-title">Immutable view</h3>
              <dl className="inspector-grid">
                <div><dt>Mode</dt><dd>{snapshot.view.mode}</dd></div>
                <div><dt>Scene</dt><dd>{snapshot.view.sceneId}</dd></div>
                <div><dt>Witnessed basis</dt><dd>{snapshot.view.basisSceneId ?? "none"}</dd></div>
                <div><dt>View digest</dt><dd>{snapshot.snapshotDigest}</dd></div>
                <div><dt>Catalog commit</dt><dd>{snapshot.view.asOf.catalogCommit}</dd></div>
                <div><dt>Rendered</dt><dd>{snapshot.view.asOf.renderedAt}</dd></div>
              </dl>
              <p className="inspector-safety"><ShieldCheck aria-hidden="true" /> A command cites this scene ID and digest. Marks from another replay mode are not substituted into this view.</p>
            </section>

            <section aria-labelledby="choice-context-title">
              <h3 id="choice-context-title">Current choice context</h3>
              <p>These sets remain distinct. Being served, filtered into view, visible in the viewport, interacted with, and compared are not treated as synonyms.</p>
              <dl className="choice-inspector">
                {(Object.entries(choiceSets) as Array<[keyof ChoiceSets, string[]]>).map(([kind, members]) => (
                  <div key={kind}>
                    <dt>{kind} · {members.length}</dt>
                    <dd>{members.length > 0 ? members.join(", ") : "empty"}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <section aria-labelledby="watermark-title">
              <h3 id="watermark-title">Source and projection watermarks</h3>
              <ul className="inspector-list">
                {snapshot.view.asOf.sources.map((source) => <li key={source.sourceId}>
                  <strong>{source.sourceId}</strong>
                  <span>delivered {source.deliveredThrough}; received {source.receivedThrough}; {source.cursors.length} scoped cursor{source.cursors.length === 1 ? "" : "s"}</span>
                </li>)}
                {snapshot.view.asOf.projections.map((projection) => <li key={projection.name}>
                  <strong>{projection.name} v{projection.version}</strong><span>{projection.stateDigest}</span>
                </li>)}
              </ul>
            </section>

            <section aria-labelledby="scene-command-title">
              <h3 id="scene-command-title">Append receipts</h3>
              {sceneEntries.length === 0 ? <p>No operator commands reference this scene.</p> : <ol className="inspector-list">
                {sceneEntries.map((entry) => <li key={entry.command.commandId}>
                  <strong>{entry.label} · {entry.status}</strong>
                  <span>{entry.command.commandId}</span>
                  <span>{entry.receipt ? `commit ${entry.receipt.commitSeq} · ${entry.receipt.commandDigest}` : "No durable receipt yet"}</span>
                </li>)}
              </ol>}
            </section>

            <section aria-labelledby="presentation-scene-title">
              <h3 id="presentation-scene-title">Presentation witness</h3>
              {!presentationScene ? <p>No presentation scene has been prepared.</p> : <>
                <dl className="inspector-grid">
                  <div><dt>Presentation</dt><dd>{presentationScene.presentationId}</dd></div>
                  <div><dt>Policy</dt><dd>{presentationScene.policy.policyId} v{presentationScene.policy.policyVersion}</dd></div>
                  <div><dt>Policy digest</dt><dd>{presentationScene.policy.policyDigest}</dd></div>
                  <div><dt>Presentation digest</dt><dd>{presentationReceipt?.presentationDigest ?? "no durable receipt"}</dd></div>
                  <div><dt>Eligible / planned render</dt><dd>{presentationScene.manifest.eligibleItemIds.length} / {presentationScene.manifest.plannedRenderItemIds.length}</dd></div>
                  <div><dt>Interaction receipts</dt><dd>{presentationEventReceipts.length}</dd></div>
                </dl>
                <details className="presentation-manifest-details">
                  <summary>Exact staged plan, omissions, and controls</summary>
                  <ul className="inspector-list">{presentationScene.manifest.items.map((item) => <li key={item.itemId}>
                    <strong>{item.itemId} · {item.visibility} · {item.salience}</strong>
                    <span>{item.placement} ordinal {item.ordinal}; {item.evidenceClass}; {item.omissionReason ? `omitted: ${item.omissionReason}` : "not omitted"}</span>
                  </li>)}</ul>
                </details>
                {presentationGap && <p className="presentation-gap"><strong>Capture gap:</strong> {presentationGap}</p>}
              </>}
            </section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
