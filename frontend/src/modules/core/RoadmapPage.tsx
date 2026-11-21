import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Panel, Spinner } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { RoadmapStageBar } from "./RoadmapStageBar";
import "./roadmap.css";

/**
 * "What's coming" — the operator-published roadmap (audit A15;
 * stage rebuild 2026-11-12). Entries come from Admin → Roadmap
 * in the admins' order; each carries one of the 8 stages and
 * renders with its stepped status bar. The page ships EMPTY
 * and says so plainly until the operator publishes something.
 */

interface RoadmapEntry {
  id: string;
  title: string;
  note: string;
  stage: string;
  sort_order: number;
}

export default function RoadmapPage() {
  const t = useT();
  const [entries, setEntries] = useState<RoadmapEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<RoadmapEntry[]>("/core/roadmap")
      .then(setEntries)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : t("roadmap.loadError")),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="tv-roadmap"
      style={{
        maxWidth: 880,
        margin: "0 auto",
        display: "grid",
        gap: "var(--space-4)",
      }}
    >
      <Panel>
        <h1 style={{ marginTop: 0 }}>{t("roadmap.heading")}</h1>
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          {t("roadmap.intro")}
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        {!entries && !error && <Spinner />}
        {entries && entries.length === 0 && (
          <p>
            {t("roadmap.empty")}{" "}
            <Link to="/help#features" style={{ color: "var(--accent)" }}>
              {t("roadmap.emptyBoards")}
            </Link>
            .
          </p>
        )}
        {entries && entries.length > 0 && (
          <div className="tv-inv-list tv-rm-pub-list">
            {entries.map((entry) => (
              <div key={entry.id} className="tv-rm-pub-row">
                <div>
                  <span className="tv-rm-pub-title">{entry.title}</span>
                  {entry.note && (
                    <p className="tv-rm-pub-note">{entry.note}</p>
                  )}
                </div>
                <RoadmapStageBar stage={entry.stage} />
              </div>
            ))}
          </div>
        )}
        <p
          style={{
            marginTop: "2rem",
            borderTop: "1px solid var(--edge, currentColor)",
            paddingTop: "1rem",
          }}
        >
          <Link to="/" style={{ color: "var(--accent)" }}>
            {t("roadmap.backHome")}
          </Link>
          {"  ·  "}
          <Link to="/help#features" style={{ color: "var(--accent)" }}>
            {t("roadmap.suggest")}
          </Link>
        </p>
      </Panel>
    </div>
  );
}
