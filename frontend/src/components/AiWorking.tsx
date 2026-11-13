import { Spinner } from "./Spinner";

/**
 * The site's one "the AI is working" indicator (wizard + inventory
 * fixes pack, 2026-10-25): while any surface waits on an AI call,
 * the user sees motion and a plain line saying what is happening —
 * never dead air. A spinner in the site's accent plus three
 * progressing dots, with the label beside them.
 *
 * Adopt this anywhere an AI wait happens (the drawer lookup takes
 * it in its rework; the catalog QuickAddPanel is the other known
 * AI-wait surface).
 */
export function AiWorking({ label }: { label: string }) {
  return (
    <div className="tv-ai-working" role="status" aria-live="polite">
      <Spinner size="sm" />
      <span>{label}</span>
      <span className="tv-ai-working-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
