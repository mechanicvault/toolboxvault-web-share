import { useState } from "react";
import { Button, Panel } from "../../../components";
import { SideList, SideListRow } from "../../../components/SideList";
import { LocateManualPanel } from "../../catalog/LocateManualPanel";
import { ManualLinkForm } from "../../catalog/ManualLinkForm";
import type { Attachment } from "../types";
import { AddFiles } from "./AddFiles";
import { AttachmentList } from "./AttachmentList";

type FileSection = "document" | "receipt" | "manual";

/**
 * The item page's Documents & Receipts tab as a LEFT-HAND MENU
 * (owner's sheet row, 2026-11-15 — the old stack of three panels
 * was "cluttered and hard to read"): the shared Side List frame
 * carries Documents / Receipts / Manuals on the left, and the
 * window on the right shows the picked area's files with its
 * own Add button. The Manuals window also carries a "Locate
 * manual" button that opens the manual finder in place, in the
 * window. One component for both item pages (tools + batteries)
 * so the two tabs can never drift apart.
 */
export function ItemFilesTab({
  basePath,
  segment,
  itemId,
  itemName,
  brand,
  model,
  documents,
  receipts,
  manuals,
  onView,
  onChanged,
}: {
  /** The item's API path (`/inventory/{id}`,
   *  `/inventory/batteries/{id}`) — attachments hang off it. */
  basePath: string;
  segment: "tools" | "batteries";
  itemId: string;
  itemName: string;
  brand: string;
  model: string;
  documents: Attachment[];
  receipts: Attachment[];
  manuals: Attachment[];
  onView: (attachment: Attachment, emailPath: string) => void;
  /** Fired after any upload / delete / save — the page re-reads
   *  the record in place. */
  onChanged: () => void;
}) {
  const [section, setSection] = useState<FileSection>("document");
  const [locateOpen, setLocateOpen] = useState(false);

  const areas: {
    kind: FileSection;
    title: string;
    items: Attachment[];
    addLabel: string;
    emptyText: string;
  }[] = [
    {
      kind: "document",
      title: "Documents",
      items: documents,
      addLabel: "Add a document",
      emptyText: "No documents yet.",
    },
    {
      kind: "receipt",
      title: "Receipts",
      items: receipts,
      addLabel: "Add a receipt",
      emptyText: "No receipts yet.",
    },
    {
      kind: "manual",
      title: "Manuals",
      items: manuals,
      addLabel: "Add a manual",
      emptyText: "No manuals yet.",
    },
  ];
  const active = areas.find((a) => a.kind === section) ?? areas[0];
  const countLine = (n: number) =>
    n === 0 ? "No files yet" : n === 1 ? "1 file" : `${n} files`;

  return (
    <SideList
      listLabel="File areas"
      list={
        <>
          {areas.map((a) => (
            <SideListRow
              key={a.kind}
              selected={section === a.kind}
              onSelect={() => setSection(a.kind)}
              title={a.title}
              sub={countLine(a.items.length)}
            />
          ))}
        </>
      }
      panel={
        <Panel title={`${active.title} (${active.items.length})`}>
          <AddFiles
            basePath={basePath}
            kind={active.kind}
            addLabel={active.addLabel}
            onUploaded={onChanged}
            extraActions={
              active.kind === "manual" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  aria-expanded={locateOpen}
                  onClick={() => setLocateOpen((v) => !v)}
                >
                  {locateOpen ? "Close manual finder" : "Locate manual"}
                </Button>
              ) : undefined
            }
          >
            {active.kind === "manual" ? (
              <ManualLinkForm
                segment={segment}
                itemId={itemId}
                itemName={itemName}
                onSaved={onChanged}
              />
            ) : undefined}
          </AddFiles>
          {active.kind === "manual" && locateOpen && (
            <LocateManualPanel
              segment={segment}
              itemId={itemId}
              itemName={itemName}
              brand={brand}
              model={model}
              onSaved={onChanged}
            />
          )}
          {active.items.length > 0 ? (
            <AttachmentList
              items={active.items}
              layout="tiles"
              emailPath={`${basePath}/attachments/email`}
              onView={onView}
              deletePath={`${basePath}/attachments`}
              onDeleted={onChanged}
            />
          ) : (
            <p className="tv-item-tabnote">{active.emptyText}</p>
          )}
        </Panel>
      }
    />
  );
}
