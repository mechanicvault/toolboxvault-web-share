import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Panel, Spinner } from "../../components";
import { api, ApiError } from "../../lib/api";

/**
 * "What's coming" — the operator-published roadmap (audit A15).
 * Entries come from Admin → Roadmap; the page ships EMPTY and
 * says so plainly until the operator publishes something.
 */

interface RoadmapEntry {
  id: string;
  title: string;
  note: string;
  status: string;
  sort_order: number;
}

const GROUPS: { status: string; heading: string }[] = [
  { status: "in_progress", heading: "In progress" },
  { status: "planned", heading: "Planned" },
  { status: "shipped", heading: "Shipped" },
];

export default function RoadmapPage() {
  const [entries, setEntries] = useState<RoadmapEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<RoadmapEntry[]>("/core/roadmap")
      .then(setEntries)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load the roadmap."),
      );
  }, []);

  return (
    <div className="tv-roadmap" style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "var(--space-4)" }}>
      <Panel>
        <h1 style={{ marginTop: 0 }}>What&apos;s coming</h1>
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          What the Toolbox Vault team is working on next — published by
          the operator, updated as plans firm up. Nothing here is a
          promise or a date.
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        {!entries && !error && <Spinner />}
        {entries && entries.length === 0 && (
          <p>
            Nothing is published yet. When the operator posts what&apos;s
            coming, it shows up here. In the meantime, ideas and bug
            reports live on the{" "}
            <Link to="/feedback/features" style={{ color: "var(--accent)" }}>
              feedback boards
            </Link>
            .
          </p>
        )}
        {entries &&
          GROUPS.map((group) => {
            const rows = entries.filter((e) => e.status === group.status);
            if (rows.length === 0) return null;
            return (
              <section key={group.status} style={{ marginTop: "1.6rem" }}>
                <h2 style={{ fontSize: "1.15rem", marginBottom: "0.4rem" }}>
                  {group.heading}
                </h2>
                <div style={{ display: "grid", gap: "0.7rem" }}>
                  {rows.map((entry) => (
                    <div
                      key={entry.id}
                      className="tv-roadmap-entry"
                      style={{
                        border: "1px solid var(--edge, currentColor)",
                        borderRadius: "0.5rem",
                        padding: "0.8rem 1rem",
                      }}
                    >
                      <strong>{entry.title}</strong>
                      {entry.note && (
                        <p style={{ margin: "0.3rem 0 0", color: "var(--text-muted)" }}>
                          {entry.note}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            );
          })}
        <p
          style={{
            marginTop: "2rem",
            borderTop: "1px solid var(--edge, currentColor)",
            paddingTop: "1rem",
          }}
        >
          <Link to="/" style={{ color: "var(--accent)" }}>
            ← Back to home
          </Link>
          {"  ·  "}
          <Link to="/feedback/features" style={{ color: "var(--accent)" }}>
            Suggest a feature
          </Link>
        </p>
      </Panel>
    </div>
  );
}
