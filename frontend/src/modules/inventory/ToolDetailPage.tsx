import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  AttachmentViewer,
  Badge,
  Button,
  DetailSkeleton,
  EmptyState,
  FramedImage,
  Modal,
  Panel,
  Tabs,
  type TabItem,
  type ViewableAttachment,
  LinkButton,
} from "../../components";
import { TagChip } from "../../components";
import { api, ApiError } from "../../lib/api";
import { useFixFocus } from "../../lib/fixFocus";
import { usePageCrumbs } from "../../lib/navTrail";
import { LendingPanel } from "../borrowing/components/LendingPanel";
import { ItemClaimsPanel } from "../claims/ItemClaimsPanel";
import { ExpansionSection } from "../tool-expansion/components";
import { BrokenItemActions } from "../claims/BrokenItemActions";
import { RequireAuth } from "../core";
import { useMyModules } from "../core/MyModules";
import { useT } from "../../i18n/LocaleContext";
import { ItemCarePanels } from "../maintenance/components/ItemCarePanels";
import {
  AttachmentDeleteControl,
  AttachmentList,
} from "./components/AttachmentList";
import { DealerAgentLine } from "./components/DealerAgentLine";
import { AddFiles } from "./components/AddFiles";
import { ItemPhoto } from "./components/ItemPhoto";
import { ItemStatusStrip, useItemStatus } from "./components/ItemStatusStrip";
import { ItemStatusPill } from "./components/ItemStatusPill";
import { ItemActionsMenu } from "./components/ItemActionsMenu";
import { ItemLocationColumn } from "./components/ItemLocationColumn";
import {
  WarrantyAgentForProvider,
  WarrantyProviderValue,
} from "./components/WarrantyProvider";
import { LossReportPanel } from "./components/LossReportPanel";
import { LocateManualPanel } from "../catalog/LocateManualPanel";
import { ManualLinkForm } from "../catalog/ManualLinkForm";
import { HistoryPanel } from "./components/HistoryPanel";
import { SalesPanel } from "./components/SalesPanel";
import { StandingBadge } from "./components/StandingBadge";
import { WARRANTY_TONES, WarrantyBadge } from "./components/BatteryCard";
import { SetPanel } from "./components/SetPanel";
import { customValueText, displayDate, money } from "./format";
import { WARRANTY_LABELS, WARRANTY_TYPE_LABELS, type Attachment, type Battery, type FieldDefinition, type Tool } from "./types";
import "./itemPage.css";

function Row({ label, value }: { label: string; value: string }) {
  // F1-26: rows with no data don't render — no "—" padding.
  // W-05: the format helpers (money/displayDate) pre-render a null
  // as the string "—", which is non-empty and slipped past this
  // guard — a "—" value is no data too.
  if (!value || !value.trim() || value.trim() === "—") return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "150px minmax(0, 1fr)",
        gap: "0.5rem",
      }}
    >
      <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
      <dd style={{ margin: 0, minWidth: 0, overflowWrap: "anywhere" }}>
        {value || "—"}
      </dd>
    </div>
  );
}

/** Total for a per-unit money field at the tool's quantity. */
function totalOf(value: string | null, quantity: number): string | null {
  if (value === null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return (n * quantity).toFixed(2);
}

/** Tool detail (owner layout, 2026-10-31): a header zone —
 *  thumbnail (clickable into the photo viewer), the name and the
 *  main facts (quantity, price, purchase date), and the page's
 *  actions — then a live-status strip (only the states this item
 *  is actually in, each linking to its record), then the record
 *  itself in tabs: Details · Borrowing · Photos · Documents &
 *  Receipts · Maintenance · Warranty · Claims · Audit. The
 *  Borrowing, Maintenance and Claims tabs exist only while
 *  their module is effective for the viewer, the panels' own
 *  rule carried up to the tab. (Borrowing is its OWN tab since
 *  2026-11-04 — the owner revoked the 2026-11-01 ruling that
 *  had kept the lending panel inside Details.) */
export default function ToolDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { has } = useMyModules();
  const t = useT();
  const [tool, setTool] = useState<Tool | null>(null);
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [viewing, setViewing] = useState<{
    attachment: ViewableAttachment;
    emailPath: string;
  } | null>(null);
  // The #repairs deep link (older Maintenance rows) opens the
  // Claims / Replace tab — repairs live there since the merge
  // (2026-11-04); the Maintenance tab keeps schedules only.
  // #lending / #borrowing land on the Borrowing tab (the
  // lending panel's home since 2026-11-04).
  const [activeTab, setActiveTab] = useState(() => {
    if (typeof window === "undefined") return "details";
    const hash = window.location.hash;
    if (hash === "#repairs" || hash === "#claims" || hash === "#start-claim") return "claims";
    if (hash === "#lending" || hash === "#borrowing") return "borrowing";
    // #photos: the health check's photo Fix-it link lands on
    // this tab, at its Add photos button (see useFixFocus below).
    if (hash === "#photos") return "photos";
    return "details";
  });
  useFixFocus((hash) => (hash === "photos" ? "item-add-photos" : null));
  // The Borrowing tab drops itself when the lending panel
  // reports its read failed (the module isn't effective for
  // this viewer after all) — the tab vanishes exactly when the
  // panel would have hidden inside Details before the move.
  const [borrowingUnavailable, setBorrowingUnavailable] = useState(false);
  const onBorrowingUnavailable = useCallback(() => {
    setBorrowingUnavailable(true);
    setActiveTab((cur) => (cur === "borrowing" ? "details" : cur));
  }, []);
  // The header Actions menu's Start a claim entry bumps this
  // after switching to the Claims tab; the tab's action panel
  // opens its claim form on the bump (amendment #4).
  const [claimSignal, setClaimSignal] = useState(0);
  // The lost/stolen report and the sale record live in their
  // own modal windows, opened from the Actions menu and the
  // status strip — NOT in the Details tab (owner correction,
  // 2026-10-31). The #loss-report / #sale hashes open the same
  // windows (the #repairs pattern: a landing names its record).
  const [lossOpen, setLossOpen] = useState(false);
  const [saleOpen, setSaleOpen] = useState(false);
  const [saleIntent, setSaleIntent] = useState<"mark" | "details">("details");
  const openSale = useCallback((intent: "mark" | "details") => {
    setSaleIntent(intent);
    setSaleOpen(true);
  }, []);

  useEffect(() => {
    const hash = window.location.hash;
    if (hash === "#loss-report") setLossOpen(true);
    else if (hash === "#sale") setSaleOpen(true);
  }, []);

  // The #start-claim deep link (the inventory row
  // Actions menu's Start a claim, 2026-11-05): the claims
  // panel opens its form on a signal CHANGE from the value
  // it mounted with — and it mounts only once the item has
  // loaded. So the bump waits for the item, once: bump any
  // earlier and the panel's mount snapshot already holds it
  // and the form stays shut.
  const claimHashBumped = useRef(false);
  useEffect(() => {
    if (
      tool &&
      !claimHashBumped.current &&
      window.location.hash === "#start-claim"
    ) {
      claimHashBumped.current = true;
      setClaimSignal((n) => n + 1);
    }
  }, [tool]);
  // Batteries currently sitting in this tool (the link lives on the
  // battery; this is the read-back). Loaded best-effort — a failure
  // here never blocks the tool's own page.
  const [inTool, setInTool] = useState<Battery[] | null>(null);
  const [unlinking, setUnlinking] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!id) return;
    api<Tool>(`/inventory/${id}`)
      .then(setTool)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load this tool."),
      );
  }, [id]);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api<Tool>(`/inventory/${id}`),
      api<FieldDefinition[]>("/inventory/field-definitions?item_type=tool"),
    ])
      .then(([t, d]) => {
        setTool(t);
        setDefs(d);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load this tool."),
      );
    api<Battery[]>(`/inventory/batteries?in_tool=${id}`)
      .then(setInTool)
      .catch(() => setInTool([]));
  }, [id]);

  // The status strip's records (also the Claims tab's empty
  // state). Reloads when the item changes or the tab does.
  const { data: status, reload: reloadStatus } = useItemStatus(
    "tool",
    id ?? "",
    `${activeTab}|${tool?.updated_at ?? ""}`,
  );

  // The link tree lives in the shell bar, right of the back /
  // forward arrows (owner ruling 2026-11-03) — registered here,
  // never rendered in this page's own header.
  usePageCrumbs(
    tool
      ? [{ label: "Inventory", to: "/inventory" }, { label: tool.name }]
      : null,
  );

  /** Panels that change the item's record or its live states:
   *  refetch the item AND the strip's records together. */
  const onItemChanged = useCallback(() => {
    refresh();
    reloadStatus();
  }, [refresh, reloadStatus]);

  async function onUnlink(battery: Battery) {
    setUnlinking(battery.id);
    try {
      await api(`/inventory/batteries/${battery.id}`, {
        method: "PUT",
        body: JSON.stringify({ currently_in_tool_id: null }),
      });
      setInTool((list) => (list ?? []).filter((b) => b.id !== battery.id));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't unlink that battery.",
      );
    } finally {
      setUnlinking(null);
    }
  }

  const [confirmDelete, setConfirmDelete] = useState(false);

  async function onDelete() {
    if (!id || !tool) return;
    setDeleting(true);
    try {
      await api(`/inventory/${id}`, { method: "DELETE" });
      navigate("/inventory", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete this tool.");
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  /** A status-strip jump: open the tab that holds the record,
   *  then scroll to it once the tab has painted. */
  const jump = useCallback((tab: string, anchor?: string) => {
    setActiveTab(tab);
    if (anchor) {
      window.setTimeout(() => {
        document.getElementById(anchor)?.scrollIntoView({ block: "start" });
      }, 120);
    }
  }, []);

  const photos = (tool?.attachments ?? []).filter((a) => a.kind === "photo");
  const documents = (tool?.attachments ?? []).filter((a) => a.kind === "document");
  const receipts = (tool?.attachments ?? []).filter((a) => a.kind === "receipt");
  const manuals = (tool?.attachments ?? []).filter((a) => a.kind === "manual");
  const defById = new Map(defs.map((d) => [d.id, d]));
  const customEntries = Object.entries(tool?.custom_data ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  /* The Details box's right column exists only when it has
   * something to hold (owner layout, 2026-11-04): a category
   * and/or tags. Neither → no column, details full width. */
  const hasDetailsSide =
    !!tool && (!!tool.category?.trim() || tool.tags.length > 0);
  /* Sweep B2-F5: does the Details list itself have any row?
   * Every Row renders null when its value is empty, so a tool
   * with nothing recorded left the panel as a bare headed box.
   * The panel now says so in words, with the way in. */
  const hasDetailRows =
    !!tool &&
    Boolean(
      tool.brand ||
        tool.model_numbers.length > 0 ||
        tool.model ||
        tool.serial_numbers.length > 0 ||
        tool.serial_number ||
        tool.size ||
        tool.upc ||
        (tool.standing && tool.standing !== "in_service") ||
        tool.dealer_company_name ||
        tool.notes,
    );
  const viewAttachment = (attachment: Attachment, emailPath: string) =>
    setViewing({ attachment, emailPath });

  const tabs: TabItem[] = !tool
    ? []
    : [
        {
          id: "details",
          label: "Details",
          content: (
            <div className="tv-item-stack">
              <Panel title="Details">
                {!hasDetailRows && (
                  <p className="tv-item-details-empty">
                    No brand, model or serial recorded yet — Edit adds them.
                  </p>
                )}
                <div className={hasDetailsSide ? "tv-details-split" : undefined}>
                <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
                  <Row label="Brand" value={tool.brand} />
                  <Row
                    label={tool.model_numbers.length > 1 ? "Model numbers" : "Model"}
                    value={tool.model_numbers.join(", ") || tool.model}
                  />
                  <Row
                    label={tool.serial_numbers.length > 1 ? "Serial numbers" : "Serial number"}
                    value={tool.serial_numbers.join(", ") || tool.serial_number}
                  />
                  <Row label="Size" value={tool.size} />
                  {tool.upc ? <Row label="UPC / barcode" value={tool.upc} /> : null}
                  {tool.standing && tool.standing !== "in_service" && (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "150px minmax(0, 1fr)",
                        gap: "0.5rem",
                      }}
                    >
                      <dt style={{ color: "var(--text-muted)" }}>Standing</dt>
                      <dd style={{ margin: 0, minWidth: 0 }}>
                        <StandingBadge standing={tool.standing} />
                      </dd>
                    </div>
                  )}
                  {/* Location is NOT repeated here (owner,
                      2026-11-04): the header's location plate
                      already shows it, tier by tier. */}
                  {tool.dealer_company_name && (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "150px minmax(0, 1fr)",
                        gap: "0.5rem",
                      }}
                    >
                      <dt style={{ color: "var(--text-muted)" }}>
                        {t("inventory.details.dealer")}
                      </dt>
                      <dd style={{ margin: 0, minWidth: 0, overflowWrap: "anywhere" }}>
                        {tool.dealer_company_id ? (
                          <Link
                            to={`/dealers/${tool.dealer_company_id}`}
                            style={{ color: "var(--accent)", fontWeight: 600 }}
                          >
                            {tool.dealer_company_name}
                          </Link>
                        ) : (
                          tool.dealer_company_name
                        )}
                        {/* Owner, 2026-11-04: the agent rides ON
                            this row, indented right of the dealer
                            name — "Dealer Agent: <NAME>", a link
                            into that agent's record; the segment
                            renders only while an agent is on
                            record. */}
                        {tool.dealer_company_id && (
                          <DealerAgentLine
                            companyId={tool.dealer_company_id}
                            layout="inline"
                          />
                        )}
                      </dd>
                    </div>
                  )}
                  <Row label="Notes" value={tool.notes} />
                </dl>
                {hasDetailsSide && (
                  <dl className="tv-details-side">
                    {!!tool.category?.trim() && (
                      <div>
                        <dt>Category</dt>
                        <dd>{tool.category}</dd>
                      </div>
                    )}
                    {tool.tags.length > 0 && (
                      <div>
                        <dt>Tags</dt>
                        <dd className="tv-details-side-tags">
                          {tool.tags.map((tag) => (
                            <TagChip key={tag.id} name={tag.name} color={tag.color} />
                          ))}
                        </dd>
                      </div>
                    )}
                  </dl>
                )}
                </div>
              </Panel>

              {tool.sub_limit_warning && (
                <Alert tone="warning">
                  Business use: Your policy's business-use sub-limit may cap this item — check your policy.
                  The sub-limit in Settings → My Insurance is your own
                  record of the policy — this is a reminder, not a
                  coverage decision.
                </Alert>
              )}

              {tool.consumable &&
                (tool.rebuy_store || tool.rebuy_url || tool.rebuy_sku || tool.rebuy_notes) && (
                  <Panel title="Re-buy">
                    <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
                      {tool.rebuy_store && <Row label="Store" value={tool.rebuy_store} />}
                      {tool.rebuy_sku && <Row label="Store SKU / part #" value={tool.rebuy_sku} />}
                      {tool.rebuy_url && (
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "150px minmax(0, 1fr)",
                            gap: "0.5rem",
                          }}
                        >
                          <dt style={{ color: "var(--text-muted)" }}>Website</dt>
                          <dd style={{ margin: 0, minWidth: 0, overflowWrap: "anywhere" }}>
                            <a
                              href={
                                /^https?:\/\//i.test(tool.rebuy_url)
                                  ? tool.rebuy_url
                                  : `https://${tool.rebuy_url}`
                              }
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: "var(--accent)", fontWeight: 600 }}
                            >
                              {tool.rebuy_url}
                            </a>
                          </dd>
                        </div>
                      )}
                      {tool.rebuy_notes && <Row label="Notes" value={tool.rebuy_notes} />}
                    </dl>
                  </Panel>
                )}

              <Panel title="Costs" variant="accent-edge">
                <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
                  <Row label="Quantity" value={String(tool.quantity)} />
                  <Row
                    label="Purchase price (each)"
                    value={
                      tool.quantity > 1 && tool.purchase_price
                        ? `${money(tool.purchase_price)} × ${tool.quantity} = ${money(totalOf(tool.purchase_price, tool.quantity))}`
                        : money(tool.purchase_price)
                    }
                  />
                  <Row label="Purchase date" value={displayDate(tool.purchase_date)} />
                  <Row
                    label="Replacement cost (each)"
                    value={
                      tool.quantity > 1 && tool.replacement_cost
                        ? `${money(tool.replacement_cost)} × ${tool.quantity} = ${money(totalOf(tool.replacement_cost, tool.quantity))}`
                        : money(tool.replacement_cost)
                    }
                  />
                  <Row
                    label="MSRP (each)"
                    value={
                      tool.quantity > 1 && tool.msrp
                        ? `${money(tool.msrp)} × ${tool.quantity} = ${money(totalOf(tool.msrp, tool.quantity))}`
                        : money(tool.msrp)
                    }
                  />
                </dl>
                <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 0 }}>
                  Prices are per item; totals multiply by the quantity.
                  Replacement cost and MSRP are what your insurance values are based on.
                </p>
              </Panel>

              {tool.is_set && <SetPanel tool={tool} onChanged={onItemChanged} />}

              <ExpansionSection kind="tool" id={tool.id} />

              {inTool !== null && inTool.length > 0 && (
                <Panel title={`Batteries in this tool (${inTool.length})`}>
                  <div style={{ display: "grid", gap: "0.6rem" }}>
                    {inTool.map((battery) => (
                      <div
                        key={battery.id}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "1rem",
                          flexWrap: "wrap",
                        }}
                      >
                        <p style={{ margin: 0, display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
                          <Link
                            to={`/inventory/batteries/${battery.id}`}
                            style={{ color: "var(--accent)", fontWeight: 600 }}
                          >
                            {battery.name}
                          </Link>
                          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                            {[battery.brand, battery.model]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                          <WarrantyBadge battery={battery} />
                        </p>
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={unlinking === battery.id}
                          onClick={() => void onUnlink(battery)}
                        >
                          Unlink
                        </Button>
                      </div>
                    ))}
                  </div>
                  <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 0 }}>
                    The link lives on the battery — unlinking moves nothing
                    else, and deleting this tool never deletes a battery.
                  </p>
                </Panel>
              )}

              {customEntries.length > 0 && (
                <Panel title="Custom fields">
                  <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
                    {customEntries.map(([key, value]) => {
                      const def = defById.get(key);
                      return (
                        <Row
                          key={key}
                          label={def?.label ?? key}
                          value={customValueText(value, def?.field_type ?? "text")}
                        />
                      );
                    })}
                  </dl>
                </Panel>
              )}
            </div>
          ),
        },
        ...(has("borrowing") && !borrowingUnavailable
          ? [
              {
                id: "borrowing",
                label: t("nav.borrowing"),
                content: (
                  <div className="tv-item-stack">
                    {/* The lending panel's own tab (owner,
                        2026-11-04 — revokes the 2026-11-01
                        lending-in-Details exception). The
                        #lending anchor rides along: the status
                        strip and the Actions menu jump here. */}
                    <div id="lending" className="tv-item-anchor">
                      <LendingPanel
                        itemKind="tool"
                        itemId={tool.id}
                        itemName={tool.name}
                        itemActive={tool.active}
                        isSet={tool.is_set}
                        onChanged={reloadStatus}
                        onUnavailable={onBorrowingUnavailable}
                      />
                    </div>
                  </div>
                ),
              } as TabItem,
            ]
          : []),
        {
          id: "photos",
          label: "Photos",
          content: (
            <div className="tv-item-stack">
              <Panel title={`Photos (${photos.length})`}>
                {/* Owner ruling 2026-11-03: the Photos area has
                 * its own Add button — no trip into Edit to add
                 * a file. Owner correction 2026-11-04 22:19: NO
                 * delete control on this tab at all — every photo
                 * renders the same size in one uniform grid
                 * (about half the old full-width lead render),
                 * and a photo is deleted only from inside the
                 * photo viewer (see the AttachmentViewer below). */}
                <AddFiles
                  basePath={`/inventory/${tool.id}`}
                  kind="photo"
                  addLabel="Add photos"
                  onUploaded={refresh}
                  buttonId="item-add-photos"
                />
                {photos.length > 0 ? (
                  <AttachmentList
                    items={photos}
                    layout="photos"
                    emailPath={`/inventory/${tool.id}/attachments/email`}
                    onView={viewAttachment}
                  />
                ) : (
                  <p className="tv-item-tabnote">
                    No photos yet — add the first one with Add photos.
                  </p>
                )}
              </Panel>
            </div>
          ),
        },
        {
          id: "documents",
          label: "Documents & Receipts",
          content: (
            <div className="tv-item-stack">
              {/* Owner batch 2026-11-03: each file area stands on
               * its own — Documents, Receipts, and the new
               * Manuals area — each with its own Add button that
               * files straight into that area. Owner, 2026-11-04
               * 22:27: each area renders as an icon grid — a
               * document-type icon with the file's name below
               * it (AttachmentList layout="tiles"). */}
              <Panel title={`Documents (${documents.length})`}>
                <AddFiles
                  basePath={`/inventory/${tool.id}`}
                  kind="document"
                  addLabel="Add a document"
                  onUploaded={refresh}
                />
                {documents.length > 0 ? (
                  <AttachmentList
                    items={documents}
                    layout="tiles"
                    emailPath={`/inventory/${tool.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/${tool.id}/attachments`}
                    onDeleted={refresh}
                  />
                ) : (
                  <p className="tv-item-tabnote">No documents yet.</p>
                )}
              </Panel>

              <Panel title={`Receipts (${receipts.length})`}>
                <AddFiles
                  basePath={`/inventory/${tool.id}`}
                  kind="receipt"
                  addLabel="Add a receipt"
                  onUploaded={refresh}
                />
                {receipts.length > 0 ? (
                  <AttachmentList
                    items={receipts}
                    layout="tiles"
                    emailPath={`/inventory/${tool.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/${tool.id}/attachments`}
                    onDeleted={refresh}
                  />
                ) : (
                  <p className="tv-item-tabnote">No receipts yet.</p>
                )}
              </Panel>

              <Panel title={`Manuals (${manuals.length})`}>
                <AddFiles
                  basePath={`/inventory/${tool.id}`}
                  kind="manual"
                  addLabel="Add a manual"
                  onUploaded={refresh}
                >
                  <ManualLinkForm
                    segment="tools"
                    itemId={tool.id}
                    itemName={tool.name}
                    onSaved={refresh}
                  />
                </AddFiles>
                {manuals.length > 0 ? (
                  <AttachmentList
                    items={manuals}
                    layout="tiles"
                    emailPath={`/inventory/${tool.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/${tool.id}/attachments`}
                    onDeleted={refresh}
                  />
                ) : (
                  <p className="tv-item-tabnote">No manuals yet.</p>
                )}
              </Panel>

              <LocateManualPanel
                segment="tools"
                itemId={tool.id}
                itemName={tool.name}
                brand={tool.brand}
                model={tool.model}
                onSaved={refresh}
              />
            </div>
          ),
        },
        ...(has("maintenance")
          ? [
              {
                id: "maintenance",
                label: "Maintenance",
                content: (
                  <div className="tv-item-stack">
                    <ItemCarePanels itemKind="tool" itemId={tool.id} />
                  </div>
                ),
              } as TabItem,
            ]
          : []),
        {
          id: "warranty",
          label: "Warranty",
          content: (
            <div className="tv-item-stack">
              <Panel title="Warranty">
                <div style={{ display: "grid", gap: "0.6rem" }}>
                  <p style={{ margin: 0, display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
                    <Badge tone={WARRANTY_TONES[tool.warranty_status]} dot>
                      {WARRANTY_LABELS[tool.warranty_status]}
                    </Badge>
                  </p>
                  <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
                    {/* Owner amendment (2026-10-31): the warranty
                        TYPE is the top row, ahead of term, ends,
                        provider and the rest. */}
                    {tool.warranty_type && (
                      <Row
                        label="Warranty type"
                        value={WARRANTY_TYPE_LABELS[tool.warranty_type] ?? tool.warranty_type}
                      />
                    )}
                    <Row
                      label="Warranty term"
                      value={
                        tool.warranty_months === null || tool.warranty_months === undefined
                          ? "Not recorded"
                          : `${tool.warranty_months} months`
                      }
                    />
                    <Row
                      label="Warranty ends"
                      value={
                        tool.warranty_type === "lifetime"
                          ? "Lifetime — no end date"
                          : displayDate(tool.warranty_end_date)
                      }
                    />
                    {tool.warranty_provider && (
                      <div className="tv-item-row">
                        <dt>Provider</dt>
                        <dd>
                          <WarrantyProviderValue
                            provider={tool.warranty_provider}
                            dealerCompanyId={tool.dealer_company_id}
                            dealerCompanyName={tool.dealer_company_name}
                          />
                        </dd>
                      </div>
                    )}
                    {/* Owner ruling 2026-11-03: the owner's
                        current agent for that provider, when the
                        provider genuinely matches a dealer record
                        and an agent is on record — otherwise this
                        renders nothing at all. */}
                    {tool.warranty_provider && (
                      <WarrantyAgentForProvider
                        provider={tool.warranty_provider}
                        dealerCompanyId={tool.dealer_company_id}
                        dealerCompanyName={tool.dealer_company_name}
                        rowClassName="tv-item-row"
                      />
                    )}
                    {tool.warranty_contact && (
                      <Row label="Contact" value={tool.warranty_contact} />
                    )}
                    {tool.warranty_terms && (
                      <Row label="Terms" value={tool.warranty_terms} />
                    )}
                  </dl>
                  <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: 0 }}>
                    Worked out from the purchase date and warranty term — the same
                    computation batteries use. This item's claims are listed
                    under the Claims / Replace tab.
                  </p>
                </div>
              </Panel>
            </div>
          ),
        },
        ...(has("claims")
          ? [
              {
                id: "claims",
                label: "Claims / Replace",
                content: (
                  <div className="tv-item-stack">
                    {/* Exactly ONE action panel (merge, 2026-11-04):
                        the broken prompt when the item is broken,
                        the Start a claim / Replace item panel when
                        it isn't — BrokenItemActions renders the
                        right one for the item's standing. */}
                    <BrokenItemActions
                      itemKind="tool"
                      itemId={tool.id}
                      openSignal={claimSignal}
                    />

                    <ItemClaimsPanel itemKind="tool" itemId={tool.id} />

                    {status.claims !== null &&
                      status.claims.current.length === 0 &&
                      status.claims.history.length === 0 &&
                      tool.standing !== "broken" && (
                        <p className="tv-item-tabnote">
                          No claims on this item yet.
                        </p>
                      )}
                  </div>
                ),
              } as TabItem,
            ]
          : []),
        {
          id: "audit",
          label: "Audit",
          content: (
            <div className="tv-item-stack">
              <HistoryPanel itemKind="tool" item={tool} />
            </div>
          ),
        },
      ];

  return (
    <RequireAuth>
      {error && (
        <div style={{ marginBottom: "var(--spacing)" }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {!tool && !error ? (
        <DetailSkeleton />
      ) : !tool ? (
        <EmptyState
          title="Tool not found"
          action={
            <LinkButton to="/inventory">Back to inventory</LinkButton>
          }
        />
      ) : (
        <div style={{ display: "grid", gap: "var(--spacing)" }}>
          {tool.active === false && (
            <Alert tone="warning">
              This tool is <strong>inactive</strong> — it's over your
              plan's item limit, so it's hidden from sharing and stats.
              It stays safe in your vault; upgrading your plan
              (Settings → Plan &amp; billing) reactivates it.
            </Alert>
          )}
          {tool.attached_to_set && (
            <Alert tone="info">
              This tool is an <strong>addon of the set “{tool.attached_to_set.name}”</strong> —
              it doesn't appear in the inventory list on its own.{" "}
              <Link
                to={`/inventory/${tool.attached_to_set.id}`}
                style={{ color: "var(--accent)", fontWeight: 600 }}
              >
                Open the set
              </Link>{" "}
              to detach it back to standalone.
            </Alert>
          )}
          <div
            style={{
              display: "flex",
              gap: "1rem",
              alignItems: "flex-start",
              justifyContent: "space-between",
              flexWrap: "wrap",
            }}
          >
            <div className="tv-item-thumb">
              {photos.length > 0 ? (
                <button
                  type="button"
                  className="tv-item-thumb-btn"
                  onClick={() => viewAttachment(photos[0], `/inventory/${tool.id}/attachments/email`)}
                  title="View the photo larger"
                >
                  <FramedImage
                    src={photos[0].thumb_url || photos[0].url}
                    alt={tool.name}
                    aspectRatio="16 / 9"
                    fit="contain"
                  />
                </button>
              ) : (
                <ItemPhoto photo={undefined} name={tool.name} brand={tool.brand} variant="tile" />
              )}
            </div>
            <div className="tv-item-head-main">
              <h1 style={{ margin: 0, fontSize: "1.6rem" }}>
                {tool.name}
                {tool.is_set && (
                  <>
                    {" "}
                    <Badge tone="accent">Set</Badge>
                  </>
                )}
                {tool.consumable && (
                  <>
                    {" "}
                    <Badge tone="neutral">Consumable</Badge>
                  </>
                )}
                {tool.business_use && (
                  <>
                    {" "}
                    <Badge tone="accent">Business use</Badge>
                  </>
                )}
                {tool.replaced_on && (
                  <>
                    {" "}
                    <Badge tone="neutral">
                      Replaced {displayDate(tool.replaced_on)}
                    </Badge>
                  </>
                )}
              </h1>
              <dl className="tv-item-facts">
                <div className="tv-item-fact">
                  <dt>Quantity</dt>
                  <dd>{tool.quantity}</dd>
                </div>
                {tool.purchase_price !== null && tool.purchase_price !== undefined && (
                  <div className="tv-item-fact">
                    <dt>Price</dt>
                    <dd>
                      {money(tool.purchase_price)}
                      {tool.quantity > 1 ? " each" : ""}
                    </dd>
                  </div>
                )}
                {tool.purchase_date && (
                  <div className="tv-item-fact">
                    <dt>Purchase date</dt>
                    <dd>{displayDate(tool.purchase_date)}</dd>
                  </div>
                )}
                {/* The header status pill (owner ruling
                    2026-11-03): immediately right of the purchase
                    date in the facts row. */}
                <ItemStatusPill
                  standing={tool.standing}
                  data={status}
                  itemKind="tool"
                  itemId={tool.id}
                />
              </dl>
            </div>
            <div className="tv-item-side">
              {/* Sweep B2-F2 (superseding the 2026-11-03 inline
                  seat): the Actions dropdown is pinned to the
                  header's TOP-RIGHT corner — the corner a user
                  scans first, matching the Inventory list header —
                  instead of floating mid-page in the facts row
                  with the header's right half empty. The location
                  plate stays in this column, below Actions. The
                  menu itself is untouched: it still anchors to
                  this button (do-not-lose). */}
              <ItemActionsMenu
                itemKind="tool"
                item={tool}
                status={status}
                hasModule={has}
                onJump={jump}
                onChanged={onItemChanged}
                onDelete={() => setConfirmDelete(true)}
                onStartClaim={() => {
                  setActiveTab("claims");
                  setClaimSignal((n) => n + 1);
                }}
                onOpenLoss={() => setLossOpen(true)}
                onOpenSale={openSale}
              />
              <ItemLocationColumn location={tool.location} />
            </div>
          </div>

          <ItemStatusStrip
            standing={tool.standing}
            replacedOn={tool.replaced_on}
            replacedByName={tool.replaced_by_name}
            data={status}
            claimsEffective={has("claims")}
            maintenanceEffective={has("maintenance")}
            onJump={jump}
            onOpenLoss={() => setLossOpen(true)}
            onOpenSale={() => openSale("details")}
          />

          <Tabs tabs={tabs} activeId={activeTab} onChange={setActiveTab} />

          <Modal
            open={confirmDelete}
            onClose={() => setConfirmDelete(false)}
            title={`Delete "${tool.name}"?`}
            size="sm"
            footer={
              <>
                <Button type="button" variant="secondary" onClick={() => setConfirmDelete(false)}>
                  Keep it
                </Button>
                <Button type="button" variant="danger" onClick={() => void onDelete()} disabled={deleting}>
                  {deleting ? "Deleting…" : "Delete tool"}
                </Button>
              </>
            }
          >
            <p style={{ margin: 0 }}>
              This can't be undone.
              {tool.is_set
                ? " Its pieces and their files are deleted too; attached tools are NOT deleted — they go back to standalone."
                : ""}
            </p>
          </Modal>

          <Modal
            open={lossOpen}
            onClose={() => setLossOpen(false)}
            title="Lost / stolen report"
            size="lg"
          >
            <LossReportPanel
              bare
              itemKind="tool"
              itemId={tool.id}
              onChanged={onItemChanged}
            />
          </Modal>

          <Modal
            open={saleOpen}
            onClose={() => setSaleOpen(false)}
            title="Sale"
            size="lg"
          >
            <SalesPanel
              bare
              itemKind="tool"
              itemId={tool.id}
              itemName={tool.name}
              quantity={tool.quantity}
              standing={tool.standing}
              isAttachedAddon={tool.attached_to_set_id !== null}
              startWithForm={saleIntent === "mark"}
              onChanged={onItemChanged}
            />
          </Modal>

          <AttachmentViewer
            attachment={viewing?.attachment ?? null}
            emailPath={viewing?.emailPath}
            deleteControl={
              viewing?.attachment.kind === "photo" ? (
                <AttachmentDeleteControl
                  attachment={viewing.attachment}
                  deletePath={`/inventory/${tool.id}/attachments`}
                  onDeleted={() => {
                    setViewing(null);
                    refresh();
                  }}
                />
              ) : undefined
            }
            onClose={() => setViewing(null)}
          />
        </div>
      )}
    </RequireAuth>
  );
}
