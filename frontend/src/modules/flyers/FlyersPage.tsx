import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./flyers.css";
import {
  Button,
  EmptyState,
  LinkButton,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { listPostable, listSources, sourceDetail } from "./api";
import { CompanyFlyersPanel } from "./CompanyFlyersPanel";
import type { FlyerSource } from "./types";

interface CompanyGroup {
  company_id: string;
  name: string;
  sources: FlyerSource[];
}

/** Group the visible sources into ONE tab per company (owner
 *  order, 2026-11-09: the tab unit is the COMPANY — "Matco" —
 *  not the flyer spot). First-appearance order is preserved:
 *  the sources list arrives oldest-spot-first from the API. */
function groupByCompany(sources: FlyerSource[]): CompanyGroup[] {
  const groups: CompanyGroup[] = [];
  const byId = new Map<string, CompanyGroup>();
  for (const source of sources) {
    let group = byId.get(source.company_id);
    if (!group) {
      group = {
        company_id: source.company_id,
        name: source.company_name,
        sources: [],
      };
      byId.set(source.company_id, group);
      groups.push(group);
    }
    group.sources.push(source);
  }
  return groups;
}

/** Deep links name a SOURCE — /flyers#<source key> is what the
 *  Home widget's teasers and the new-flyer notifications point
 *  at (backend inbox links carry the same key). With company
 *  tabs, the link lands on that source's COMPANY tab. */
function companyIdForHash(
  hash: string,
  sources: FlyerSource[],
  postable: FlyerSource[],
): string | null {
  const raw = hash.replace(/^#/, "");
  if (!raw) return null;
  let key = raw;
  try {
    key = decodeURIComponent(raw);
  } catch {
    /* keep the raw hash */
  }
  const hit = [...sources, ...postable].find((s) => s.key === key);
  if (hit) return hit.company_id;
  if (key.startsWith("company:")) return key.slice("company:".length);
  return null;
}

/**
 * Flyers (owner order, 2026-11-05 #10; main tab layout
 * conformance, 2026-11-09): a MAIN TAB LAYOUT page on the
 * shared kit — header (thumbnail, title, facts, Actions), then
 * ONE TAB PER COMPANY that has a flyer spot the user is
 * connected to. Each tab is a true list of that company's
 * flyers — every spot's current flyer plus its past flyers,
 * newest posted first — and clicking a flyer opens it in the
 * preview window (the shared AttachmentViewer); nothing is
 * embedded in the tab anymore. A poster's own controls (post
 * a flyer, the spot's settings, take down) ride inside the
 * tab of the company they belong to, behind the same
 * can_post gate as always; spots whose company has no tab
 * yet ride in the "Post a flyer" section below the tabs.
 * Deep links land on a source's company tab:
 * /flyers#<source key> (the Home widget and the new-flyer
 * notifications both point here).
 */
function FlyersHome() {
  const t = useT();
  const { hash } = useLocation();
  const navigate = useNavigate();
  const [sources, setSources] = useState<FlyerSource[] | null>(null);
  const [postable, setPostable] = useState<FlyerSource[]>([]);
  const [details, setDetails] = useState<Record<string, FlyerSource>>({});
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, mine] = await Promise.all([listSources(), listPostable()]);
      setSources(list);
      setPostable(mine);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("home.widgetLoadFailed"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const companies = useMemo(
    () => groupByCompany(sources ?? []),
    [sources],
  );

  // A deep link names a source; follow it to its company tab —
  // on arrival AND on later hash changes while this page stays
  // mounted (the Lane 1 hash-follow pattern: a bell click
  // through to another dealer must move the tab too).
  const hashCompany = useMemo(
    () => companyIdForHash(hash, sources ?? [], postable),
    [hash, sources, postable],
  );
  useEffect(() => {
    if (hashCompany) setPicked(hashCompany);
  }, [hashCompany]);

  const activeCompanyId = useMemo(() => {
    if (companies.length === 0) return null;
    if (picked && companies.some((c) => c.company_id === picked)) {
      return picked;
    }
    return companies[0].company_id;
  }, [companies, picked]);

  const activeCompany = useMemo(
    () => companies.find((c) => c.company_id === activeCompanyId) ?? null,
    [companies, activeCompanyId],
  );

  // The list read carries each spot's CURRENT flyer only; the
  // tab's list needs the history too, so fetch the detail of
  // every spot on the active company's tab (the poster's own
  // spots already arrive with history via /postable).
  useEffect(() => {
    if (!activeCompany) return;
    let cancelled = false;
    for (const source of activeCompany.sources) {
      if (!source.id || details[source.id]) continue;
      const id = source.id;
      sourceDetail(id)
        .then((d) => {
          if (!cancelled) {
            setDetails((prev) => ({ ...prev, [id]: d }));
          }
        })
        .catch(() => {
          /* the list view (current flyer) still renders */
        });
    }
    return () => {
      cancelled = true;
    };
  }, [activeCompany, details]);

  const refresh = useCallback(() => {
    setDetails({});
    void load();
  }, [load]);

  if (sources === null && !error) return <Spinner label="Loading…" />;

  const tabCompanies = companies;
  const liveCount = (sources ?? []).filter((s) => s.current).length;

  // The active tab's spots, resolved to their richest view:
  // the detail read when it has landed, else the list view;
  // the poster's own spots for this company join by key (an
  // invisible own spot has no tab presence as a viewer, but
  // its poster still manages — and sees — it here).
  function resolvedSources(company: CompanyGroup): FlyerSource[] {
    const byKey = new Map<string, FlyerSource>();
    for (const source of company.sources) {
      byKey.set(
        source.key,
        (source.id && details[source.id]) || source,
      );
    }
    for (const entry of postable) {
      if (entry.company_id === company.company_id && !byKey.has(entry.key)) {
        byKey.set(entry.key, entry);
      }
    }
    return [...byKey.values()];
  }

  const tabs: TabItem[] = tabCompanies.map((company) => ({
    id: company.company_id,
    label: company.name,
    content:
      company.company_id === activeCompanyId ? (
        <CompanyFlyersPanel
          sources={resolvedSources(company)}
          onChanged={refresh}
        />
      ) : (
        <Spinner label="Loading…" />
      ),
  }));

  // "Post a flyer" below the tabs: the spots this user
  // controls whose company has NO tab (nothing they can see
  // is posted there yet, or their own spot is switched off) —
  // the same seat the page has always kept for them.
  const tabbedIds = new Set(tabCompanies.map((c) => c.company_id));
  const manageCompanies = groupByCompany(
    postable.filter((s) => !tabbedIds.has(s.company_id)),
  );

  return (
    <div>
      <SectionPageHeader
        thumb={<ArtIcon name="flyers" size={96} />}
        title={t("flyers.title")}
        subtitle={t("flyers.subtitle")}
        facts={
          sources !== null
            ? [
                {
                  label: t("flyers.factCompanies"),
                  value: String(tabCompanies.length),
                },
                {
                  label: t("flyers.factLive"),
                  value: String(liveCount),
                },
              ]
            : undefined
        }
        actions={
          /* The Actions menu ALWAYS rides the header (sweep
             06-F1): the tab jumps when companies exist, and the
             Settings door — to this module's own setting, the
             new-flyer alerts toggle in Settings → Notifications
             — in every state, the empty one included. */
          <SettingsActionsMenu
            ariaLabel={t("flyers.title")}
            buttonLabel={t("inventory.actions")}
            entries={tabs.map((tab) => ({
              key: tab.id,
              label: tab.label,
              run: () => setPicked(tab.id),
            }))}
            settingsEntry={{
              key: "settings",
              label: t("shell.settings"),
              run: () => navigate("/settings/notifications"),
            }}
          />
        }
      />

      {error ? <p className="flyer-error">{error}</p> : null}

      {tabs.length > 0 ? (
        <Tabs
          tabs={tabs}
          activeId={activeCompanyId ?? undefined}
          onChange={(id) => setPicked(id)}
        />
      ) : (
        <Panel>
          {/* The shared nothing-here-yet kit (Sweep A1): art,
              one directing sentence, one door. A poster seat's
              door is its own post form, which already rides
              below as the manage section; everyone else's door
              is the dealer directory, where the connection that
              makes flyers appear here is made. */}
          <EmptyState
            art="flyers"
            title={t("flyers.emptyTitle")}
            description={
              postable.length > 0
                ? t("flyers.emptyPoster")
                : t("flyers.empty")
            }
            action={
              postable.length > 0 ? (
                <Button
                  type="button"
                  onClick={() =>
                    document
                      .getElementById("flyers-post")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  {t("flyers.postTitle")}
                </Button>
              ) : (
                <LinkButton to="/dealers">{t("flyers.findDealers")}</LinkButton>
              )
            }
          />
        </Panel>
      )}

      {manageCompanies.length > 0 ? (
        <div className="flyer-manage" id="flyers-post">
          <h2 className="flyer-manage-title">{t("flyers.postTitle")}</h2>
          {manageCompanies.map((company) => (
            <Panel key={company.company_id} title={company.name}>
              <CompanyFlyersPanel
                sources={company.sources}
                onChanged={refresh}
                onPosted={() => {
                  setPicked(company.company_id);
                  refresh();
                }}
              />
            </Panel>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function FlyersPage() {
  return (
    <RequireAuth>
      <FlyersHome />
    </RequireAuth>
  );
}
