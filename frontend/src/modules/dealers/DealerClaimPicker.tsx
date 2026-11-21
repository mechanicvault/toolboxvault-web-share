import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  ItemThumb,
  Modal,
  TextInput,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { ClaimForm, type ClaimFormData } from "../claims/BrokenItemActions";
import { createWarrantyClaim } from "../claims/api";
import type { TargetKind } from "../claims/types";
import type { CompanyItemRef } from "./types";

/**
 * Open Claims → "Start a claim" (owner ask, 2026-11-03): a
 * picker over the VIEWER's tools attached to THIS dealer — the
 * exact list the page's Tools tab shows (the my-records items),
 * with a search over name / brand / model / serial. Picking a
 * tool opens the standard warranty ClaimForm with that tool
 * preselected; the dealer and the agent on record default
 * exactly as the claims model resolves them (the form's own
 * options read), and creating rides createWarrantyClaim onto
 * the new claim — the same path as the item page's action.
 */
export function DealerClaimPicker({
  items,
  disabled = false,
}: {
  items: CompanyItemRef[];
  /** "View as visitor" preview (Sweep D5): the door renders
   *  as a member sees it but cannot open — starting a claim
   *  is a write, and nothing in preview mode writes. */
  disabled?: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<CompanyItemRef | null>(null);
  const [busy, setBusy] = useState(false);
  /* The B-02/B-03 synchronous in-flight guard, same as the
   * broken prompt's: React state can't stop same-task repeats. */
  const busyRef = useRef(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) =>
      [item.name, item.brand, item.model, item.serial]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [items, query]);

  function close() {
    setOpen(false);
    setPicked(null);
    setQuery("");
  }

  async function startClaim(data: ClaimFormData) {
    if (!picked || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    const targetKind: TargetKind = picked.is_set ? "set" : picked.item_kind;
    try {
      const result = await createWarrantyClaim({
        target_kind: targetKind,
        target_id: picked.id,
        include_addons: data.include_addons,
        dealer_notified: data.dealer_notified,
        problem: data.problem,
        agent_user_id: data.agent_user_id,
        private_agent_id: data.private_agent_id,
        no_agent: data.no_agent,
        filed_with: data.filed_with,
      });
      toast(
        result.reported
          ? t("claims.broken.claimReported")
          : t("claims.broken.claimNotReported"),
        { tone: "success", title: result.claim.claim_number },
      );
      close();
      navigate(`/claims/${result.claim.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't start that claim.", {
        tone: "danger",
        title: "Claims",
      });
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)} disabled={disabled}>
        {t("dealers.picker.startClaim")}
      </Button>
      <Modal
        open={open}
        onClose={close}
        title={
          picked
            ? t("dealers.picker.startClaim")
            : t("dealers.picker.title")
        }
      >
        {picked ? (
          <div>
            <p className="tv-agent-notes">
              <strong>{picked.name}</strong>
              {[picked.brand, picked.model].filter(Boolean).length > 0 &&
                ` — ${[picked.brand, picked.model].filter(Boolean).join(" · ")}`}
            </p>
            <ClaimForm
              showAddons={picked.is_set}
              busy={busy}
              targetKind={picked.is_set ? "set" : picked.item_kind}
              targetId={picked.id}
              onCancel={() => setPicked(null)}
              onCreate={(data) => void startClaim(data)}
            />
          </div>
        ) : (
          <div>
            <p className="tv-agent-notes">{t("dealers.picker.intro")}</p>
            {items.length === 0 ? (
              <p className="tv-agent-notes">{t("dealers.picker.empty")}</p>
            ) : (
              <>
                <div className="tv-picker-search">
                  <TextInput
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t("dealers.picker.search")}
                    aria-label={t("dealers.picker.search")}
                  />
                </div>
                {filtered.length === 0 ? (
                  <p className="tv-agent-notes">{t("dealers.picker.noMatches")}</p>
                ) : (
                  <div className="tv-picker-list">
                    {filtered.map((item) => (
                      <button
                        key={`${item.item_kind}-${item.id}`}
                        type="button"
                        className="tv-picker-row"
                        onClick={() => setPicked(item)}
                      >
                        <span className="tv-thumb-cell--sm">
                          <ItemThumb
                            src={item.photo?.thumb_url_sm || item.photo?.thumb_url || null}
                            name={item.name}
                            aspectRatio="4 / 3"
                          />
                        </span>
                        <span className="tv-picker-row-main">
                          <span>
                            <strong>{item.name}</strong>{" "}
                            {item.is_set && (
                              <Badge tone="neutral">{t("dealers.picker.setBadge")}</Badge>
                            )}
                            {item.item_kind === "battery" && (
                              <Badge tone="neutral">
                                {t("dealers.picker.batteryBadge")}
                              </Badge>
                            )}
                          </span>
                          <span className="tv-agent-meta">
                            {[item.brand, item.model, item.serial]
                              .filter(Boolean)
                              .join(" · ")}
                            {item.quantity > 1 ? ` · ×${item.quantity}` : ""}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
