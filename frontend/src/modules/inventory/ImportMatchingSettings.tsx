import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Panel, useToast } from "../../components";
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

const FIELD_LABELS: Record<string, string> = {
  dealer_name: "Dealers",
  brand: "Brands",
  category: "Categories",
  tags: "Tags",
  location: "Locations",
};

const FIELD_ORDER = ["dealer_name", "brand", "category", "tags", "location"];

function outcomeLabel(mapping: LearnedMapping): string {
  if (mapping.action === "unset") return "leave it unset";
  if (mapping.action === "create") return "add it as a new value";
  return `use "${mapping.target_label}"`;
}

export default function ImportMatchingSettings() {
  const { toast } = useToast();
  const [mappings, setMappings] = useState<LearnedMapping[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMappings(await listLearnedMappings());
      setLoadError(null);
    } catch {
      setLoadError("Your remembered answers couldn't be loaded. Try again.");
    }
  }, []);

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
        `Forgot the answer for "${mapping.raw_value}" — the importer will ask again next time it shows up.`,
        { title: "Answer forgotten", tone: "success" },
      );
    } catch {
      toast("That answer couldn't be forgotten. Try again.", {
        title: "Something went wrong",
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
            Import matching
          </h2>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            When you import a spreadsheet, the Resolve matches step asks about
            values that look similar to ones you already have — and remembers
            your answers here, so the next import is pre-answered. Forgetting
            an answer makes the importer ask again.
          </p>
        </div>
        {loadError && (
          <Alert tone="danger" title="Couldn't load">
            {loadError}
          </Alert>
        )}
        {mappings !== null && mappings.length === 0 && (
          <p style={{ margin: 0 }}>
            Nothing remembered yet — answers you give while importing will
            appear here.
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
              {FIELD_LABELS[group.field] ?? group.field}
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
                  When the file says <strong>&ldquo;{mapping.raw_value}&rdquo;</strong>
                  {" → "}
                  {outcomeLabel(mapping)}
                </span>
                <Badge tone="neutral">
                  {mapping.action === "map"
                    ? "Matched"
                    : mapping.action === "create"
                      ? "New value"
                      : "Left unset"}
                </Badge>
                <span style={{ flex: 1 }} />
                <Button
                  variant="ghost"
                  loading={deletingId === mapping.id}
                  onClick={() => void handleDelete(mapping)}
                >
                  Forget this answer
                </Button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}
