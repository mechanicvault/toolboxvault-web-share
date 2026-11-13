import { useState, type ReactNode } from "react";
import { Button } from "../../../components";
import { PhotoUploader } from "./PhotoUploader";
import type { AttachmentKind } from "./photoTransfer";
import "../itemPage.css";

/**
 * One file area's own Add flow (owner ruling 2026-11-03): every
 * file area on the item page — Photos, Documents, Receipts,
 * Manuals — carries an Add button of its own that opens the
 * upload flow scoped to that kind, WITHOUT entering the item's
 * Edit form. Saving lands the file in the area immediately (the
 * page's refresh re-reads the record in place). The Edit form's
 * uploaders keep working exactly as before; this is the same
 * PhotoUploader + transfer pipeline, pointed at the same
 * per-record endpoints.
 *
 * `children` render under the uploader while it's open — the
 * Manuals area passes its add-by-link form there.
 */
export function AddFiles({
  basePath,
  kind,
  addLabel,
  onUploaded,
  children,
  buttonId,
}: {
  /** The item's API path (`/inventory/{id}`,
   *  `/inventory/batteries/{id}`). */
  basePath: string;
  kind: AttachmentKind;
  addLabel: string;
  onUploaded: () => void;
  children?: ReactNode;
  /** Optional id for the Add button — the health check's
   *  photo Fix-it link lands on it (lib/fixFocus). */
  buttonId?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tv-item-addfiles">
      <div className="tv-item-addbar">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          id={buttonId}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Done" : addLabel}
        </Button>
      </div>
      {open && (
        <>
          <PhotoUploader
            toolId=""
            basePath={basePath}
            kind={kind}
            onUploaded={onUploaded}
          />
          {children}
        </>
      )}
    </div>
  );
}
