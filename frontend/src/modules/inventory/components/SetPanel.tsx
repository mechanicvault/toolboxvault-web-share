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
import type { SetPiece, Tool } from "../types";
import { PhotoUploader } from "./PhotoUploader";
import { AttachmentDeleteControl } from "./AttachmentList";

const PIECE_STATUSES = ["present", "missing", "sold", "removed"] as const;

/** Plain status wording, shared with the wizard's set page (the
 *  one helper line under the lists explains each — owner clarity
 *  fix, 2026-10-25). */
const STATUS_HELP_STYLE = {
  margin: "0 0 var(--space-3)",
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;

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

/**
 * The set structure on a set's detail page: core pieces, addon
 * pieces (each may carry its own price — a core piece's price is
 * the piece's own figure and never joins the set's totals), and
 * standalone tools attached as addons. Add-piece / add-addon /
 * attach-existing / detach / status changes all live here; totals
 * come from the backend's resolve_set_members so the page never
 * re-derives set math.
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

  const pieceRow = (piece: SetPiece) => (
    <div
      key={piece.id}
      style={{
        border: "1px solid var(--edge)",
        borderRadius: "var(--radius)",
        padding: "0.6rem 0.75rem",
        display: "grid",
        gap: "0.45rem",
        opacity: piece.status === "sold" || piece.status === "removed" ? 0.65 : 1,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "0.75rem",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <p style={{ margin: 0 }}>
          <strong>{piece.name}</strong>{" "}
          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {[piece.part_number && `Part ${piece.part_number}`,
              piece.serial_number && `SN ${piece.serial_number}`]
              .filter(Boolean)
              .join(" · ")}
          </span>{" "}
          {piece.price && (
            <span style={{ fontWeight: 600 }}>{money(piece.price)}</span>
          )}{" "}
          {piece.repair_state && piece.repair_state !== "in_service" && (
            <Badge tone={REPAIR_STATE_TONES[piece.repair_state]} dot>
              {REPAIR_STATE_LABELS[piece.repair_state]}
              {piece.repair_problem ? ` — ${piece.repair_problem}` : ""}
            </Badge>
          )}
        </p>
        <div
          style={{
            display: "flex",
            gap: "0.4rem",
            alignItems: "center",
            flexWrap: "wrap",
            // Phone width: a long piece name used to squeeze this
            // row until the status select clipped shut ("Pres…").
            // The row wraps to its own line instead, and the select
            // keeps a readable minimum width.
            flex: "1 1 15rem",
            justifyContent: "flex-end",
          }}
        >
          <span style={{ flex: "0 1 9rem", minWidth: "8rem" }}>
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
          </span>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setExpandedPiece(expandedPiece === piece.id ? null : piece.id)
            }
          >
            Files ({piece.attachments.length})
          </Button>
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
          <Button size="sm" variant="danger" onClick={() => void removePiece(piece)}>
            Remove
          </Button>
        </div>
      </div>
      {sellingPiece === piece.id && (
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            alignItems: "end",
            flexWrap: "wrap",
          }}
        >
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
          <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            Records the sale on the ledger (the Sold view + this set's
            history) — not just the status flip.
          </span>
        </div>
      )}
      {expandedPiece === piece.id && (
        <div style={{ display: "grid", gap: "0.5rem" }}>
          {piece.attachments.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "1.1rem", display: "grid", gap: "0.3rem" }}>
              {piece.attachments.map((a) => (
                <li key={a.key}>
                  <button
                    type="button"
                    onClick={() =>
                      setViewing({
                        attachment: a,
                        emailPath: `/inventory/pieces/${piece.id}/attachments/email`,
                        deletePath: `/inventory/pieces/${piece.id}/attachments`,
                      })
                    }
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      color: "var(--accent)",
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    {a.filename}
                  </button>{" "}
                  <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    ({a.kind})
                  </span>
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

  return (
    <Panel title="Set contents" variant="accent-edge">
      {error && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {set.core_pieces.length + set.addon_pieces.length > 0 && (
        <p style={STATUS_HELP_STYLE}>{t("wizard.setStatusHelp")}</p>
      )}
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <p style={{ margin: 0, fontWeight: 600 }}>
            Core pieces{" "}
            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              — part of the set from the start
            </span>
          </p>
          {set.core_pieces.length === 0 ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No core pieces yet.
            </p>
          ) : (
            set.core_pieces.map(pieceRow)
          )}
          {addingKind !== "core" && (
            <div>
              <Button size="sm" variant="secondary" onClick={() => setAddingKind("core")}>
                Add a core piece
              </Button>
            </div>
          )}
        </div>

        <div style={{ display: "grid", gap: "0.5rem" }}>
          <p style={{ margin: 0, fontWeight: 600 }}>
            Addon pieces &amp; tools{" "}
            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              — bought later; each carries its own price
            </span>
          </p>
          {set.addon_pieces.length === 0 && set.attached_tools.length === 0 ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No addons yet.
            </p>
          ) : (
            <>
              {set.addon_pieces.map(pieceRow)}
              {set.attached_tools.map((attached) => (
                <div
                  key={attached.id}
                  style={{
                    border: "1px solid var(--edge)",
                    borderRadius: "var(--radius)",
                    padding: "0.6rem 0.75rem",
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "0.75rem",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <p style={{ margin: 0 }}>
                    <Link
                      to={`/inventory/${attached.id}`}
                      style={{ color: "var(--accent)", fontWeight: 600 }}
                    >
                      {attached.name}
                    </Link>{" "}
                    <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                      {[attached.brand, attached.model].filter(Boolean).join(" · ")}
                      {attached.quantity > 1 ? ` · ×${attached.quantity}` : ""}
                    </span>{" "}
                    {attached.purchase_total && (
                      <span style={{ fontWeight: 600 }}>{money(attached.purchase_total)}</span>
                    )}{" "}
                    <Badge tone="neutral">attached tool</Badge>
                  </p>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void detach(attached.id)}
                  >
                    Detach to standalone
                  </Button>
                </div>
              ))}
            </>
          )}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {addingKind !== "addon" && (
              <Button size="sm" variant="secondary" onClick={() => setAddingKind("addon")}>
                Add an addon piece
              </Button>
            )}
            {!attachOpen && (
              <Button size="sm" variant="secondary" onClick={() => setAttachOpen(true)}>
                Attach an existing tool
              </Button>
            )}
          </div>
          {attachOpen && (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "end" }}>
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
        </div>

        {addingKind && (
          <form
            onSubmit={(e) => void addPiece(e)}
            style={{
              border: "1px solid var(--edge)",
              borderRadius: "var(--radius)",
              padding: "0.75rem",
              display: "grid",
              gap: "0.6rem",
            }}
          >
            <p style={{ margin: 0, fontWeight: 600 }}>
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
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>
              A piece's price is its own number — what that piece cost,
              or what it would cost to replace. It doesn't change the
              set's price.
            </p>
            <div style={{ display: "flex", gap: "0.5rem" }}>
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
        )}

        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Set value: <strong style={{ color: "var(--text)" }}>{money(set.price_total)}</strong>
          {" · "}Replacement:{" "}
          <strong style={{ color: "var(--text)" }}>{money(set.replacement_total)}</strong>{" "}
          — the set's own price plus its present addons. Sold or removed
          pieces drop out of the totals but stay in the list for history.
        </p>
      </div>
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
