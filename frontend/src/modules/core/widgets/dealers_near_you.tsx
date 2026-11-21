import {useState} from "react";
import {Link} from "react-router-dom";
import {
  Button,
  FormField,
  Modal,
  Select,
  TextInput,
} from "../../../components";
import {ArtIcon} from "../../../components/ArtIcon";
import {useT} from "../../../i18n/LocaleContext";
import {getNearYou} from "../../dealers/api";
import {CompanyLogo} from "../../dealers/components/CompanyLogo";
import type {NearYouResult} from "../../dealers/types";
import {optNum} from "../widgetOptions";
import type {
  WidgetRow,
  WidgetData,
  WidgetDef,
} from "./shared";
import {line} from "./shared";

function NearYouFinder({
  initialZip,
  radius: radiusDefault,
}: {
  initialZip: string | null;
  radius: number;
}) {
  const t = useT();
  const [zip, setZip] = useState(initialZip ?? "");
  const [radius, setRadius] = useState(radiusDefault);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<NearYouResult | null>(null);
  const [open, setOpen] = useState(false);

  async function search() {
    const typed = zip.trim();
    if (!/^\d{5}(-\d{4})?$/.test(typed)) {
      setError(t("home.widget.dealersNear.badZip"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const found = await getNearYou(radius, typed);
      setResult(found);
      setOpen(true);
    } catch {
      setError(t("home.widget.dealersNear.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form
        className="tv-widget-entry-form"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <div className="tv-widget-entry-row">
          <FormField
            label={t("home.widget.dealersNear.zipLabel")}
            htmlFor="tw-near-zip"
          >
            <TextInput
              id="tw-near-zip"
              inputSize="sm"
              inputMode="numeric"
              autoComplete="postal-code"
              maxLength={10}
              placeholder="56345"
              value={zip}
              onChange={(e) => {
                setZip(e.target.value);
                setError("");
              }}
            />
          </FormField>
          <FormField label={t("home.opt.near.radius")} htmlFor="tw-near-range">
            <Select
              id="tw-near-range"
              inputSize="sm"
              value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
            >
              {[10, 25, 50, 100].map((miles) => (
                <option key={miles} value={miles}>
                  {t("home.widget.dealersNear.rangeOpt").replace(
                    "{miles}",
                    String(miles),
                  )}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        {error && (
          <p className="tv-widget-entry-error" role="alert">
            {error}
          </p>
        )}
        <div className="tv-widget-entry-row">
          <Button type="submit" size="sm" loading={busy}>
            {t("home.widget.dealersNear.find")}
          </Button>
        </div>
      </form>
      <Modal
        open={open && result !== null}
        onClose={() => setOpen(false)}
        title={
          result
            ? t("home.widget.dealersNear.popupTitle").replace(
                "{zip}",
                result.zip ?? zip.trim(),
              )
            : undefined
        }
      >
        {result === null || busy ? (
          <p>{t("home.widget.dealersNear.searching")}</p>
        ) : result.state === "unknown_zip" ? (
          <p>
            {t("home.widget.dealersNear.popupUnknown").replace(
              "{zip}",
              result.zip ?? zip.trim(),
            )}
          </p>
        ) : result.state === "none_near" || result.results.length === 0 ? (
          <p>
            {t("home.widget.dealersNear.popupNone")
              .replace("{radius}", String(result.radius_miles))
              .replace("{zip}", result.zip ?? zip.trim())}
          </p>
        ) : (
          <div className="tv-near-results">
            {result.results.flatMap((agent) =>
              agent.companies.map((company) => (
                <Link
                  key={`${agent.agent_user_id}-${company.company_id}`}
                  to={`/dealers?dealer=${company.company_id}`}
                  className="tv-near-result"
                  onClick={() => setOpen(false)}
                >
                  <span className="tv-near-dealer">
                    <CompanyLogo
                      company={{
                        name: company.company_name,
                        logo_url: company.logo_url,
                        logo_tile: company.logo_tile,
                      }}
                      width={72}
                      height={40}
                    />
                    <span className="tv-near-result-names">
                      <span>{company.company_name}</span>
                      <span className="tv-near-result-agent">
                        {agent.display_name}
                      </span>
                    </span>
                  </span>
                  <span>
                    {agent.covers_zip
                      ? t("home.widget.dealersNear.covers")
                      : t("dealers.findLocal.away").replace(
                          "{miles}",
                          String(agent.distance_miles),
                        )}
                  </span>
                </Link>
              )),
            )}
          </div>
        )}
      </Modal>
    </>
  );
}

/**
 * The Quick Add box (widget wave 2 build 3): one input, one
 * drop zone — a door into the add wizard, nothing more. A typed
 * name rides location state as the wizard's seed (the wizard
 * seats it in its own name field; see quickAddSeed.ts); a
 * dropped or picked photo rides as the File itself, which the
 * wizard stages as the item's first photo while its lookup
 * step runs photo identification on it — the exact treatment a
 * pick inside the wizard gets. The box validates a photo with
 * the wizard's own photo rules (photoFileError — the staged
 * picker's own words) and says so in place when a file can't
 * ride; the name path and the wizard door stay usable. An
 * empty name simply opens the wizard — a valid door too. The
 * fork (battery or tool) is the wizard's own first question;
 * the box never asks it.
 */

export const dealersNearYouWidget: WidgetDef = {
    icon: <ArtIcon name="dealers" size={24} />,
    tone: "info",
    cta: "open",
    path: "/dealers/find-agent",
    // A NEW widget (widget wave 2, owner approval 2026-11-09):
    // it joins the picker OFF for everyone who already has a
    // Home — nobody's stored layout is rearranged. (It is NOT
    // a module widget in HOME_WIDGET_ORDER — the dealers module
    // already seats its directory widget there; CorePage seats
    // this one as its own block gated on the dealers module,
    // the Quick Reports pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Dealers near you (idea C#1): the directory widget shows
      // dealers you HAVE; this one finds NEW ones — the nearest
      // findable agents to the ZIP in the viewer's own profile
      // postal address, read server-side by /dealers/near-you
      // through the Find local Agent search itself, so the
      // findability bar and the distance math are the page's
      // own. Rows are (agent, company) pairs — the directory's
      // CompanyLogo treatment on the company cell, the agent's
      // name, and the honest distance (0 reads as "covers your
      // ZIP", never a dressed-up 0 mi). No ZIP on file is a
      // plain statement — never a fake list, never a guessed
      // location — and under every state sits the finder
      // (owner, 2026-11-14): a ZIP field, a range, and a "Find
      // an agent near me" button whose answers land in a popup,
      // so the widget works for any ZIP, not only the profile's.
      const settings = ctx?.settings ?? {};
      const rawRadius = settings.radiusMiles;
      const radius =
        typeof rawRadius === "number" &&
        [10, 25, 50, 100].includes(rawRadius)
          ? rawRadius
          : 50;
      const rowsToShow = optNum(settings, "rowsToShow", 4, 2, 6);
      // Edit view: the finder is a live form — while the box is
      // being arranged it describes itself instead (the
      // converter's pattern).
      if (ctx?.editing) {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.blurb",
              "Type any ZIP code, pick a range, and this widget finds the dealer agents near it.",
            ),
          ],
        };
      }
      const near = await getNearYou(radius);
      // The finder (owner, 2026-11-14) rides every state: a
      // member with no ZIP on file — or one searching a ZIP
      // that isn't theirs — types it right here and gets the
      // popup, instead of a box whose only move is a link.
      const finder = (
        <NearYouFinder initialZip={near.zip} radius={radius} />
      );
      if (near.state === "no_location") {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.noLocation",
              "Add a ZIP code to the postal address on your profile, and this widget will show the dealer agents near you.",
            ),
          ],
          actions: finder,
        };
      }
      if (near.state === "unknown_zip") {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.unknownZip",
              "We couldn't find the ZIP code in your profile address ({zip}). Check it in your profile and this widget will try again.",
              { zip: near.zip ?? "" },
            ),
          ],
          actions: finder,
        };
      }
      if (near.state === "none_near" || near.results.length === 0) {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.noneNear",
              "No dealer agents within {radius} miles of {zip} yet. Find a dealer runs a wider search whenever you want one.",
              { radius: String(near.radius_miles), zip: near.zip ?? "" },
            ),
          ],
          actions: finder,
        };
      }
      const rows: WidgetRow[] = [];
      for (const agent of near.results) {
        for (const company of agent.companies) {
          rows.push({
            cells: [
              <span key="dealer" className="tv-near-dealer">
                <CompanyLogo
                  company={{
                    name: company.company_name,
                    logo_url: company.logo_url,
                    logo_tile: company.logo_tile,
                  }}
                  width={72}
                  height={40}
                />
                <span>{company.company_name}</span>
              </span>,
              <span key="agent" className="tv-near-agent">
                {agent.photo_url ? (
                  <img className="tv-near-photo" src={agent.photo_url} alt="" />
                ) : null}
                <span>{agent.display_name}</span>
              </span>,
              agent.covers_zip
                ? line(t, "home.widget.dealersNear.covers", "Covers your ZIP")
                : line(t, "dealers.findLocal.away", "≈ {miles} mi away", {
                    miles: String(agent.distance_miles),
                  }),
            ],
            href: `/dealers?dealer=${company.company_id}`,
          });
        }
      }
      const data: WidgetData = {
        lines: [
          line(t, "home.widget.dealersNear.within", "Dealer agents within {radius} miles of {place}", {
            radius: String(near.radius_miles),
            place: near.point?.display_name ?? near.zip ?? "",
          }),
        ],
        rowsClass: "tv-widget-rows--cols-near",
        rows: rows.slice(0, rowsToShow),
        actions: finder,
      };
      if (ctx?.size === "full") {
        data.header = [
          line(t, "dealers.findLocal.col.companies", "Dealer"),
          line(t, "dealers.roster.col.name", "Agent"),
          line(t, "dealers.findLocal.col.distance", "Distance"),
        ];
      }
      return data;
    },
  };
