import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { api } from "../../../lib/api";
import { activeLocale, formatDate } from "../../../lib/format";
import { optBool } from "../widgetOptions";
import { ACCOUNT_TYPE_OPTIONS } from "../accountTypes";
import type { WidgetRow, WidgetStat, WidgetDef } from "./shared";
import { count, line } from "./shared";

interface AccountPlanView {
  plan_name: string;
  source: string;
  is_paid: boolean;
  item_limit: number | null;
  items_total: number;
  enforcement_enabled: boolean;
  subscription: {
    status: string;
    current_period_end: string | null;
    grace_until: string | null;
    trial_end: string | null;
  } | null;
}

/** Plain-language names for the entitlement sources the widget
 *  names in a line. A source outside this map gets NO line —
 *  the widget never prints a raw enum value. Mirrors the source
 *  vocabulary of billing/entitlements.resolve_entitlement. */
const ACCOUNT_PLAN_SOURCES: Record<string, { key: string; fallback: string }> = {
  subscription: {
    key: "home.widget.accountPlan.source.subscription",
    fallback: "Paid subscription",
  },
  subscription_grace: {
    key: "home.widget.accountPlan.source.subscriptionGrace",
    fallback: "Subscription — in its grace period",
  },
  trial: {
    key: "home.widget.accountPlan.source.trial",
    fallback: "Free trial",
  },
  lifetime: {
    key: "home.widget.accountPlan.source.lifetime",
    fallback: "Lifetime access",
  },
  referral: {
    key: "home.widget.accountPlan.source.referral",
    fallback: "Referral reward",
  },
  redeem_code: {
    key: "home.widget.accountPlan.source.redeem",
    fallback: "Redeem code",
  },
  admin: {
    key: "home.widget.accountPlan.source.admin",
    fallback: "Granted by Toolbox Vault",
  },
};

/** The renewal-class date the widget may show, if any — ONLY a
 *  date the subscription record itself carries: a trial's end,
 *  a grace window's end, or a paid subscription's period end
 *  (\"Renews\", or \"Ends\" when the subscription is canceled and
 *  will not renew). An account with no such record gets no date
 *  tile at all — honest absence, never a placeholder. */
function accountPlanRenewal(
  view: AccountPlanView,
): { key: string; fallback: string; iso: string } | null {
  const sub = view.subscription;
  if (!sub || !view.is_paid) return null;
  if (view.source === "trial" && sub.trial_end) {
    return {
      key: "home.widget.accountPlan.trialEnds",
      fallback: "Trial ends",
      iso: sub.trial_end,
    };
  }
  if (view.source === "subscription_grace" && sub.grace_until) {
    return {
      key: "home.widget.accountPlan.accessThrough",
      fallback: "Access through",
      iso: sub.grace_until,
    };
  }
  if (view.source === "subscription" && sub.current_period_end) {
    return sub.status === "canceled"
      ? {
          key: "home.widget.accountPlan.ends",
          fallback: "Ends",
          iso: sub.current_period_end,
        }
      : {
          key: "home.widget.accountPlan.renews",
          fallback: "Renews",
          iso: sub.current_period_end,
        };
  }
  return null;
}

/** Borrowing's Send reminder (sample redesign, 2026-11-15):
 *  the overdue banner's action — the SAME nudge the Borrowing
 *  page composes. A linked borrower gets it in-app; an
 *  unlinked one gets the ready-to-send text with the page's
 *  own copy / call / text / email doors. */

export const accountPlanWidget: WidgetDef = {
    icon: <ArtIcon name="money" size={24} />,
    tone: "info",
    cta: "open",
    path: "/settings/billing",
    // A NEW widget (widget wave 2 build 4, owner approval
    // 2026-11-09/10): OFF by default like Builds 1–3 beside it —
    // nobody's stored Home is rearranged; Edit view's Add menu
    // and the widget gallery offers it. CORE reach,
    // not a feature module: the widget reads the account's own
    // standing from /billing/me — always-on billing
    // infrastructure, deliberately ungated by modules (see
    // billing/routes.py) — plus /core/me for the tier, so
    // CorePage seats it for EVERY seat, the downloads rung
    // included: their plan IS the downloads level.
    defaultOff: true,
    load: async (t, ctx) => {
      // Account & Plan (idea C#4): the plan the account pages
      // themselves present (GET /billing/me is the exact read
      // Settings → Plan & billing renders — plan name, the
      // limit's OWN item count, the subscription record), the
      // tier from /core/me. Nothing is recomputed here: the
      // count is entitlements.asset_count, the same number the
      // free-tier limit enforces against, and a date shows only
      // when the subscription record itself carries one.
      //
      // Custom-widget aspect gates (Lane 2): every stat, note
      // line and button carries its own switch, all defaulting
      // ON — absence is today's widget, byte for byte; a
      // custom box picks the slices it wants.
      const settings = ctx?.settings ?? {};
      const showPlan = optBool(settings, "showPlan", true);
      const showAccount = optBool(settings, "showAccount", true);
      const showItems = optBool(settings, "showItems", true);
      const showRenewal = optBool(settings, "showRenewal", true);
      const showSource = optBool(settings, "showSource", true);
      const showManage = optBool(settings, "showManage", true);
      const showAccountBtn = optBool(settings, "showAccountBtn", true);
      const [view, me] = await Promise.all([
        api<AccountPlanView>("/billing/me"),
        api<{
          tier: string;
          beta_tester: boolean;
          account_number: string;
          account_types: string[];
          created_at: string;
        }>("/core/me"),
      ]);
      // Sample redesign (2026-11-15): the account number as
      // the sub-line, three stat tiles (Plan / Items / Member
      // since — the items value turns accent when the count
      // passes the limit), then PLAN DETAILS fact rows with
      // their pills, a Billing row carrying its own Manage
      // button, and the footer pair.
      const stats: WidgetStat[] = [];
      const lines: string[] = [];
      const rung = me.tier === "downloads";
      if (showAccount) {
        lines.push(
          line(t, "home.widget.accountPlan.accountLine", "Account {number}", {
            number: me.account_number,
          }),
        );
      }
      const memberSince = new Intl.DateTimeFormat(activeLocale(), {
        month: "short",
        year: "numeric",
      }).format(new Date(me.created_at));
      const typeLabel = me.account_types
        .map(
          (tp) =>
            ACCOUNT_TYPE_OPTIONS.find((o) => o.value === tp)?.label ?? tp,
        )
        .join(" · ");
      const factRows: WidgetRow[] = [];
      if (typeLabel) {
        factRows.push({
          cells: [
            line(t, "home.widget.accountPlan.factType", "Account type"),
            typeLabel,
          ],
        });
      }
      if (rung) {
        if (showPlan) {
          stats.push({
            label: line(t, "home.widget.accountPlan.statPlan", "Plan"),
            value: line(
              t,
              "home.widget.accountPlan.levelDownloads",
              "Downloads level",
            ),
          });
        }
        stats.push({
          label: line(t, "home.widget.accountPlan.statMemberSince", "Member since"),
          value: memberSince,
        });
      } else {
        if (showPlan) {
          stats.push({
            label: line(t, "home.widget.accountPlan.statPlan", "Plan"),
            value: view.plan_name,
          });
        }
        if (showItems) {
          if (view.item_limit === null) {
            stats.push({
              label: line(t, "home.widget.accountPlan.statItems", "Items"),
              value: count(view.items_total),
            });
          } else {
            stats.push({
              label: line(t, "home.widget.accountPlan.statItems", "Items"),
              value: line(
                t,
                "home.widget.accountPlan.itemsOfSpaced",
                "{count} / {limit}",
                {
                  count: count(view.items_total),
                  limit: count(view.item_limit),
                },
              ),
              tone:
                view.items_total > view.item_limit ? "warn" : undefined,
            });
          }
        }
        stats.push({
          label: line(t, "home.widget.accountPlan.statMemberSince", "Member since"),
          value: memberSince,
        });
        if (showSource && me.beta_tester) {
          factRows.push({
            cells: [
              line(t, "home.widget.accountPlan.factBeta", "Beta tester"),
              line(t, "home.widget.accountPlan.yes", "Yes"),
              <Badge key="beta" tone="accent">
                {line(t, "home.widget.accountPlan.betaPill", "BETA")}
              </Badge>,
            ],
          });
        }
        if (showItems) {
          const over =
            view.item_limit !== null && view.items_total > view.item_limit;
          factRows.push({
            cells: [
              line(t, "home.widget.accountPlan.factLimit", "Item limit"),
              view.item_limit === null
                ? line(t, "home.widget.accountPlan.noLimitShort", "No limit")
                : line(
                    t,
                    "home.widget.accountPlan.limitValue",
                    "{limit}{enforcement}",
                    {
                      limit: count(view.item_limit),
                      enforcement: view.enforcement_enabled
                        ? ""
                        : line(
                            t,
                            "home.widget.accountPlan.limitOffSuffix",
                            " · enforcement off",
                          ),
                    },
                  ),
              ...(over
                ? [
                    <Badge key="over" tone="warning">
                      {line(t, "home.widget.accountPlan.overPill", "OVER LIMIT")}
                    </Badge>,
                  ]
                : []),
            ],
          });
        }
        const renewal = accountPlanRenewal(view);
        if (showRenewal && renewal) {
          factRows.push({
            cells: [
              line(t, renewal.key, renewal.fallback),
              formatDate(renewal.iso),
            ],
          });
        }
        factRows.push({
          cells: [
            line(t, "home.widget.accountPlan.factSubscription", "Subscription"),
            view.subscription
              ? view.subscription.status
              : line(t, "home.widget.accountPlan.subNone", "None"),
          ],
        });
        if (showSource) {
          const source = ACCOUNT_PLAN_SOURCES[view.source];
          if (source) {
            lines.push(line(t, source.key, source.fallback));
          }
        }
      }
      // The Billing row: its standing plus its own Manage
      // button, as the sample draws it.
      if (!rung) {
        factRows.push({
          cells: [
            line(t, "home.widget.accountPlan.factBilling", "Billing"),
            view.subscription
              ? line(t, "home.widget.accountPlan.billingActive", "Subscription on file")
              : line(t, "home.widget.accountPlan.billingNone", "No subscription on file"),
            showManage ? (
              ctx?.editing ? (
                <span key="manage" className={buttonClasses("ghost", "sm")}>
                  {line(t, "home.widget.accountPlan.manageShort", "Manage")}
                </span>
              ) : (
                <Link
                  key="manage"
                  to="/settings/billing"
                  className={buttonClasses("ghost", "sm")}
                >
                  {line(t, "home.widget.accountPlan.manageShort", "Manage")}
                </Link>
              )
            ) : (
              ""
            ),
          ],
        });
      }
      const buttons: ReactNode[] = [];
      if (rung) {
        if (showAccountBtn) {
          buttons.push(
            <Link
              key="account"
              to="/settings/profile"
              className={buttonClasses("primary", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.accountSettings",
                "Account settings",
              )}
            </Link>,
          );
        }
      } else {
        if (showAccountBtn) {
          buttons.push(
            <Link
              key="account"
              to="/settings/profile"
              className={buttonClasses("ghost", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.accountSettings",
                "Account settings",
              )}
            </Link>,
          );
        }
        if (showManage) {
          buttons.push(
            <Link
              key="manage"
              to="/settings/billing"
              className={buttonClasses("primary", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.manage",
                "Manage subscription",
              )}
            </Link>,
          );
        }
      }
      return {
        lines,
        stats,
        groups:
          factRows.length > 0
            ? [
                {
                  label: line(
                    t,
                    "home.widget.accountPlan.detailsLabel",
                    "Plan details",
                  ),
                  rows: factRows,
                  rowsClass:
                    "tv-widget-rows--cols-facts tv-widget-rows--ruled",
                },
              ]
            : undefined,
        actionsEnd: true,
        actions: buttons.length > 0 ? <>{buttons}</> : undefined,
      };
    },
  };
