import { Component, type ErrorInfo, type ReactNode } from "react";
import { isChunkLoadError, reloadOnce } from "../lib/chunkRecovery";
import { Button } from "./Button";
import { Panel } from "./Panel";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Top-level crash net. Without it, ANY render throw (the classic
 * case: a lazily loaded page chunk that no longer exists after a
 * deploy) unmounted the whole app to a bare white page — the
 * owner's "the website just goes blank" report. Now:
 *  - chunk-load failures trigger the guarded one-time reload
 *    (see lib/chunkRecovery) to pick up the fresh build;
 *  - anything else lands on this themed recovery panel with a
 *    working Reload button instead of a white void.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    if (isChunkLoadError(error)) {
      // Reloading to the fresh build; if the guard says we already
      // reloaded moments ago, the fallback below stays on screen.
      reloadOnce();
    }
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const chunkFailure = isChunkLoadError(error);
    return (
      <div className="tv-auth-shell">
        <Panel title="Something went wrong" className="tv-auth-panel">
          <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
            {chunkFailure
              ? "The site was updated while this page was open, and a piece of the old version couldn't load. Reloading usually fixes it."
              : "This page hit a snag and couldn't finish loading. Reloading usually fixes it — your data is saved on the server, not in this tab."}
          </p>
          <Button onClick={() => window.location.reload()}>
            Reload the page
          </Button>
          <p style={{ marginTop: "1rem", marginBottom: 0 }}>
            <a href="/" style={{ color: "var(--accent)", fontSize: "0.9rem" }}>
              ← Back to home
            </a>
          </p>
        </Panel>
      </div>
    );
  }
}
