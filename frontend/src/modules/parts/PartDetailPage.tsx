import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Modal,
  Panel,
  Spinner,
  useToast,
  LinkButton,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { usePageCrumbs } from "../../lib/navTrail";
import { formatMoney } from "../../lib/money";
import { RequireAuth } from "../core";
import type { FieldDefinition } from "../inventory/types";
import { customValueText } from "../inventory/format";
import { PhotoUploader } from "../inventory/components/PhotoUploader";
import { convertToTool, deletePart, getPart, updatePart } from "./api";
import { levelLabel, type Part } from "./types";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "150px minmax(0, 1fr)",
        gap: "0.5rem",
      }}
    >
      <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
      <dd style={{ margin: 0, minWidth: 0, overflowWrap: "anywhere" }}>
        {value || "—"}
      </dd>
    </div>
  );
}

/**
 * Part detail: every recorded field (core + the owner's custom
 * fields), the location path, photos, and the one-way "Add to
 * Asset Inventory as a tool" copy. The part always remains on the
 * shelf; conversion stamps it with the tool it was copied into.
 */
function PartDetailContent() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [part, setPart] = useState<Part | null>(null);
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [error, setError] = useState("");
  const [converting, setConverting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    if (!id) return;
    getPart(id)
      .then(setPart)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load this part."),
      );
  }, [id]);

  useEffect(() => {
    refresh();
    api<FieldDefinition[]>("/inventory/field-definitions?item_type=part")
      .then(setDefs)
      .catch(() => setDefs([]));
  }, [refresh]);

  // The link tree lives in the shell bar, right of the back /
  // forward arrows (owner ruling 2026-11-03) — registered here,
  // never rendered in this page's own header.
  usePageCrumbs([
    { label: "My Parts", to: "/parts" },
    { label: part?.title ?? "Part" },
  ]);

  async function onConvert() {
    if (!id) return;
    setConverting(true);
    setError("");
    try {
      const result = await convertToTool(id);
      setPart(result.part);
      toast(
        <>
          Copied into Inventory as a tool.{" "}
          <Link to={`/inventory/${result.tool_id}`}>Open the tool</Link>
        </>,
        { title: "In inventory", tone: "success" },
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't copy this part into inventory.",
      );
    } finally {
      setConverting(false);
    }
  }

  async function onVisibility(visibility: "public" | "private") {
    if (!id) return;
    setError("");
    try {
      const updated = await updatePart(id, { visibility });
      setPart(updated);
      toast(
        visibility === "public"
          ? "Listed in Community Parts — members can find it and message you."
          : "Unpublished — this part is private again.",
        { title: visibility === "public" ? "Published" : "Unpublished", tone: "success" },
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't change the visibility.",
      );
    }
  }

  async function onDelete() {
    if (!id) return;
    setDeleting(true);
    try {
      await deletePart(id);
      toast("Part deleted.", { title: "Deleted", tone: "success" });
      navigate("/parts");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete the part.");
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  if (error && !part) {
    return (
      <div style={{ display: "grid", gap: "1rem" }}>
        <Alert tone="danger">{error}</Alert>
        <EmptyState
          title="Part not found"
          description="It may have been deleted, or it belongs to someone else."
          action={
            <LinkButton to="/parts">Back to My Parts</LinkButton>
          }
        />
      </div>
    );
  }
  if (!part) return <Spinner />;

  const customRows = defs
    .filter((d) => part.custom_data[d.id] !== undefined && part.custom_data[d.id] !== null)
    .map((d) => ({
      label: d.label,
      value: customValueText(part.custom_data[d.id], d.field_type),
    }));

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "960px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <h1 style={{ margin: 0, overflowWrap: "anywhere" }}>
          {part.title}{" "}
          {part.quantity > 1 && <Badge tone="neutral">×{part.quantity}</Badge>}{" "}
          {part.converted_tool_id && <Badge tone="success">In inventory</Badge>}{" "}
          {part.is_public ? (
            <Badge tone="accent">Public in Community Parts</Badge>
          ) : (
            <Badge tone="neutral">Private</Badge>
          )}
        </h1>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <LinkButton to={`/parts/${part.id}/edit`} variant="secondary">Edit</LinkButton>
          <Button type="button" variant="danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </Button>
        </div>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}

      <Panel title="Details">
        <dl style={{ display: "grid", gap: "0.55rem", margin: 0 }}>
          <Row label="Quantity" value={String(part.quantity)} />
          <Row label="Condition" value={part.condition} />
          <Row
            label="Location"
            value={
              part.location
                ? `${part.location.path} (${levelLabel(part.location.level)})`
                : "Unfiled"
            }
          />
          {part.category && <Row label="Category" value={part.category} />}
          {(part.year || part.make || part.model || part.engine) && (
            <Row
              label="Fits"
              value={[part.year, part.make, part.model, part.engine]
                .filter((v) => v !== null && v !== "")
                .join(" · ")}
            />
          )}
          {part.asking_price !== null && part.asking_price !== "" && (
            <Row label="Asking price" value={formatMoney(part.asking_price)} />
          )}
          {customRows.map((row) => (
            <Row key={row.label} label={row.label} value={row.value} />
          ))}
          <Row label="Notes" value={part.notes} />
        </dl>
      </Panel>

      <Panel title="Community Parts">
        <div style={{ display: "grid", gap: "0.7rem" }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            {part.is_public
              ? "This part is listed in Community Parts — other members can find it and message you about it. Your storage location and notes are never shown."
              : part.visibility === "public"
                ? "This part is set to public, but the pool itself is switched off right now, so it isn't listed."
                : "This part is private — only you can see it. Publish it to list it in Community Parts, where members search by year, make, model and engine."}
          </p>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            {part.visibility === "public" ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() => void onVisibility("private")}
              >
                Unpublish
              </Button>
            ) : (
              <Button type="button" onClick={() => void onVisibility("public")}>
                Publish to Community Parts
              </Button>
            )}
            <LinkButton to="/parts/community" variant="secondary">Browse the pool</LinkButton>
          </div>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
            Effective visibility: <strong>{part.visibility}</strong>
            {part.visibility_override
              ? " (this part's own setting)"
              : " (from your pool settings)"}
            . Publishing needs a paid plan once plan enforcement
            switches on at launch.
          </p>
        </div>
      </Panel>

      <Panel title="Photos">
        <div style={{ display: "grid", gap: "0.8rem" }}>
          {part.attachments.length > 0 ? (
            <div
              style={{
                display: "grid",
                gap: "var(--space-3)",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(min(100%, 140px), 1fr))",
              }}
            >
              {part.attachments.map((a) => (
                <a key={a.key} href={a.url} target="_blank" rel="noreferrer">
                  <img
                    src={a.url}
                    alt={a.filename}
                    style={{
                      display: "block",
                      width: "100%",
                      aspectRatio: "1",
                      objectFit: "cover",
                      borderRadius: "var(--radius)",
                      border: "1px solid var(--edge)",
                    }}
                  />
                </a>
              ))}
            </div>
          ) : (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No photos yet — a picture of the part and its label makes it
              much easier to find and identify later.
            </p>
          )}
          <PhotoUploader
            toolId={part.id}
            basePath={`/parts/${part.id}`}
            kind="photo"
            onUploaded={refresh}
          />
        </div>
      </Panel>

      <Panel title="Inventory">
        {part.converted_tool_id ? (
          <div style={{ display: "grid", gap: "0.7rem" }}>
            <p style={{ margin: 0 }}>
              This part was copied into Inventory as a tool. The copy
              is independent now — editing either one never changes the
              other.
            </p>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <LinkButton to={`/inventory/${part.converted_tool_id}`} variant="secondary">Open the tool</LinkButton>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void onConvert()}
                disabled={converting}
              >
                {converting ? "Copying…" : "Copy again as a new tool"}
              </Button>
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: "0.7rem" }}>
            <p style={{ margin: 0 }}>
              Put this spare to work: copy it into Inventory as a
              regular tool — name, quantity, condition and notes carry
              over, along with any of your fields that match (make becomes
              brand, and same-named custom fields keep their values) and
              its photos. The part stays right here on the shelf.
            </p>
            <div>
              <Button
                type="button"
                onClick={() => void onConvert()}
                disabled={converting}
              >
                {converting ? "Copying…" : "Add to Inventory as a tool"}
              </Button>
            </div>
          </div>
        )}
      </Panel>

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={`Delete “${part.title}”?`}
        size="sm"
        footer={
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirmDelete(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void onDelete()}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete part"}
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          The part and its photos are deleted. This doesn't touch any tool
          it was copied into — those live their own life in Inventory.
        </p>
      </Modal>
    </div>
  );
}

export default function PartDetailPage() {
  return (
    <RequireAuth>
      <PartDetailContent />
    </RequireAuth>
  );
}
