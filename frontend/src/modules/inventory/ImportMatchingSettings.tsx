import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Panel, useToast } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import {
  deleteLearnedMapping,
  listLearnedMappings,
  type LearnedMapping,
} from "./importApi";

/**
 * Settings -> Import matching: the importer's remembered answers
 * (smart value matching, 2026-10-19).
 *
 * Every time the Resolve matches step asks about a value and the
 * user answers, the answer is remembered and pre-answers the next
 * import. This is where those memories live: grouped by field,
 * each showing what the file's value becomes — and each deletable,
 * which makes the importer ask again next time. Nothing here is
 * hidden state: the resolve step and the import summary list the
 * same answers whenever they're used.
 */

const FIELD_KEYS: Record<string, DictKey> = {
  dealer_name: "settings.importMatching.fieldDealerName",
  brand: "settings.importMatching.fieldBrand",
  category: "settings.importMatching.fieldCategory",
  tags: "settings.importMatching.fieldTags",
  location: "settings.importMatching.fieldLocation",
};

const FIELD_ORDER = ["dealer_name", "brand", "category", "tags", "location"];

function outcomeLabel(
  mapping: LearnedMapping,
  t: (key: DictKey) => string,
): string {
  if (mapping.action === "unset") return t("settings.importMatching.outcomeUnset");
  if (mapping.action === "create")
    return t("settings.importMatching.outcomeCreate");
  return t("settings.importMatching.outcomeUse").replace(
    "{label}",
    mapping.target_label ?? "",
  );
}

export default function ImportMatchingSettings() {
  const { toast } = useToast();
  const t = useT();
  const [mappings, setMappings] = useState<LearnedMapping[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMappings(await listLearnedMappings());
      setLoadError(null);
    } catch {
      setLoadError(t("settings.importMatching.loadFailed"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete(mapping: LearnedMapping) {
    setDeletingId(mapping.id);
    try {
      await deleteLearnedMapping(mapping.id);
      setMappings((prev) =>
        prev ? prev.filter((row) => row.id !== mapping.id) : prev,
      );
      toast(
        t("settings.importMatching.forgotToast").replace(
          "{value}",
          mapping.raw_value,
        ),
        { title: t("settings.importMatching.forgotTitle"), tone: "success" },
      );
    } catch {
      toast(t("settings.importMatching.forgetFailedToast"), {
        title: t("settings.importMatching.errorTitle"),
        tone: "danger",
      });
    } finally {
      setDeletingId(null);
    }
  }

  const groups = FIELD_ORDER.map((field) => ({
    field,
    rows: (mappings ?? []).filter((row) => row.field === field),
  })).filter((group) => group.rows.length > 0);

  return (
    <Panel>
      <div style={{ display: "grid", gap: "0.9rem" }}>
        <div>
          <h2 style={{ margin: "0 0 0.3rem", fontSize: "1.1rem" }}>
            {t("settings.importMatching.title")}
          </h2>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            {t("settings.importMatching.intro")}
          </p>
        </div>
        {loadError && (
          <Alert tone="danger" title={t("settings.importMatching.loadTitle")}>
            {loadError}
          </Alert>
        )}
        {mappings !== null && mappings.length === 0 && (
          <p style={{ margin: 0 }}>
            {t("settings.importMatching.empty")}
          </p>
        )}
        {groups.map((group, groupIndex) => (
          <div
            key={group.field}
            style={{
              display: "grid",
              gap: "0.4rem",
              // Field section break (owner, 2026-11-12): every
              // field group after the first gets a full extra
              // space above its heading, so one field's answers
              // visibly end before the next field begins.
              marginTop: groupIndex === 0 ? undefined : "var(--space-3)",
            }}
          >
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>
              {FIELD_KEYS[group.field] ? t(FIELD_KEYS[group.field]) : group.field}
            </h3>
            {group.rows.map((mapping) => (
              <div
                key={mapping.id}
                style={{
                  display: "flex",
                  gap: "0.6rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                  borderTop: "1px solid var(--border, #ddd)",
                  paddingTop: "0.45rem",
                }}
              >
                <span>
                  {t("settings.importMatching.whenLead")}{" "}
                  <strong>&ldquo;{mapping.raw_value}&rdquo;</strong>
                  {" → "}
                  {outcomeLabel(mapping, t)}
                </span>
                <Badge tone="neutral">
                  {mapping.action === "map"
                    ? t("settings.importMatching.badgeMatched")
                    : mapping.action === "create"
                      ? t("settings.importMatching.badgeNew")
                      : t("settings.importMatching.badgeUnset")}
                </Badge>
                <span style={{ flex: 1 }} />
                <Button
                  variant="ghost"
                  loading={deletingId === mapping.id}
                  onClick={() => void handleDelete(mapping)}
                >
                  {t("settings.importMatching.forgetBtn")}
                </Button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}
