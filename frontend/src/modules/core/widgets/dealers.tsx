import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatMoney } from "../../../lib/money";
import { getDealerListSettings, listCompanies, listPreferred } from "../../dealers/api";
import { dayLabel, summarizePreferred } from "../../dealers/rosterFormat";
import { listAccounts } from "../../truck-accounts/api";
import type { TruckAccount } from "../../truck-accounts/types";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const dealersWidget: WidgetDef = {
    icon: <ArtIcon name="dealers" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      // Dealer Directory widget REBUILT (dashboard-flare lane,
      // owner order 2026-11-09): the widget stops reciting the
      // agent-stats lines and shows the user's OWN dealers —
      // the same list the Dealers page shows them (directory
      // companies they haven't hidden, then their own private
      // companies) — as a thumbnail strip: each dealer's logo
      // where the record carries one, the dealers artwork
      // where it doesn't, one tap to that dealer's page. Two
      // real doors ride the actions slot: Find a dealer (the
      // find-an-agent search) and the Dealer directory itself.
      // The old /dealers/stats lines were an agent's mirror
      // (preferred-by counts); a dealer-group user's dashboard
      // block still carries that world — this widget is the
      // directory's.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 16);
      // Custom-widget aspect gates (Lane 2): the tile strip
      // and the two door buttons carry their own switches,
      // both defaulting ON — absence is today's widget.
      const showTiles = optBool(settings, "showTiles", true);
      const showActions = optBool(settings, "showActions", true);
      const [companies, listSettings, preferred, accounts] =
        await Promise.all([
          listCompanies(),
          getDealerListSettings().catch(() => null),
          listPreferred().catch(() => []),
          // Sheet row 51: the Agents / Visiting tabs carry
          // each agent's truck-account facts — loaded
          // softly (the truck module can be off).
          listAccounts().catch(() => [] as TruckAccount[]),
        ]);
      const hidden = new Set(
        (listSettings?.directory ?? [])
          .filter((row) => row.hidden)
          .map((row) => row.company.id),
      );
      const mine = [
        ...companies.filter((c) => c.is_directory && !hidden.has(c.id)),
        ...companies.filter((c) => !c.is_directory),
      ];
      // Sample redesign (2026-11-15): the logo strip gives way
      // to the sample's shape — the counts line, TABS (Dealers /
      // With agents / Visiting this week), and monogram rows:
      // the dealer's name, its agent and route day as the quiet
      // sub-line, and the next-visit pill when one is close.
      // The agent named is the standing preferred summary (one
      // flagged, else the earliest connection; several flagged
      // name nobody — "Multiple agents").
      const byCompany = new Map<string, typeof preferred>();
      for (const row of preferred) {
        const list = byCompany.get(row.company_id) ?? [];
        list.push(row);
        byCompany.set(row.company_id, list);
      }
      const today = new Date();
      const dayMs = 24 * 60 * 60 * 1000;
      const startOfDay = (d: Date) =>
        new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
      const enriched = mine.map((c) => {
        const summary = summarizePreferred(byCompany.get(c.id) ?? []);
        const agent = summary.state === "one" ? summary.agent : null;
        const nextVisit = agent?.next_visit
          ? new Date(`${agent.next_visit.slice(0, 10)}T12:00:00`)
          : null;
        const daysAway = nextVisit
          ? Math.round((startOfDay(nextVisit) - startOfDay(today)) / dayMs)
          : null;
        return { company: c, summary, agent, daysAway };
      });
      const withAgents = enriched.filter((e) => e.summary.state !== "none");
      // Sheet row 51 (owner): truck facts per agent — the
      // viewer's own customer accounts matched to the
      // agent by company + private record (platform agents
      // match on the name the account itself carries).
      const companyById = new Map(companies.map((c) => [c.id, c]));
      const myAccounts = accounts.filter(
        (a) => a.my_role === "customer" && a.status !== "closed",
      );
      const accountsFor = (entry: (typeof preferred)[number]) =>
        myAccounts.filter(
          (a) =>
            a.dealer_company_id === entry.company_id &&
            (entry.private_agent_id
              ? a.private_agent_id === entry.private_agent_id
              : a.agent_name === entry.name),
        );
      const owedFor = (entry: (typeof preferred)[number]) => {
        const list = accountsFor(entry);
        if (list.length === 0) return null;
        return {
          total: list.reduce((s, a) => s + Number(a.balance || 0), 0),
          currency: list[0].currency,
          weekly:
            list.find((a) => a.payment_amount)?.payment_amount ?? null,
        };
      };
      const daysAwayFor = (iso: string | null) => {
        if (!iso) return null;
        const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
        return Math.round((startOfDay(d) - startOfDay(today)) / dayMs);
      };
      const data: WidgetData = { lines: [] };
      if (showCount) {
        data.counts = [
          {
            value: count(mine.length),
            label: line(t, "home.widget.dealersCountWord", "dealers in your directory"),
          },
          {
            value: count(withAgents.length),
            label: line(t, "home.widget.dealersWithAgentsWord", "with agents"),
          },
        ];
      }
      // Sheet row 51 (owner) rebuild: the three tabs stop
      // sharing one stacked row. Dealers: the agent name
      // rides in its OWN column, never under the dealer
      // name. Agents: one row per agent — dealer, agent,
      // total truck account. Visiting: dealer > agent >
      // total owed > weekly payment > day, each in its
      // own column. Every row leads with the dealer's
      // logo where the record carries one, the monogram
      // tile where it doesn't.
      const leadFor = (companyId: string, name: string) => {
        const company = companyById.get(companyId);
        return {
          monogram: name.trim().charAt(0).toUpperCase() || "?",
          monogramImg: company?.logo_url ?? undefined,
        };
      };
      const dealerRow = (e: (typeof enriched)[number]) => {
        const pill =
          e.daysAway === 0 ? (
            <Badge key="pill" tone="success">
              {line(t, "home.widget.visitToday", "TODAY")}
            </Badge>
          ) : e.daysAway === 1 ? (
            <Badge key="pill" tone="success">
              {line(t, "home.widget.visitTomorrow", "TOMORROW")}
            </Badge>
          ) : null;
        const agentCell =
          e.summary.state === "many" ? (
            <span key="agent" className="tv-widget-cellsub">
              {line(t, "home.widget.dealerMultipleAgents", "Multiple agents")}
            </span>
          ) : e.agent ? (
            e.agent.name
          ) : (
            <span key="agent" className="tv-widget-cellsub">
              {line(t, "home.widget.dealerNoAgent", "No agent yet")}
            </span>
          );
        return {
          ...leadFor(e.company.id, e.company.name),
          cells: [
            <span key="name">{e.company.name}</span>,
            agentCell,
            ...(pill ? [pill] : []),
          ],
          href: `/dealers?dealer=${e.company.id}`,
        };
      };
      const agentEntries = preferred.filter((p) => !p.tenure_ended_at);
      const agentRow = (entry: (typeof preferred)[number]) => {
        const owed = owedFor(entry);
        const name =
          entry.company_name ??
          companyById.get(entry.company_id)?.name ??
          "—";
        return {
          ...leadFor(entry.company_id, name),
          cells: [
            <span key="dealer">{name}</span>,
            <span key="agent">{entry.name}</span>,
            <span key="total">
              {owed ? formatMoney(owed.total, owed.currency, true) : "—"}
            </span>,
          ],
          href: `/dealers?dealer=${entry.company_id}`,
        };
      };
      const visitingEntries = agentEntries
        .map((entry) => ({ entry, daysAway: daysAwayFor(entry.next_visit) }))
        .filter(
          (v) => v.daysAway !== null && v.daysAway >= 0 && v.daysAway <= 7,
        );
      const visitingRow = (v: (typeof visitingEntries)[number]) => {
        const owed = owedFor(v.entry);
        const name =
          v.entry.company_name ??
          companyById.get(v.entry.company_id)?.name ??
          "—";
        const day = v.entry.next_visit
          ? dayLabel(
              t as never,
              new Date(`${v.entry.next_visit.slice(0, 10)}T12:00:00`).getDay(),
            )
          : "";
        return {
          ...leadFor(v.entry.company_id, name),
          cells: [
            <span key="dealer">{name}</span>,
            <span key="agent">{v.entry.name}</span>,
            <span key="owed">
              {owed ? formatMoney(owed.total, owed.currency, true) : "—"}
            </span>,
            <span key="weekly">
              {owed?.weekly
                ? formatMoney(owed.weekly, owed.currency, true)
                : "—"}
            </span>,
            <span key="day">{day}</span>,
          ],
          href: `/dealers?dealer=${v.entry.company_id}`,
        };
      };
      if (showTiles && mine.length > 0) {
        data.tabs = [
          {
            id: "all",
            label: line(t, "home.widget.dealerTabAll", "Dealers"),
            count: mine.length,
            rowsVisible: tilesToShow,
            rowsClass: "tv-widget-rows--cols-dealerdir tv-widget-rows--ruled",
            emptyText: line(t, "home.widget.dealerNone", "No dealers yet"),
            rows: enriched.map(dealerRow),
          },
          {
            id: "agents",
            label: line(t, "home.widget.dealerTabAgents", "With agents"),
            count: agentEntries.length,
            rowsVisible: tilesToShow,
            rowsClass: "tv-widget-rows--cols-dealerdir tv-widget-rows--ruled",
            emptyText: line(t, "home.widget.dealerNoAgents", "No dealers with agents yet"),
            rows: agentEntries.map(agentRow),
          },
          {
            id: "visiting",
            label: line(t, "home.widget.dealerTabVisiting", "Visiting this week"),
            count: visitingEntries.length,
            rowsVisible: tilesToShow,
            rowsClass: "tv-widget-rows--cols-visiting tv-widget-rows--ruled",
            emptyText: line(t, "home.widget.dealerNoVisits", "No visits this week"),
            rows: visitingEntries.map(visitingRow),
          },
        ];
      }
      if (showActions) {
        data.actionsEnd = true;
        data.actions = (
          <>
            <Link to="/dealers" className={buttonClasses("ghost", "sm")}>
              {line(t, "nav.dealers", "Dealer directory")}
            </Link>
            <Link to="/dealers/find-agent" className={buttonClasses("primary", "sm")}>
              {line(t, "home.widget.dealerFind", "Find a dealer")}
            </Link>
          </>
        );
      }
      return data;
    },
  };
