import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  AttachmentViewer,
  Badge,
  Button,
  DatePicker,
  FormField,
  formGridStyle,
  Panel,
  Select,
  TextInput,
  type ViewableAttachment,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { todayLocalIso } from "../../../lib/format";
import { type DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import {
  REPAIR_STATE_LABELS,
  REPAIR_STATE_TONES,
} from "../../maintenance/format";
import { money } from "../format";
import type { AttachedToolRef, SetPiece, Tool } from "../types";
import { PhotoUploader } from "./PhotoUploader";
import { AttachmentDeleteControl } from "./AttachmentList";

const PIECE_STATUSES = ["present", "missing", "sold", "removed"] as const;

const PIECE_STATUS_LABEL_KEYS: Record<(typeof PIECE_STATUSES)[number], DictKey> = {
  present: "wizard.pieceStatus.present",
  missing: "wizard.pieceStatus.missing",
  sold: "wizard.pieceStatus.sold",
  removed: "wizard.pieceStatus.removed",
};

interface PieceFormState {
  name: string;
  part_number: string;
  serial_number: string;
  price: string;
  purchase_date: string;
}

function emptyPiece(): PieceFormState {
  return {
    name: "",
    part_number: "",
    serial_number: "",
    price: "",
    /* A new piece starts on today (owner's date rule, 2026-11-04);
     * editing a piece loads its saved date instead. */
    purchase_date: todayLocalIso(),
  };
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * The set structure on a set's detail page: core pieces, addon
 * pieces (each may carry its own price — a core piece's price is
 * the piece's own figure and never joins the set's totals), and
 * standalone tools attached as addons. Add-piece / add-addon /
 * attach-existing / detach / status changes all live here; totals
 * come from the backend's resolve_set_members so the page never
 * re-derives set math.
 *
 * Layout (row 226, owner 2026-11-20): headed sections over true
 * lists — a header row with the facts spread in columns, the
 * Main list treatment — never one flowing box of content.
 */
export function SetPanel({
  tool,
  onChanged,
}: {
  tool: Tool;
  onChanged: () => void;
}) {
  const t = useT();
  const [error, setError] = useState("");
  const [addingKind, setAddingKind] = useState<"core" | "addon" | null>(null);
  const [pieceForm, setPieceForm] = useState<PieceFormState>(emptyPiece);
  const [pieceBusy, setPieceBusy] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [candidates, setCandidates] = useState<Tool[] | null>(null);
  const [attachId, setAttachId] = useState("");
  const [attachBusy, setAttachBusy] = useState(false);
  const [expandedPiece, setExpandedPiece] = useState<string | null>(null);
  // Sold tracking (wave 2): the piece Sell flow — the status
  // select above flips presence bare; this writes the ledger.
  const [sellingPiece, setSellingPiece] = useState<string | null>(null);
  const [sellPrice, setSellPrice] = useState("");
  const [sellBuyer, setSellBuyer] = useState("");
  const [sellBusy, setSellBusy] = useState(false);
  const [viewing, setViewing] = useState<{
    attachment: ViewableAttachment;
    emailPath: string;
    /** The owning piece's attachments endpoint — the viewer
     *  hosts the piece photo's delete (owner correction
     *  2026-11-04 22:19: deletes live only inside the viewer). */
    deletePath?: string;
  } | null>(null);

  const set = tool.set;

  useEffect(() => {
    if (!attachOpen) return;
    api<Tool[]>("/inventory?limit=200")
      .then((rows) =>
        setCandidates(
          rows.filter(
            (t) => t.id !== tool.id && !t.is_set && !t.attached_to_set_id,
          ),
        ),
      )
      .catch(() => setCandidates([]));
  }, [attachOpen, tool.id]);

  async function addPiece(e: FormEvent) {
    e.preventDefault();
    if (!addingKind) return;
    setError("");
    if (!pieceForm.name.trim()) {
      setError("Give the piece a name.");
      return;
    }
    setPieceBusy(true);
    try {
      await api(`/inventory/${tool.id}/pieces`, {
        method: "POST",
        body: JSON.stringify({
          kind: addingKind,
          name: pieceForm.name.trim(),
          part_number: pieceForm.part_number.trim(),
          serial_number: pieceForm.serial_number.trim(),
          price: pieceForm.price !== "" ? pieceForm.price : null,
          purchase_date:
            pieceForm.purchase_date !== "" ? pieceForm.purchase_date : null,
        }),
      });
      setPieceForm(emptyPiece());
      setAddingKind(null);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the piece.");
    } finally {
      setPieceBusy(false);
    }
  }

  async function setStatus(piece: SetPiece, status: string) {
    setError("");
    try {
      await api(`/inventory/pieces/${piece.id}`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update the piece.");
    }
  }

  async function sellPiece(piece: SetPiece) {
    if (sellPrice === "") return;
    setSellBusy(true);
    setError("");
    try {
      await api(`/inventory/sets/${tool.id}/pieces/${piece.id}/mark-sold`, {
        method: "POST",
        body: JSON.stringify({
          sale_price: sellPrice,
          buyer_name: sellBuyer.trim(),
          buyer_contact: "",
          sold_on: null,
          note: "",
        }),
      });
      setSellingPiece(null);
      setSellPrice("");
      setSellBuyer("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record that sale.");
    } finally {
      setSellBusy(false);
    }
  }

  async function removePiece(piece: SetPiece) {
    if (!window.confirm(`Remove "${piece.name}" from this set? Its attached files are deleted too.`)) return;
    setError("");
    try {
      await api(`/inventory/pieces/${piece.id}`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the piece.");
    }
  }

  async function attach() {
    if (!attachId) return;
    setAttachBusy(true);
    setError("");
    try {
      await api(`/inventory/${attachId}/attach-to-set`, {
        method: "POST",
        body: JSON.stringify({ set_id: tool.id }),
      });
      setAttachId("");
      setAttachOpen(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't attach that tool.");
    } finally {
      setAttachBusy(false);
    }
  }

  async function detach(toolId: string) {
    setError("");
    try {
      await api(`/inventory/${toolId}/detach`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't detach that tool.");
    }
  }

  if (!set) return null;

  const listHead = (
    <div className="tv-setp-thead" role="row">
      <span className="tv-setp-th" role="columnheader">Piece</span>
      <span className="tv-setp-th" role="columnheader">Part #</span>
      <span className="tv-setp-th" role="columnheader">Status</span>
      <span className="tv-setp-th tv-setp-th--num" role="columnheader">Price</span>
      <span className="tv-setp-th" role="columnheader">Files</span>
      <span className="tv-setp-th" role="columnheader">
        <span className="tv-setp-sr">Actions</span>
      </span>
    </div>
  );

  const pieceRow = (piece: SetPiece) => {
    // Row 199: the piece's own photo shows on its row — the
    // first photo attachment, click to view it. (The API
    // serializes a fresh view url onto each attachment; the
    // shared Attachment type predates it.)
    const photo = piece.attachments.find(
      (a) => a.kind === "photo" && (a as { url?: string }).url,
    ) as (typeof piece.attachments)[number] & { url?: string } | undefined;
    const dim = piece.status === "sold" || piece.status === "removed";
    return (
      <div key={piece.id} className="tv-setp-row" role="row" data-dim={dim || undefined}>
        <div className="tv-setp-cell tv-setp-cell--piece" role="cell">
          {photo && photo.url ? (
            <button
              type="button"
              className="tv-setp-thumb-btn"
              onClick={() =>
                setViewing({
                  attachment: photo,
                  emailPath: `/inventory/pieces/${piece.id}/attachments/email`,
                  deletePath: `/inventory/pieces/${piece.id}/attachments`,
                })
              }
              aria-label={`View photo of ${piece.name}`}
            >
              <img src={photo.url} alt="" className="tv-setp-thumb" />
            </button>
          ) : null}
          <div className="tv-setp-piece-text">
            <span className="tv-setp-piece-name">{piece.name}</span>
            {piece.serial_number && (
              <span className="tv-setp-piece-sub">SN {piece.serial_number}</span>
            )}
            {piece.repair_state && piece.repair_state !== "in_service" && (
              <span className="tv-setp-piece-badge">
                <Badge tone={REPAIR_STATE_TONES[piece.repair_state]} dot>
                  {REPAIR_STATE_LABELS[piece.repair_state]}
                  {piece.repair_problem ? ` — ${piece.repair_problem}` : ""}
                </Badge>
              </span>
            )}
          </div>
        </div>
        <div className="tv-setp-cell" role="cell">
          {piece.part_number || "—"}
        </div>
        <div className="tv-setp-cell" role="cell">
          <Select
            value={piece.status}
            onChange={(e) => void setStatus(piece, e.target.value)}
            aria-label={`Status of ${piece.name}`}
            inputSize="sm"
          >
            {PIECE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(PIECE_STATUS_LABEL_KEYS[s])}
              </option>
            ))}
          </Select>
        </div>
        <div className="tv-setp-cell tv-setp-cell--num" role="cell">
          {piece.price ? money(piece.price) : "—"}
        </div>
        <div className="tv-setp-cell" role="cell">
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setExpandedPiece(expandedPiece === piece.id ? null : piece.id)
            }
          >
            Files ({piece.attachments.length})
          </Button>
        </div>
        <div className="tv-setp-cell tv-setp-cell--actions" role="cell">
          {piece.kind === "addon" && piece.status !== "sold" && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setSellingPiece(sellingPiece === piece.id ? null : piece.id);
                setSellPrice(piece.price ?? "");
                setSellBuyer("");
              }}
            >
              Sell…
            </Button>
          )}
          <button
            type="button"
            className="tv-list-remove-btn"
            aria-label={`Remove ${piece.name}`}
            title={`Remove ${piece.name}`}
            onClick={() => void removePiece(piece)}
          >
            {"−"}
          </button>
        </div>
        {sellingPiece === piece.id && (
          <div className="tv-setp-subrow">
            <div className="tv-setp-sellform">
              <FormField label="Sale price" htmlFor={`sell-price-${piece.id}`}>
                <TextInput
                  id={`sell-price-${piece.id}`}
                  inputMode="decimal"
                  value={sellPrice}
                  onChange={(e) => setSellPrice(e.target.value)}
                  placeholder="0.00"
                />
              </FormField>
              <FormField label="Buyer (optional)" htmlFor={`sell-buyer-${piece.id}`}>
                <TextInput
                  id={`sell-buyer-${piece.id}`}
                  value={sellBuyer}
                  onChange={(e) => setSellBuyer(e.target.value)}
                />
              </FormField>
              <Button
                size="sm"
                loading={sellBusy}
                disabled={sellPrice === ""}
                onClick={() => void sellPiece(piece)}
              >
                Record sale
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSellingPiece(null)}>
                Cancel
              </Button>
            </div>
            <p className="tv-setp-hint">
              Records the sale on the ledger (the Sold view + this set's
              history) — not just the status flip.
            </p>
          </div>
        )}
        {expandedPiece === piece.id && (
          <div className="tv-setp-subrow">
            {piece.attachments.length > 0 && (
              <ul className="tv-setp-files">
                {piece.attachments.map((a) => (
                  <li key={a.key}>
                    <button
                      type="button"
                      className="tv-setp-file-link"
                      onClick={() =>
                        setViewing({
                          attachment: a,
                          emailPath: `/inventory/pieces/${piece.id}/attachments/email`,
                          deletePath: `/inventory/pieces/${piece.id}/attachments`,
                        })
                      }
                    >
                      {a.filename}
                    </button>{" "}
                    <span className="tv-setp-file-kind">({a.kind})</span>
                  </li>
                ))}
              </ul>
            )}
            <PhotoUploader
              toolId={piece.id}
              basePath={`/inventory/pieces/${piece.id}`}
              kind="photo"
              onUploaded={onChanged}
            />
          </div>
        )}
      </div>
    );
  };

  const attachedRow = (attached: AttachedToolRef) => (
    <div key={attached.id} className="tv-setp-row" role="row">
      <div className="tv-setp-cell tv-setp-cell--piece" role="cell">
        <div className="tv-setp-piece-text">
          <Link to={`/inventory/${attached.id}`} className="tv-setp-piece-link">
            {attached.name}
          </Link>
          {[attached.brand, attached.model].filter(Boolean).length > 0 && (
            <span className="tv-setp-piece-sub">
              {[attached.brand, attached.model].filter(Boolean).join(" · ")}
              {attached.quantity > 1 ? ` · ×${attached.quantity}` : ""}
            </span>
          )}
        </div>
      </div>
      <div className="tv-setp-cell" role="cell">
        {attached.model || "—"}
      </div>
      <div className="tv-setp-cell" role="cell">
        <Badge tone="neutral">attached tool</Badge>
      </div>
      <div className="tv-setp-cell tv-setp-cell--num" role="cell">
        {attached.purchase_total ? money(attached.purchase_total) : "—"}
      </div>
      <div className="tv-setp-cell" role="cell">—</div>
      <div className="tv-setp-cell tv-setp-cell--actions" role="cell">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void detach(attached.id)}
        >
          Detach to standalone
        </Button>
      </div>
    </div>
  );

  const pieceFormBlock = (
    <form onSubmit={(e) => void addPiece(e)} className="tv-setp-form">
      <p className="tv-setp-form-title">
        New {addingKind === "core" ? "core piece" : "addon piece"}
      </p>
      <div style={formGridStyle}>
        <FormField label="Name" required>
          <TextInput
            value={pieceForm.name}
            onChange={(e) => setPieceForm({ ...pieceForm, name: e.target.value })}
            placeholder={addingKind === "core" ? "e.g. 10mm socket" : "e.g. 21mm socket"}
          />
        </FormField>
        <FormField label="Part number">
          <TextInput
            value={pieceForm.part_number}
            onChange={(e) => setPieceForm({ ...pieceForm, part_number: e.target.value })}
          />
        </FormField>
        <FormField label="Serial number">
          <TextInput
            value={pieceForm.serial_number}
            onChange={(e) => setPieceForm({ ...pieceForm, serial_number: e.target.value })}
          />
        </FormField>
        <FormField label="Price (optional)">
          <TextInput
            type="number"
            min="0"
            step="any"
            value={pieceForm.price}
            onChange={(e) => setPieceForm({ ...pieceForm, price: e.target.value })}
          />
        </FormField>
        <FormField label="Purchase date">
          <DatePicker
            value={pieceForm.purchase_date}
            onChange={(v) =>
              setPieceForm({ ...pieceForm, purchase_date: v })
            }
            clearable
          />
        </FormField>
      </div>
      <p className="tv-setp-hint">
        A piece's price is its own number — what that piece cost,
        or what it would cost to replace. It doesn't change the
        set's price.
      </p>
      <div className="tv-setp-form-actions">
        <Button type="submit" size="sm" loading={pieceBusy}>
          Add piece
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setAddingKind(null)}
        >
          Cancel
        </Button>
      </div>
    </form>
  );

  const allPieces = [...set.core_pieces, ...set.addon_pieces];
  const presentCount = allPieces.filter((p) => p.status === "present").length;

  return (
    <Panel title="Set contents" variant="accent-edge">
      {error && (
        <div className="tv-setp-error">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {allPieces.length > 0 && (
        <p className="tv-setp-legend">{t("wizard.setStatusHelp")}</p>
      )}

      <section className="tv-setp-section">
        <header className="tv-setp-head">
          <h3 className="tv-setp-title">Core pieces</h3>
          <span className="tv-setp-note">Part of the set from the start</span>
          <span className="tv-setp-count">
            {countLabel(set.core_pieces.length, "piece")}
          </span>
        </header>
        {set.core_pieces.length > 0 ? (
          <div className="tv-setp-list" role="table">
            {listHead}
            {set.core_pieces.map(pieceRow)}
          </div>
        ) : (
          <p className="tv-setp-empty">No core pieces yet.</p>
        )}
        {addingKind === "core" ? (
          pieceFormBlock
        ) : (
          <div className="tv-setp-addrow">
            <button
              type="button"
              className="tv-setp-add"
              onClick={() => setAddingKind("core")}
            >
              <span className="tv-setp-add-disc" aria-hidden="true">+</span>
              Add a core piece
            </button>
          </div>
        )}
      </section>

      <section className="tv-setp-section">
        <header className="tv-setp-head">
          <h3 className="tv-setp-title">Addon pieces &amp; tools</h3>
          <span className="tv-setp-note">Bought later; each carries its own price</span>
          <span className="tv-setp-count">
            {countLabel(
              set.addon_pieces.length + set.attached_tools.length,
              "addon",
            )}
          </span>
        </header>
        {set.addon_pieces.length === 0 && set.attached_tools.length === 0 ? (
          <p className="tv-setp-empty">No addons yet.</p>
        ) : (
          <div className="tv-setp-list" role="table">
            {listHead}
            {set.addon_pieces.map(pieceRow)}
            {set.attached_tools.map(attachedRow)}
          </div>
        )}
        {addingKind === "addon" && pieceFormBlock}
        <div className="tv-setp-addrow">
          {addingKind !== "addon" && (
            <button
              type="button"
              className="tv-setp-add"
              onClick={() => setAddingKind("addon")}
            >
              <span className="tv-setp-add-disc" aria-hidden="true">+</span>
              Add an addon piece
            </button>
          )}
          {!attachOpen && (
            <Button size="sm" variant="secondary" onClick={() => setAttachOpen(true)}>
              Attach an existing tool
            </Button>
          )}
        </div>
        {attachOpen && (
          <div className="tv-setp-attachform">
            <FormField label="Standalone tool to attach">
              <Select value={attachId} onChange={(e) => setAttachId(e.target.value)}>
                <option value="">Pick a tool…</option>
                {(candidates ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {[t.brand, t.model].filter(Boolean).length > 0
                      ? ` — ${[t.brand, t.model].filter(Boolean).join(" ")}`
                      : ""}
                  </option>
                ))}
              </Select>
            </FormField>
            <Button size="sm" onClick={() => void attach()} loading={attachBusy} disabled={!attachId}>
              Attach
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setAttachOpen(false)}>
              Cancel
            </Button>
          </div>
        )}
      </section>

      <section className="tv-setp-section">
        <header className="tv-setp-head">
          <h3 className="tv-setp-title">Set value</h3>
          <span className="tv-setp-note">What the set is worth, as it stands</span>
        </header>
        <div className="tv-setp-stats">
          <div className="tv-setp-stat">
            <div className="tv-stat-label">Set value</div>
            <div className="tv-stat-value">{money(set.price_total)}</div>
          </div>
          <div className="tv-setp-stat">
            <div className="tv-stat-label">Replacement</div>
            <div className="tv-stat-value">{money(set.replacement_total)}</div>
          </div>
          <div className="tv-setp-stat">
            <div className="tv-stat-label">Pieces present</div>
            <div className="tv-stat-value">
              {presentCount} of {allPieces.length}
            </div>
          </div>
        </div>
        <p className="tv-setp-hint">
          The set's own price plus its present addons. Sold or removed
          pieces drop out of the totals but stay in the list for history.
        </p>
      </section>

      <AttachmentViewer
        attachment={viewing?.attachment ?? null}
        emailPath={viewing?.emailPath}
        deleteControl={
          viewing?.attachment.kind === "photo" && viewing.deletePath ? (
            <AttachmentDeleteControl
              attachment={viewing.attachment}
              deletePath={viewing.deletePath}
              onDeleted={() => {
                setViewing(null);
                onChanged();
              }}
            />
          ) : undefined
        }
        onClose={() => setViewing(null)}
      />
    </Panel>
  );
}
