import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  AttachmentViewer,
  Badge,
  Button,
  FramedImage,
  Modal,
  Panel,
  Spinner,
  Tabs,
  type TabItem,
  type ViewableAttachment,
} from "../../components";
import { TagChip } from "../../components";
import { api, ApiError } from "../../lib/api";
import { useFixFocus } from "../../lib/fixFocus";
import { usePageCrumbs } from "../../lib/navTrail";
import { LendingPanel } from "../borrowing/components/LendingPanel";
import { ItemClaimsPanel } from "../claims/ItemClaimsPanel";
import { ExpansionSection } from "../tool-expansion/components";
import { BrokenItemActions } from "../claims/BrokenItemActions";
import { useMyModules } from "../core/MyModules";
import { useT } from "../../i18n/LocaleContext";
import { ItemCarePanels } from "../maintenance/components/ItemCarePanels";
import { AttachmentDeleteControl, AttachmentList } from "./components/AttachmentList";
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
import { batterySpecChips, WarrantyBadge } from "./components/BatteryCard";
import { StandingBadge } from "./components/StandingBadge";
import { customValueText, displayDate, money } from "./format";
import { WARRANTY_TYPE_LABELS } from "./types";
import type { Attachment, Battery, FieldDefinition } from "./types";
import "./itemPage.css";

/**
 * Battery detail — the tool detail page's layout (owner spec,
 * 2026-10-31): header zone (thumbnail, name, main facts, actions),
 * the live-status strip, then tabs — Details · Borrowing ·
 * Photos · Documents & Receipts · Maintenance · Warranty ·
 * Claims · Audit. Plus the battery story: spec chips, the
 * computed warranty standing with its end date (the Warranty
 * tab), and the "currently in" link to the tool it's sitting in
 * (the link lives here, on the battery). The Borrowing,
 * Maintenance and Claims tabs exist only while their module is
 * effective for the viewer. (Borrowing is its OWN tab since
 * 2026-11-04 — the owner revoked the 2026-11-01 ruling that had
 * kept the lending panel inside Details.)
 */
export default function BatteryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { has } = useMyModules();
  const t = useT();
  const [battery, setBattery] = useState<Battery | null>(null);
  const [definitions, setDefinitions] = useState<FieldDefinition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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

  useEffect(() => {
    let live = true;
    Promise.all([
      api<Battery>(`/inventory/batteries/${id}`),
      api<FieldDefinition[]>("/inventory/field-definitions?item_type=battery"),
    ])
      .then(([data, defs]) => {
        if (!live) return;
        setBattery(data);
        setDefinitions(defs);
      })
      .catch((err) => {
        if (live) {
          setError(
            err instanceof ApiError ? err.message : "Couldn't load the battery.",
          );
        }
      });
    return () => {
      live = false;
    };
  }, [id]);

  function refreshBattery() {
    if (!id) return;
    api<Battery>(`/inventory/batteries/${id}`)
      .then(setBattery)
      .catch(() => undefined);
  }

  async function onDelete() {
    if (!id) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api(`/inventory/batteries/${id}`, { method: "DELETE" });
      navigate("/inventory", { replace: true });
    } catch (err) {
      setDeleteError(
        err instanceof ApiError ? err.message : "Couldn't delete the battery.",
      );
      setDeleting(false);
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

  const [viewing, setViewing] = useState<{
    attachment: ViewableAttachment;
    emailPath: string;
  } | null>(null);
  const photos = (battery?.attachments ?? []).filter((a) => a.kind === "photo");
  const documents = (battery?.attachments ?? []).filter((a) => a.kind === "document");
  const receipts = (battery?.attachments ?? []).filter((a) => a.kind === "receipt");
  const manuals = (battery?.attachments ?? []).filter((a) => a.kind === "manual");
  const viewAttachment = (attachment: Attachment, emailPath: string) =>
    setViewing({ attachment, emailPath });
  const customRows = definitions
    .map((def) => ({ def, value: battery?.custom_data?.[def.id] }))
    .filter(({ value }) => value !== undefined && value !== null && value !== "");

  // The status strip's records (also the Claims tab's empty
  // state). Reloads when the battery changes or the tab does.
  const { data: status, reload: reloadStatus } = useItemStatus(
    "battery",
    id ?? "",
    `${activeTab}|${battery?.updated_at ?? ""}`,
  );

  // The link tree lives in the shell bar, right of the back /
  // forward arrows (owner ruling 2026-11-03) — registered here,
  // never rendered in this page's own header.
  usePageCrumbs([
    { label: "Inventory", to: "/inventory" },
    { label: battery?.name ?? "Battery" },
  ]);

  /** Panels that change the item's record or its live states:
   *  refetch the battery AND the strip's records together. */
  function onItemChanged() {
    refreshBattery();
    reloadStatus();
  }

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
      battery &&
      !claimHashBumped.current &&
      window.location.hash === "#start-claim"
    ) {
      claimHashBumped.current = true;
      setClaimSignal((n) => n + 1);
    }
  }, [battery]);

  /* The Warranty tab's rows (owner amendment, 2026-10-31): the
   * warranty TYPE is the top row, ahead of term, ends, provider
   * and the rest. The provider cell is flagged — it renders
   * through WarrantyProviderValue (a dealer link on a real
   * record match, plain text otherwise). */
  const warrantyCells: { label: string; value: string; provider?: boolean }[] =
    !battery
      ? []
      : (
          [
            ...(battery.warranty_type
              ? [
                  {
                    label: "Warranty type",
                    value:
                      WARRANTY_TYPE_LABELS[battery.warranty_type] ??
                      battery.warranty_type,
                  },
                ]
              : []),
            {
              label: "Warranty",
              value:
                battery.warranty_months !== null
                  ? `${battery.warranty_months} months`
                  : "—",
            },
            {
              label: "Warranty ends",
              value:
                battery.warranty_type === "lifetime"
                  ? "Lifetime — no end date"
                  : battery.warranty_end_date
                    ? displayDate(battery.warranty_end_date)
                    : "—",
            },
            ...(battery.warranty_provider
              ? [
                  {
                    label: "Warranty provider",
                    value: battery.warranty_provider,
                    provider: true,
                  },
                ]
              : []),
            ...(battery.warranty_contact
              ? [{ label: "Warranty contact", value: battery.warranty_contact }]
              : []),
            ...(battery.warranty_terms
              ? [{ label: "Warranty terms", value: battery.warranty_terms }]
              : []),
          ] as { label: string; value: string; provider?: boolean }[]
        ).filter(({ value }) => value !== "—");

  const tabs: TabItem[] = !battery
    ? []
    : [
        {
          id: "details",
          label: "Details",
          content: (
            <div className="tv-item-stack">
              {battery.sub_limit_warning && (
                <Alert tone="warning">
                  Business use: your policy's business-use sub-limit may
                  cap this item — check your policy. The sub-limit in
                  Settings → My Insurance is your own record of the
                  policy — this is a reminder, not a coverage decision.
                </Alert>
              )}

              <Panel title="Details">
                {/* Two-sided Details (owner, 2026-11-04): the
                    detail cells on the left, Category in its own
                    right column. Location is NOT repeated here —
                    the header's location plate already shows it.
                    Neither category nor location stays in the
                    cell grid. */}
                <div className={battery.category ? "tv-details-split" : undefined}>
                <div>
                <dl
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                    gap: "1rem 1.5rem",
                    margin: 0,
                  }}
                >
                  {[
                    ["Brand", battery.brand || "—"],
                    ["Model", battery.model || "—"],
                    ["Serial number", battery.serial_number || "—"],
                    ["UPC / barcode", battery.upc || "—"],
                    ["Platform", battery.platform || "—"],
                    [
                      "Voltage",
                      battery.voltage ? `${Number(battery.voltage)} V` : "—",
                    ],
                    [
                      "Capacity",
                      battery.capacity_ah
                        ? `${Number(battery.capacity_ah)} Ah`
                        : "—",
                    ],
                    ["Chemistry", battery.chemistry || "—"],
                    ["Quantity", String(battery.quantity ?? 1)],
                    [
                      "Purchase price (each)",
                      battery.quantity > 1 && battery.purchase_price
                        ? `${money(battery.purchase_price)} × ${battery.quantity} = ${money(String(Number(battery.purchase_price) * battery.quantity))}`
                        : money(battery.purchase_price),
                    ],
                    ["Purchase date", displayDate(battery.purchase_date)],
                    ["Replacement cost", money(battery.replacement_cost)],
                    ["Current market price", money(battery.msrp)],
                  ]
                    // W-05: fields with no data render no cell at all
                    // (the F1-26 standard) — never an isolated "—".
                    .filter(([, value]) => value !== "—")
                    .map(([label, value]) => (
                    <div key={label}>
                      <dt style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                        {label}
                      </dt>
                      <dd
                        style={{
                          margin: "0.15rem 0 0",
                          fontWeight: 600,
                          minWidth: 0,
                          overflowWrap: "anywhere",
                        }}
                      >
                        {value}
                      </dd>
                    </div>
                  ))}
                  {battery.standing && battery.standing !== "in_service" && (
                    <div>
                      <dt style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                        Standing
                      </dt>
                      <dd style={{ margin: "0.15rem 0 0" }}>
                        <StandingBadge standing={battery.standing} />
                      </dd>
                    </div>
                  )}
                  {battery.dealer_company_name && (
                    <div>
                      <dt style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                        {t("inventory.details.dealer")}
                      </dt>
                      <dd style={{ margin: "0.15rem 0 0", fontWeight: 600 }}>
                        {battery.dealer_company_id ? (
                          <Link
                            to={`/dealers/${battery.dealer_company_id}`}
                            style={{ color: "var(--accent)" }}
                          >
                            {battery.dealer_company_name}
                          </Link>
                        ) : (
                          battery.dealer_company_name
                        )}
                      </dd>
                      {/* Owner, 2026-11-04: the agent rides IN
                          this cell, indented under the dealer
                          name — "Dealer Agent: <NAME>", a link
                          into that agent's record; the segment
                          renders only while an agent is on
                          record. */}
                      {battery.dealer_company_id && (
                        <DealerAgentLine
                          companyId={battery.dealer_company_id}
                          layout="subline"
                        />
                      )}
                    </div>
                  )}
                  <div>
                    <dt style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                      Currently in
                    </dt>
                    <dd style={{ margin: "0.15rem 0 0", fontWeight: 600 }}>
                      {battery.currently_in_tool_id ? (
                        <Link to={`/inventory/${battery.currently_in_tool_id}`}>
                          {battery.currently_in_tool_name ?? "Tool"}
                        </Link>
                      ) : (
                        "Not in a tool"
                      )}
                    </dd>
                  </div>
                  {customRows.map(({ def, value }) => (
                    <div key={def.id}>
                      <dt style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                        {def.label}
                      </dt>
                      <dd style={{ margin: "0.15rem 0 0", fontWeight: 600 }}>
                        {customValueText(value, def.field_type)}
                      </dd>
                    </div>
                  ))}
                </dl>
                {battery.notes && (
                  <div style={{ marginTop: "1rem" }}>
                    <p
                      style={{
                        color: "var(--text-muted)",
                        fontSize: "0.85rem",
                        margin: "0 0 0.25rem",
                      }}
                    >
                      Notes
                    </p>
                    <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                      {battery.notes}
                    </p>
                  </div>
                )}
                </div>
                {!!battery.category && (
                  <dl className="tv-details-side">
                    <div>
                      <dt>Category</dt>
                      <dd>{battery.category}</dd>
                    </div>
                  </dl>
                )}
                </div>
              </Panel>

              <ExpansionSection kind="battery" id={battery.id} />

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
                        itemKind="battery"
                        itemId={battery.id}
                        itemName={battery.name}
                        itemActive={battery.active}
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
              <Panel title="Photos">
                {/* Owner ruling 2026-11-03: the Photos area has
                 * its own Add button — no trip into Edit to add
                 * a file. Owner correction 2026-11-04 22:19: NO
                 * delete control on this tab — uniform grid,
                 * deletes only from inside the photo viewer. */}
                <AddFiles
                  basePath={`/inventory/batteries/${battery.id}`}
                  kind="photo"
                  addLabel="Add photos"
                  onUploaded={refreshBattery}
                  buttonId="item-add-photos"
                />
                {photos.length > 0 ? (
                  <AttachmentList
                    items={photos}
                    layout="photos"
                    emailPath={`/inventory/batteries/${battery.id}/attachments/email`}
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
                  basePath={`/inventory/batteries/${battery.id}`}
                  kind="document"
                  addLabel="Add a document"
                  onUploaded={refreshBattery}
                />
                {documents.length > 0 ? (
                  <AttachmentList
                    items={documents}
                    layout="tiles"
                    emailPath={`/inventory/batteries/${battery.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/batteries/${battery.id}/attachments`}
                    onDeleted={refreshBattery}
                  />
                ) : (
                  <p className="tv-item-tabnote">No documents yet.</p>
                )}
              </Panel>

              <Panel title={`Receipts (${receipts.length})`}>
                <AddFiles
                  basePath={`/inventory/batteries/${battery.id}`}
                  kind="receipt"
                  addLabel="Add a receipt"
                  onUploaded={refreshBattery}
                />
                {receipts.length > 0 ? (
                  <AttachmentList
                    items={receipts}
                    layout="tiles"
                    emailPath={`/inventory/batteries/${battery.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/batteries/${battery.id}/attachments`}
                    onDeleted={refreshBattery}
                  />
                ) : (
                  <p className="tv-item-tabnote">No receipts yet.</p>
                )}
              </Panel>

              <Panel title={`Manuals (${manuals.length})`}>
                <AddFiles
                  basePath={`/inventory/batteries/${battery.id}`}
                  kind="manual"
                  addLabel="Add a manual"
                  onUploaded={refreshBattery}
                >
                  <ManualLinkForm
                    segment="batteries"
                    itemId={battery.id}
                    itemName={battery.name}
                    onSaved={refreshBattery}
                  />
                </AddFiles>
                {manuals.length > 0 ? (
                  <AttachmentList
                    items={manuals}
                    layout="tiles"
                    emailPath={`/inventory/batteries/${battery.id}/attachments/email`}
                    onView={viewAttachment}
                    deletePath={`/inventory/batteries/${battery.id}/attachments`}
                    onDeleted={refreshBattery}
                  />
                ) : (
                  <p className="tv-item-tabnote">No manuals yet.</p>
                )}
              </Panel>

              <LocateManualPanel
                segment="batteries"
                itemId={battery.id}
                itemName={battery.name}
                brand={battery.brand}
                model={battery.model}
                onSaved={refreshBattery}
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
                    <ItemCarePanels itemKind="battery" itemId={battery.id} />
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
                <div className="tv-item-warranty-body">
                  <p className="tv-item-nomargin">
                    <WarrantyBadge battery={battery} />
                  </p>
                  {warrantyCells.length > 0 ? (
                    <dl className="tv-item-cells">
                      {warrantyCells.map(({ label, value, provider }) => (
                        <div key={label} className="tv-item-cell">
                          <dt>{label}</dt>
                          <dd>
                            {provider ? (
                              <WarrantyProviderValue
                                provider={value}
                                dealerCompanyId={battery.dealer_company_id}
                                dealerCompanyName={battery.dealer_company_name}
                              />
                            ) : (
                              value
                            )}
                          </dd>
                        </div>
                      ))}
                      {/* Owner ruling 2026-11-03: the owner's
                          current agent for that provider, on a
                          genuine dealer-record match with an
                          agent on record — otherwise nothing. */}
                      {battery.warranty_provider && (
                        <WarrantyAgentForProvider
                          provider={battery.warranty_provider}
                          dealerCompanyId={battery.dealer_company_id}
                          dealerCompanyName={battery.dealer_company_name}
                          rowClassName="tv-item-cell"
                        />
                      )}
                    </dl>
                  ) : (
                    <p className="tv-item-tabnote">
                      No warranty details recorded for this battery.
                    </p>
                  )}
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
                      itemKind="battery"
                      itemId={battery.id}
                      openSignal={claimSignal}
                    />

                    <ItemClaimsPanel itemKind="battery" itemId={battery.id} />

                    {status.claims !== null &&
                      status.claims.current.length === 0 &&
                      status.claims.history.length === 0 &&
                      battery.standing !== "broken" && (
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
              <HistoryPanel itemKind="battery" item={battery} />
            </div>
          ),
        },
      ];

  return (
    <div style={{ display: "grid", gap: "var(--spacing)" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        {battery && (
          <div className="tv-item-thumb">
            {photos.length > 0 ? (
              <button
                type="button"
                className="tv-item-thumb-btn"
                onClick={() => viewAttachment(photos[0], `/inventory/batteries/${battery.id}/attachments/email`)}
                title="View the photo larger"
              >
                <FramedImage
                  src={photos[0].thumb_url || photos[0].url}
                  alt={battery.name}
                  aspectRatio="16 / 9"
                  fit="contain"
                />
              </button>
            ) : (
              <ItemPhoto photo={undefined} name={battery.name} brand={battery.brand} variant="tile" />
            )}
          </div>
        )}
        <div className={battery ? "tv-item-head-main" : undefined}>
          <h1 style={{ margin: 0, fontSize: "1.5rem" }}>
            {battery?.name ?? "Battery"}
          </h1>
          {battery && (
            <div
              style={{
                display: "flex",
                gap: "0.4rem",
                flexWrap: "wrap",
                marginTop: "0.5rem",
              }}
            >
              {batterySpecChips(battery).map((chip) => (
                <Badge key={chip} tone="accent">
                  {chip}
                </Badge>
              ))}
              <WarrantyBadge battery={battery} />
              {(battery.tags ?? []).map((tag) => (
                <TagChip key={tag.id} name={tag.name} color={tag.color} />
              ))}
              {battery.business_use && <Badge tone="accent">Business use</Badge>}
              {battery.active === false && (
                <Badge tone="warning">Inactive — over plan limit</Badge>
              )}
              {battery.replaced_on && (
                <Badge tone="neutral">
                  Replaced {displayDate(battery.replaced_on)}
                </Badge>
              )}
            </div>
          )}
          {battery && (
            <dl className="tv-item-facts">
              <div className="tv-item-fact">
                <dt>Quantity</dt>
                <dd>{battery.quantity ?? 1}</dd>
              </div>
              {battery.purchase_price !== null && battery.purchase_price !== undefined && (
                <div className="tv-item-fact">
                  <dt>Price</dt>
                  <dd>
                    {money(battery.purchase_price)}
                    {battery.quantity > 1 ? " each" : ""}
                  </dd>
                </div>
              )}
              {battery.purchase_date && (
                <div className="tv-item-fact">
                  <dt>Purchase date</dt>
                  <dd>{displayDate(battery.purchase_date)}</dd>
                </div>
              )}
              {/* The header status pill (owner ruling
                  2026-11-03): immediately right of the purchase
                  date in the facts row. */}
              <ItemStatusPill
                standing={battery.standing}
                data={status}
                itemKind="battery"
                itemId={battery.id}
              />
            </dl>
          )}
        </div>
        {battery && (
          <div className="tv-item-side">
            {/* Sweep B2-F2 (superseding the 2026-11-03 inline
                seat, same change as the tool page): Actions is
                pinned to the header's top-right corner; the
                location plate stays in this column below it. */}
            <ItemActionsMenu
              itemKind="battery"
              item={battery}
              status={status}
              hasModule={has}
              onJump={jump}
              onChanged={onItemChanged}
              onDelete={() => {
                setDeleteError(null);
                setConfirmDelete(true);
              }}
              onStartClaim={() => {
                setActiveTab("claims");
                setClaimSignal((n) => n + 1);
              }}
              onOpenLoss={() => setLossOpen(true)}
              onOpenSale={openSale}
            />
            <ItemLocationColumn location={battery.location} />
          </div>
        )}
      </div>

      {error && <Alert tone="danger">{error}</Alert>}
      {!battery && !error && (
        <p
          style={{
            color: "var(--text-muted)",
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "center",
          }}
        >
          <Spinner size="sm" /> Loading battery…
        </p>
      )}

      {battery && (
        <>
          <ItemStatusStrip
            standing={battery.standing}
            replacedOn={battery.replaced_on}
            replacedByName={battery.replaced_by_name}
            data={status}
            claimsEffective={has("claims")}
            maintenanceEffective={has("maintenance")}
            onJump={jump}
            onOpenLoss={() => setLossOpen(true)}
            onOpenSale={() => openSale("details")}
          />

          <Tabs tabs={tabs} activeId={activeTab} onChange={setActiveTab} />

          <Modal
            open={lossOpen}
            onClose={() => setLossOpen(false)}
            title="Lost / stolen report"
            size="lg"
          >
            <LossReportPanel
              bare
              itemKind="battery"
              itemId={battery.id}
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
              itemKind="battery"
              itemId={battery.id}
              itemName={battery.name}
              quantity={battery.quantity}
              standing={battery.standing}
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
                  deletePath={`/inventory/batteries/${battery.id}/attachments`}
                  onDeleted={() => {
                    setViewing(null);
                    refreshBattery();
                  }}
                />
              ) : undefined
            }
            onClose={() => setViewing(null)}
          />
        </>
      )}

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete this battery?"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setConfirmDelete(false)}
              disabled={deleting}
            >
              Keep it
            </Button>
            <Button variant="danger" onClick={onDelete} loading={deleting}>
              Delete battery
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          "{battery?.name}" will be permanently deleted, along with its
          photos and documents. This can't be undone.
        </p>
        {deleteError && (
          <div style={{ marginTop: "var(--space-3)" }}>
            <Alert tone="danger">{deleteError}</Alert>
          </div>
        )}
      </Modal>
    </div>
  );
}
