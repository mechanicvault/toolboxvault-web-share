import { useState } from "react";

import { Badge, Button, useToast } from "../../components";
import { formatBytes } from "../../components/AttachmentViewer";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import {
  importManual,
  locateManual,
  searchManuals,
  type ManualCandidate,
  type ManualSearchResult,
} from "./api";
import "./manualFinder.css";

/** Find the manual (owner order 2026-11-05) — ONE component,
 *  shared by the Add wizard and the item pages' Manuals area
 *  so both behave identically.
 *
 *  The tiers are the owner's, in his words: the feature is
 *  supposed to PULL a manual into the system, and links are
 *  "a backup in case it can't find a manual". So:
 *    - FOUND MANUALS: direct documents the server has already
 *      proven it can pull (PDF-verified before listing). Pick
 *      one and the file is downloaded into the item's Manuals.
 *    - NO MANUAL FOUND: the panel says so plainly, and only
 *      then shows the backup tier — manufacturer/support web
 *      pages to go look at — never dressed up as manuals.
 *  Item mode imports immediately on pick (the item exists).
 *  Wizard mode only REMEMBERS the pick; the wizard imports it
 *  through the same endpoint the moment the item is created. */
export type ManualFinderProps =
  | {
      mode: "item";
      segment: "tools" | "batteries";
      itemId: string;
      itemName: string;
      brand: string;
      model: string;
      onSaved: () => void;
    }
  | {
      mode: "wizard";
      brand: string;
      model: string;
      picked: ManualCandidate | null;
      onPick: (candidate: ManualCandidate | null) => void;
    };

export function ManualFinder(props: ManualFinderProps) {
  const t = useT();
  const { toast } = useToast();
  const [result, setResult] = useState<ManualSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const [savedUrls, setSavedUrls] = useState<ReadonlySet<string>>(new Set());

  const pickedUrl =
    props.mode === "wizard" ? (props.picked?.source_url ?? null) : null;

  const search = async () => {
    if (
      props.mode === "wizard" &&
      !props.brand.trim() &&
      !props.model.trim()
    ) {
      toast(t("catalog.manual.needBrandModel"), { tone: "danger" });
      return;
    }
    setBusy(true);
    setFailed(false);
    try {
      const data =
        props.mode === "item"
          ? await locateManual(props.segment, props.itemId)
          : await searchManuals(props.brand, props.model);
      setResult(data);
    } catch (err) {
      setFailed(true);
      if (err instanceof ApiError) toast(err.message, { tone: "danger" });
      else toast(t("catalog.manual.searchFailed"), { tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const pick = async (candidate: ManualCandidate) => {
    if (props.mode === "wizard") {
      props.onPick(
        props.picked?.source_url === candidate.source_url ? null : candidate,
      );
      return;
    }
    setImporting(candidate.source_url);
    try {
      const data = await importManual(
        props.segment,
        props.itemId,
        candidate.source_url,
        candidate.source_name,
      );
      setSavedUrls((prev) => new Set(prev).add(candidate.source_url));
      toast(
        data.already_present
          ? t("catalog.manual.already")
          : t("catalog.manual.saved"),
        { tone: "success" },
      );
      props.onSaved();
    } catch (err) {
      if (err instanceof ApiError) toast(err.message, { tone: "danger" });
      else toast(t("catalog.manual.addFailed"), { tone: "danger" });
    } finally {
      setImporting(null);
    }
  };

  const candidates = result?.candidates ?? [];
  const links = result?.links ?? [];

  return (
    <div className="tv-manual-finder">
      <div className="tv-manual-finder__head">
        <p className="tv-muted tv-manual-finder__intro">
          {t("catalog.manual.intro")}
        </p>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => void search()}
        >
          {busy ? t("catalog.manual.searching") : t("catalog.manual.find")}
        </Button>
      </div>

      {busy && (
        <p className="tv-muted tv-manual-finder__note">
          {t("catalog.manual.searching")}
        </p>
      )}
      {!busy && failed && result === null && (
        <p className="tv-manual-finder__note">
          {t("catalog.manual.searchFailed")}
        </p>
      )}

      {result !== null && candidates.length > 0 && (
        <div className="tv-manual-rows">
          <p className="tv-manual-finder__note">
            <strong>{t("catalog.manual.foundTitle")}</strong>
            <br />
            <span className="tv-muted">{t("catalog.manual.foundHint")}</span>
          </p>
          {candidates.map((candidate) => (
            <div key={candidate.source_url} className="tv-manual-row">
              <span className="tv-manual-row__main">
                <span className="tv-manual-row__title">{candidate.title}</span>
                <br />
                <span className="tv-muted">
                  {candidate.source_name} · {t("catalog.manual.pdf")}
                  {candidate.size_bytes
                    ? ` · ${formatBytes(candidate.size_bytes)}`
                    : ""}
                </span>
              </span>
              {props.mode === "item" ? (
                savedUrls.has(candidate.source_url) ? (
                  <Badge tone="success">{t("catalog.manual.saved")}</Badge>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    disabled={importing !== null}
                    onClick={() => void pick(candidate)}
                  >
                    {importing === candidate.source_url
                      ? t("catalog.manual.adding")
                      : t("catalog.manual.addThis")}
                  </Button>
                )
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant={
                    pickedUrl === candidate.source_url ? "primary" : "secondary"
                  }
                  onClick={() => void pick(candidate)}
                >
                  {pickedUrl === candidate.source_url
                    ? t("wizard.manuals.removePick")
                    : t("catalog.manual.addThis")}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {result !== null && candidates.length === 0 && (
        <div className="tv-manual-rows">
          <p className="tv-manual-finder__note">
            <strong>{t("catalog.manual.noneTitle")}</strong>
            <br />
            <span className="tv-muted">
              {links.length > 0
                ? t("catalog.manual.noneBody")
                : t("catalog.manual.noneBodyNoLinks")}
            </span>
          </p>
          {links.map((link) => (
            <div key={link.source_url} className="tv-manual-row">
              <span className="tv-manual-row__main">
                <span className="tv-manual-row__title">{link.title}</span>
                <br />
                <span className="tv-muted">{link.source_name}</span>
              </span>
              <a
                className="tv-btn tv-btn--secondary tv-btn--sm"
                href={link.source_url}
                target="_blank"
                rel="noreferrer"
              >
                {t("catalog.manual.open")}
              </a>
            </div>
          ))}
        </div>
      )}

      {props.mode === "wizard" && props.picked !== null && (
        <div className="tv-manual-picked">
          <span className="tv-manual-row__main">
            {t("wizard.manuals.picked").replace("{title}", props.picked.title)}
          </span>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => props.onPick(null)}
          >
            {t("wizard.manuals.removePick")}
          </Button>
        </div>
      )}
    </div>
  );
}
