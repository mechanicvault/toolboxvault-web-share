import { useCallback, useEffect, useState } from "react";
import "../claims/claims.css";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Modal,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  useToast,
} from "../../components";
import type { TabItem } from "../../components/Tabs";
import { ArtIcon } from "../../components/ArtIcon";
import { api, ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import { useT } from "../../i18n/LocaleContext";
import { usePageCrumbs } from "../../lib/navTrail";
import { disasterClaimsApi } from "../claims/api";
import {
  ChecklistPanel,
  CommsPanel,
  EvidenceSection,
  IncidentForm,
  StatusBadge,
  headerInputFrom,
} from "../claims/components";
import { ClaimActionsMenu, type ClaimMenuEntry } from "../claims/ClaimActionsMenu";
import { ClaimStatusStrip } from "../claims/ClaimStatusStrip";
import { SellerPrice } from "../../components/SellerPrice";
import { fullDate } from "../claims/format";
import type {
  Claim,
  ClaimHeaderInput,
  ClaimTargets,
} from "../claims/types";
import { TargetPicker } from "./ClaimWizard";

/**
 * One DISASTER claim's home (sweep C3, 2026-11-12: rebuilt on
 * the main-tab record layout, in the same family as the repair
 * claim page and the tool/dealer record pages): a header with
 * the claim number, its facts and ONE state-aware Actions
 * dropdown; a live-status strip when the claim carries live
 * states; then REAL tabs — Details (to-do list + the incident
 * record + the insurance agent snapshot), Items, Evidence,
 * Communications. Every fact, section and action from the old
 * stacked page is rehoused here; nothing was added or dropped.
 *
 * The sections below the header are the whole paper trail an
 * adjuster conversation needs: status and next moves, the
 * to-do checklist, the incident record, the snapshotted items,
 * the evidence, the claim package (PDF / Drive / email), and
 * the communications log. Claims separation (2026-11-05): this
 * page serves insurance claims only; warranty claims live on
 * their own page in Claims. One seat reads it: the owner (the
 * insurer is off-platform). The disaster FILING wizard is a
 * separate surface and is untouched by this layout.
 */

export default function DisasterClaimDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const t = useT();
  const [claim, setClaim] = useState<Claim | null>(null);
  // Link tree: Disaster Claims › <claim number>.
  usePageCrumbs(
    claim
      ? [
          { label: t("disasterClaims.title"), to: "/disaster-claims" },
          { label: claim.claim_number },
        ]
      : null,
  );
  const [targets, setTargets] = useState<ClaimTargets | null>(null);
  // Audit A10: whether the owner's Google Drive is connected
  // (null = still loading / unknown). Drives the connect prompt
  // under the package actions.
  const [driveConnected, setDriveConnected] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    api<{ connected: boolean }>("/core/cloud-backup")
      .then((state) => {
        if (!cancelled) setDriveConnected(state.connected);
      })
      .catch(() => {
        if (!cancelled) setDriveConnected(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ClaimHeaderInput>({});
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [addItemsOpen, setAddItemsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("details");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [view, picker] = await Promise.all([
        disasterClaimsApi.getClaim(id),
        disasterClaimsApi.getClaimTargets().catch(() => null),
      ]);
      setClaim(view);
      setForm(headerInputFrom(view));
      setTargets(picker);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("claims.detail.couldntLoad"));
    }
  }, [id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <RequireAuth>
        <Alert tone="danger">{error}</Alert>
        <p>
          <Link to="/disaster-claims" style={{ color: "var(--accent)" }}>
            {t("claims.detail.backAll")}
          </Link>
        </p>
      </RequireAuth>
    );
  }
  if (!claim) {
    return (
      <RequireAuth>
        <div className="tv-claim-loading">
          <Spinner />
        </div>
      </RequireAuth>
    );
  }

  const closed = claim.status === "closed";
  const isDraft = claim.status === "draft";

  async function saveDetails() {
    if (!claim) return;
    setBusy(true);
    try {
      const updated = await disasterClaimsApi.updateClaim(claim.id, form);
      setClaim(updated);
      toast(t("claims.detail.savedToast"), { tone: "success", title: claim.claim_number });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntSave"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doTransition(to: Claim["status"]) {
    if (!claim) return;
    setBusy(true);
    try {
      setClaim(await disasterClaimsApi.transitionClaim(claim.id, to));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDo"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doArchive() {
    if (!claim) return;
    setBusy(true);
    try {
      const updated = await disasterClaimsApi.archiveClaim(
        claim.id,
        !claim.archived,
      );
      setClaim(updated);
      toast(
        updated.archived
          ? t("claims.detail.archivedToast")
          : t("claims.detail.unarchivedToast"),
        { tone: "success", title: claim.claim_number },
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDo"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doDuplicate() {
    if (!claim) return;
    setBusy(true);
    try {
      const copy = await disasterClaimsApi.duplicateClaim(claim.id);
      toast(t("claims.detail.duplicateToast"), {
        tone: "success",
        title: copy.claim_number,
      });
      navigate(`/disaster-claims/${copy.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDuplicate"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
      setBusy(false);
    }
  }

  async function doPackage() {
    if (!claim) return;
    setBusy(true);
    try {
      await disasterClaimsApi.downloadClaimPackage(claim.id, claim.claim_number);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntBuildPackage"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doPackageDrive() {
    if (!claim) return;
    setBusy(true);
    try {
      const saved = await disasterClaimsApi.saveClaimPackageToDrive(claim.id);
      toast(t("claims.detail.packageSavedToast").replace("{filename}", saved.filename), {
        tone: "success",
        title: t("disasterClaims.title"),
      });
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntSavePackage"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doPackageEmail() {
    if (!claim) return;
    setBusy(true);
    try {
      const sent = await disasterClaimsApi.emailClaimPackage(claim.id);
      toast(
        sent.via === "drive_link"
          ? t("claims.detail.packageEmailDriveToast")
          : t("claims.detail.packageEmailAttachedToast"),
        { tone: "success", title: t("disasterClaims.title") },
      );
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntEmailPackage"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    if (!claim) return;
    setBusy(true);
    try {
      await disasterClaimsApi.deleteClaim(claim.id);
      toast(t("claims.detail.draftDeletedToast").replace("{number}", claim.claim_number), {
        tone: "success",
        title: t("disasterClaims.title"),
      });
      navigate("/disaster-claims");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDelete"), {
        tone: "danger",
        title: t("disasterClaims.title"),
      });
      setBusy(false);
    }
  }

  /* The ONE Actions menu (sweep C3): every control the old
   * headbar scattered — the allowed transitions, the three
   * package doors, Duplicate, Archive, Delete draft —
   * rehoused in the header's top-right dropdown with the same
   * state rules. F5-08's next-step hierarchy survives as menu
   * order: the transitions lead, in their allowed order, with
   * Close claim carrying the danger tone its button had; the
   * package and utility actions follow below the separator. */
  const menuEntries: ClaimMenuEntry[] = [];
  for (const to of claim.allowed_transitions) {
    menuEntries.push({
      key: `transition-${to}`,
      kind: "action",
      label: t(`claims.transition.${to}` as never),
      danger: to === "closed",
      run: () => void doTransition(to),
    });
  }
  if (menuEntries.length > 0) {
    menuEntries.push({ key: "sep-utility", kind: "separator" });
  }
  menuEntries.push(
    {
      key: "package-pdf",
      kind: "action",
      label: t("claims.detail.packagePdf"),
      run: () => void doPackage(),
    },
    {
      key: "package-drive",
      kind: "action",
      label: t("claims.detail.packageDrive"),
      run: () => void doPackageDrive(),
    },
    {
      key: "package-email",
      kind: "action",
      label: t("claims.detail.packageEmail"),
      run: () => void doPackageEmail(),
    },
    {
      key: "duplicate",
      kind: "action",
      label: t("claims.detail.duplicate"),
      run: () => void doDuplicate(),
    },
    {
      key: "archive",
      kind: "action",
      label: claim.archived
        ? t("claims.detail.unarchive")
        : t("claims.detail.archive"),
      run: () => void doArchive(),
    },
  );
  if (isDraft) {
    menuEntries.push({
      key: "delete",
      kind: "action",
      label: t("claims.detail.deleteDraft"),
      danger: true,
      run: () => setConfirmDelete(true),
    });
  }

  const headerFacts = [
    {
      label: t("claims.col.incident"),
      value: t(`claims.incident.${claim.incident_type}` as never),
    },
    ...(claim.incident_date
      ? [
          {
            label: t("claims.form.incidentDate"),
            value: fullDate(claim.incident_date),
          },
        ]
      : []),
    ...(claim.insurer_name
      ? [{ label: t("disasterClaims.col.insurer"), value: claim.insurer_name }]
      : []),
    ...(claim.policy_number
      ? [
          {
            label: t("claims.form.policyNumber"),
            value: claim.policy_number,
          },
        ]
      : []),
    { label: t("claims.col.items"), value: String(claim.lines.length) },
    {
      label: t("claims.detail.claimTotal"),
      value: (
        <SellerPrice
          amount={claim.total_amount}
          currency={claim.owner_currency}
        />
      ),
    },
  ];

  const tabs: TabItem[] = [
    {
      id: "details",
      label: t("claims.detailTab.details"),
      content: (
        <div className="tv-claim-detail-stack">
          <div className="tv-claim-cols">
            <ChecklistPanel
              claim={claim}
              onClaimChange={setClaim}
              claimApi={disasterClaimsApi}
            />
            <Panel
              title={t("claims.detail.title")}
              actions={
                !closed ? (
                  <Button size="sm" variant="secondary" disabled={busy} onClick={saveDetails}>
                    {t("claims.detail.saveChanges")}
                  </Button>
                ) : undefined
              }
            >
              <IncidentForm
                value={form}
                onChange={setForm}
                incidentLocked={!isDraft}
                readOnly={closed}
              />
              {closed && (
                <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
                  {t("claims.detail.closedNote")}
                </p>
              )}
            </Panel>
          </div>

          {/* The insurance agent snapshot: contact details copied
              onto the claim from the owner's My Insurance profile
              at filing. */}
          {(claim.agent_name || claim.agent_phone || claim.agent_email) && (
            <Panel title={t("claims.detail.agentTitle")}>
              <div style={{ display: "grid", gap: "0.35rem" }}>
                {claim.agent_name && (
                  <p style={{ margin: 0, fontWeight: 600 }}>{claim.agent_name}</p>
                )}
                {claim.agent_phone && (
                  <p style={{ margin: 0 }}>
                    <a
                      href={`tel:${claim.agent_phone.replace(/[^+\d]/g, "")}`}
                      style={{ color: "var(--accent)" }}
                    >
                      {claim.agent_phone}
                    </a>
                  </p>
                )}
                {claim.agent_email && (
                  <p style={{ margin: 0 }}>
                    <a
                      href={`mailto:${claim.agent_email}`}
                      style={{ color: "var(--accent)" }}
                    >
                      {claim.agent_email}
                    </a>
                  </p>
                )}
                <p style={{ color: "var(--text-muted)", margin: 0 }}>
                  {t("claims.detail.agentCopied")}
                </p>
              </div>
            </Panel>
          )}
        </div>
      ),
    },
    {
      id: "items",
      label: t("claims.detailTab.items"),
      content: (
        <Panel
          title={t("claims.detail.itemsTitle")}
          actions={
            isDraft ? (
              <Button size="sm" variant="secondary" onClick={() => setAddItemsOpen(true)}>
                {t("claims.detail.addItems")}
              </Button>
            ) : undefined
          }
        >
          <div className="tv-claim-lines">
            {claim.lines.length === 0 && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("claims.detail.noItems")}
              </p>
            )}
            {claim.lines.map((line) => (
              <div key={line.id} className="tv-claim-line">
                <span>
                  <strong>{line.target_name}</strong>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    {line.target_kind === "set" &&
                      `· ${t("claims.detail.lineWholeSet")}${line.include_addons ? `, ${t("claims.detail.lineAddonsIncluded")}` : `, ${t("claims.detail.lineAddonsNotIncluded")}`}`}
                    {line.target_kind === "piece" &&
                      `· ${t("claims.detail.linePieceOf").replace("{name}", line.set_name ?? "")}`}
                    {line.target_kind === "piece" &&
                      line.target_part_number &&
                      ` · ${t("claims.line.partNumber")} ${line.target_part_number}`}
                    {line.target_kind === "piece" &&
                      line.set_model_number &&
                      ` · ${t("claims.line.setModelNumber")} ${line.set_model_number}`}
                    {line.target_kind === "battery" && `· ${t("claims.detail.lineBattery")}`}
                    {" "}· {t(`claims.basis.${line.value_basis}` as never)} —{" "}
                    {t("claims.detail.lineRecordedNote")}
                  </span>
                  {!closed && (
                    <span style={{ display: "block", marginTop: "0.3rem" }}>
                      <Checkbox
                        checked={line.include_in_package}
                        onChange={async (e) => {
                          const next = e.target.checked;
                          try {
                            const updated =
                              await disasterClaimsApi.setLinePackage(
                                claim.id,
                                line.id,
                                next,
                              );
                            setClaim((prev) =>
                              prev
                                ? {
                                    ...prev,
                                    lines: prev.lines.map((l) =>
                                      l.id === updated.id ? updated : l,
                                    ),
                                  }
                                : prev,
                            );
                          } catch (err) {
                            toast(
                              err instanceof ApiError
                                ? err.message
                                : t("claims.detail.couldntPackageToggle"),
                              { tone: "danger", title: t("disasterClaims.title") },
                            );
                          }
                        }}
                        label={t("claims.detail.includeInPackage")}
                      />
                    </span>
                  )}
                  {closed && !line.include_in_package && (
                    <span
                      style={{
                        display: "block",
                        marginTop: "0.3rem",
                        color: "var(--text-muted)",
                      }}
                    >
                      {t("claims.detail.notInPackage")}
                    </span>
                  )}
                </span>
                <strong>
                  <SellerPrice amount={line.amount} currency={claim.owner_currency} />
                </strong>
              </div>
            ))}
            <div className="tv-claim-total">
              <strong>{t("claims.detail.claimTotal")}</strong>
              <strong>
                <SellerPrice amount={claim.total_amount} currency={claim.owner_currency} />
              </strong>
            </div>
          </div>
        </Panel>
      ),
    },
    {
      id: "evidence",
      label: t("claims.detailTab.evidence"),
      content: (
        <Panel title={t("claims.detail.evidenceTitle")}>
          <EvidenceSection
            claim={claim}
            targets={targets}
            editable={!closed}
            canRemove={!closed}
            onClaimChange={setClaim}
            claimApi={disasterClaimsApi}
          />
        </Panel>
      ),
    },
    {
      id: "comms",
      label: t("claims.detailTab.comms"),
      content: (
        <CommsPanel
          claim={claim}
          onClaimChange={setClaim}
          claimApi={disasterClaimsApi}
        />
      ),
    },
  ];

  return (
    <RequireAuth>
      <div className="tv-claims-page">
        <div>
          <Link to="/disaster-claims" className="tv-claim-backlink">
            {t("claims.detail.backAll")}
          </Link>
          <SectionPageHeader
            thumb={<ArtIcon name="disaster" size={96} />}
            title={claim.claim_number}
            facts={headerFacts}
            factsExtra={
              <span className="tv-claim-headmeta">
                <StatusBadge status={claim.status} />
                {claim.archived && (
                  <Badge tone="neutral">{t("claims.detail.archived")}</Badge>
                )}
              </span>
            }
            actions={
              <ClaimActionsMenu
                claimNumber={claim.claim_number}
                entries={menuEntries}
                disabled={busy}
              />
            }
            statusStrip={
              <ClaimStatusStrip claim={claim} onJump={setActiveTab} />
            }
          />
          {driveConnected === false && (
            <p style={{ color: "var(--text-muted)", margin: "0.6rem 0 0" }}>
              {t("claims.detail.driveNoticeBefore")}{" "}
              <Link
                to="/settings/cloud-backup"
                style={{ color: "var(--accent)", fontWeight: 600 }}
              >
                {t("claims.detail.driveNoticeLink")}
              </Link>{" "}
              {t("claims.detail.driveNoticeAfter")}
            </p>
          )}
        </div>

        <Tabs tabs={tabs} activeId={activeTab} onChange={setActiveTab} />
      </div>

      <Modal
        open={addItemsOpen}
        onClose={() => setAddItemsOpen(false)}
        title={t("claims.detail.itemsModalTitle").replace("{number}", claim.claim_number)}
        size="lg"
        footer={
          <Button onClick={() => setAddItemsOpen(false)}>{t("claims.detail.done")}</Button>
        }
      >
        {targets ? (
          <TargetPicker
            claim={claim}
            targets={targets}
            onClaimChange={setClaim}
          />
        ) : (
          <Spinner />
        )}
      </Modal>

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("claims.detail.deleteTitle").replace("{number}", claim.claim_number)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              {t("claims.detail.keepIt")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={doDelete}>
              {t("claims.detail.deleteDraft")}
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          {t("claims.detail.deleteBody")}
        </p>
      </Modal>
    </RequireAuth>
  );
}
