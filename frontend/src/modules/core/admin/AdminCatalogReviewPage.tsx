import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Button,
  EmptyState,
  Panel,
  Spinner,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Catalog review (lookup rebuild Phase 5): the
 * library's trust queue. Candidate entries wait here for
 * corroboration or an admin's approval; conflicted entries
 * (two verified runs disagreed about a set's contents) wait
 * for an admin to pick which list is true. Approving marks
 * an entry verified — it can then complete lookups on its
 * own; rejecting quarantines it so it never answers again.
 */

interface ReviewPiece {
  name: string;
  model: string | null;
  msrp: number | null;
  image_url: string | null;
}

interface ReviewEntry {
  id: string;
  brand: string;
  model: string;
  status: string;
  confirmations: number;
  source_kind?: string;
  fields: Record<string, string | number | null>;
  pieces: ReviewPiece[];
  piece_count: number | null;
}

export default function AdminCatalogReviewPage() {
  const [entries, setEntries] = useState<ReviewEntry[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<{ entries: ReviewEntry[] }>("/catalog/admin/review");
      setEntries(data.entries);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the review queue.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (entry: ReviewEntry, action: string, body?: object) => {
    setBusyId(entry.id);
    try {
      await api(`/catalog/admin/review/${entry.id}/${action}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That action didn't go through.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <RequireAuth>
      <AdminShell>
        <Panel title="Catalog review">
          {error && <Alert tone="danger">{error}</Alert>}
          {entries === null && !error && <Spinner />}
          {entries !== null && entries.length === 0 && (
            <EmptyState
              title="Nothing waiting"
              description="No candidate or conflicted catalog entries need a decision right now."
            />
          )}
          {entries?.map((entry) => (
            <section key={entry.id} className="tv-admin-review-entry">
              <header className="tv-admin-review-head">
                <strong>
                  {entry.brand} {entry.model}
                </strong>
                <span>Status: {entry.status}</span>
                <span>Confirmations: {entry.confirmations}</span>
                <span>
                  Pieces: {entry.pieces.length}
                  {entry.piece_count ? ` of ${entry.piece_count} stated` : ""}
                </span>
              </header>
              {entry.fields.name && <p>{String(entry.fields.name)}</p>}
              {entry.pieces.length > 0 && (
                <table className="tv-admin-review-pieces">
                  <thead>
                    <tr>
                      <th>Piece</th>
                      <th>Part #</th>
                      <th>Price</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entry.pieces.map((piece, index) => (
                      <tr key={`${piece.model ?? "piece"}-${index}`}>
                        <td>{piece.name}</td>
                        <td>{piece.model ?? "—"}</td>
                        <td>{piece.msrp != null ? `$${piece.msrp.toFixed(2)}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="tv-admin-review-actions">
                {entry.status === "conflict" ? (
                  <>
                    <Button
                      loading={busyId === entry.id}
                      onClick={() => void act(entry, "resolve", { keep: "stored" })}
                    >
                      Keep the stored list
                    </Button>
                    <Button
                      loading={busyId === entry.id}
                      onClick={() => void act(entry, "resolve", { keep: "challenger" })}
                    >
                      Use the challenger list
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      loading={busyId === entry.id}
                      onClick={() => void act(entry, "approve")}
                    >
                      Approve as verified
                    </Button>
                    <Button
                      loading={busyId === entry.id}
                      onClick={() => void act(entry, "reject")}
                    >
                      Reject (quarantine)
                    </Button>
                  </>
                )}
              </div>
            </section>
          ))}
        </Panel>
      </AdminShell>
    </RequireAuth>
  );
}
