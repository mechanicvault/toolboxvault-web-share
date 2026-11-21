import { useState } from "react";

import { Link, useNavigate } from "react-router-dom";
import { Badge, Button, FileUpload, TextInput, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { useT } from "../../../i18n/LocaleContext";
import { api } from "../../../lib/api";
import {
  acceptForKind,
  photoFileError,
} from "../../inventory/components/photoTransfer";
import {
  quickAddSeedState,
  type QuickAddSeed,
} from "../../inventory/quickAddSeed";
import type { WidgetDef } from "./shared";
import { line } from "./shared";

interface QuickRecent {
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  location: string;
  attachments?: { kind: string }[];
}

function QuickAddBox({
  recents = [],
  wide = false,
}: {
  recents?: QuickRecent[];
  wide?: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const openWizard = (seed?: QuickAddSeed) => {
    navigate(
      "/inventory/new",
      seed ? { state: quickAddSeedState(seed) } : undefined,
    );
  };

  const onPhoto = (files: File[]) => {
    const file = files[0];
    if (!file) return;
    const problem = photoFileError(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    openWizard({ photo: file });
  };

  const standing = (item: QuickRecent) =>
    !(item.attachments ?? []).some((a) => a.kind === "photo")
      ? {
          label: line(t, "home.widget.quickAdd.needsPhoto", "Needs photo"),
          tone: "warning" as const,
        }
      : !item.model && !item.serial_number
        ? {
            label: line(t, "home.widget.quickAdd.needsSerial", "Needs serial"),
            tone: "warning" as const,
          }
        : {
            label: line(t, "home.widget.quickAdd.complete", "Complete"),
            tone: "success" as const,
          };

  const form = (
    <div className="tv-quickadd">
      <form
        className="tv-quickadd-form"
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = name.trim();
          openWizard(trimmed ? { name: trimmed } : undefined);
        }}
      >
        <TextInput
          inputSize="sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("home.widget.quickAdd.namePlaceholder")}
          aria-label={t("home.widget.quickAdd.nameLabel")}
        />
        <Button type="submit" size="sm">
          {t("home.widget.quickAdd.go")}
        </Button>
      </form>
      <FileUpload
        onFiles={onPhoto}
        accept={acceptForKind("photo")}
        multiple={false}
        label={t("home.widget.quickAdd.dropLabel")}
        hint={t("home.widget.quickAdd.dropHint")}
      />
      {error && (
        <p className="tv-widget-entry-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );

  return (
    <div className="tv-quickadd-root">
      <p className="tv-widget-line">
        {t("home.widget.quickAdd.subLine")}
      </p>
      {wide && recents.length > 0 ? (
        <div className="tv-quickadd-split">
          {form}
          <div>
            <p className="tv-widget-strip-label">
              {t("home.widget.quickAdd.justAdded")}
            </p>
            <div className="tv-widget-rows tv-widget-rows--reports">
              {recents.map((item) => {
                const st = standing(item);
                const sub = [
                  [item.brand, item.model].filter(Boolean).join(" "),
                  item.location,
                ]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <Link
                    key={item.id}
                    to={`/inventory/${item.id}`}
                    className="tv-widget-row"
                  >
                    <span className="tv-widget-cellstack">
                      <span>{item.name}</span>
                      {sub && (
                        <span className="tv-widget-cellsub">{sub}</span>
                      )}
                    </span>
                    <Badge tone={st.tone}>{st.label}</Badge>
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        form
      )}
      <div className="tv-widget-actions">
        <Link to="/inventory/new" className={buttonClasses("ghost", "sm")}>
          {t("home.widget.quickAdd.openWizard")}
        </Link>
      </div>
    </div>
  );
}

/** The Account & Plan widget's read: GET /billing/me's payload
 *  (the billing module's EntitlementView — the same shape
 *  Settings → Plan & billing renders from). */

export const quickAddWidget: WidgetDef = {
    icon: <ArtIcon name="search" size={24} />,
    tone: "info",
    cta: "open",
    path: "/inventory/new",
    // A NEW widget (widget wave 2 build 3, owner approval
    // 2026-11-09): OFF by default like Builds 1–2 beside it —
    // nobody's stored Home is rearranged; Edit view's Add menu
    // and the widget gallery offers it. (It is NOT a
    // module widget in HOME_WIDGET_ORDER — the inventory module
    // already seats its own widget there; CorePage seats this
    // one as its own block gated on the inventory module, the
    // Builds 1–2 pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Quick Add (idea C#3): the site's AI tool entry as a
      // Home door — one box: type a tool name, or drop a photo,
      // and the add wizard opens with the seed already in it.
      // The body rides the actions slot (the converter's seat),
      // above the whole-box cover, so its field, button and
      // drop zone take real clicks and drops. In Edit view the
      // frame hides the actions slot — the load then answers
      // with the explainer as a line, so the box describes
      // itself while it is arranged (the converter's pattern).
      if (ctx?.editing) {
        return {
          lines: [
            line(
              t,
              "home.widget.quickAdd.explainer",
              "Start the add wizard from here — type a tool name, or drop a photo and the wizard identifies it.",
            ),
          ],
        };
      }
      // Sample redesign (2026-11-15): the newest items ride
      // beside the box as JUST ADDED with their standing —
      // the same search read the Inventory widget uses,
      // typed for the facts the pills need (soft-fail: the
      // box alone is still the widget).
      const recents = await api<QuickRecent[]>(
        "/inventory/search?limit=3",
      ).catch(() => [] as QuickRecent[]);
      return {
        lines: [],
        actions: (
          <QuickAddBox recents={recents} wide={ctx?.size === "full"} />
        ),
      };
    },
  };
