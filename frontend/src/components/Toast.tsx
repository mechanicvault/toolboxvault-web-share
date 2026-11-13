import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface ToastOptions {
  title?: string;
  tone?: ToastTone;
  /** Milliseconds before auto-dismiss. Default 5000. */
  duration?: number;
  /** Optional action (F2-19): a button rendered inside the toast,
   *  e.g. an Undo. Clicking it runs the callback and dismisses. */
  action?: { label: string; onAction: () => void };
}

interface ToastItem extends Required<Pick<ToastOptions, "tone" | "duration">> {
  id: number;
  title?: string;
  message: ReactNode;
  action?: ToastOptions["action"];
}

interface ToastContextValue {
  toast: (message: ReactNode, options?: ToastOptions) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * Toast system: mount <ToastProvider> once (App root), then call
 * useToast().toast("Saved") anywhere. Toasts announce via aria-live.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  /* F2-19: timers live in a map so hover/focus can PAUSE a toast's
   * countdown and resume it on leave/blur; the cap never silently
   * evicts a still-live danger/warning toast (oldest info/success
   * evicts first; if every toast is danger/warning, the stack may
   * grow past the soft cap rather than destroy an unread warning). */
  const timers = useRef<Map<number, { handle: number; deadline: number; remaining: number }>>(new Map());

  const clearTimer = useCallback((id: number) => {
    const entry = timers.current.get(id);
    if (entry) window.clearTimeout(entry.handle);
    timers.current.delete(id);
  }, []);

  const dismiss = useCallback((id: number) => {
    clearTimer(id);
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, [clearTimer]);

  const armTimer = useCallback((id: number, ms: number) => {
    clearTimer(id);
    if (ms <= 0) return;
    const handle = window.setTimeout(() => dismiss(id), ms);
    timers.current.set(id, { handle, deadline: Date.now() + ms, remaining: ms });
  }, [clearTimer, dismiss]);

  const pauseTimer = useCallback((id: number) => {
    const entry = timers.current.get(id);
    if (!entry) return;
    window.clearTimeout(entry.handle);
    entry.remaining = Math.max(0, entry.deadline - Date.now());
  }, []);

  const resumeTimer = useCallback((id: number) => {
    const entry = timers.current.get(id);
    if (!entry) return;
    if (entry.remaining <= 0) { dismiss(id); return; }
    const handle = window.setTimeout(() => dismiss(id), entry.remaining);
    entry.handle = handle;
    entry.deadline = Date.now() + entry.remaining;
  }, [dismiss]);

  const toast = useCallback(
    (message: ReactNode, options?: ToastOptions) => {
      const id = nextId.current++;
      const item: ToastItem = {
        id,
        message,
        title: options?.title,
        tone: options?.tone ?? "info",
        duration: options?.duration ?? 5000,
        action: options?.action,
      };
      setToasts((prev) => {
        if (prev.length < 5) return [...prev, item];
        const evictIdx = prev.findIndex((t) => t.tone === "info" || t.tone === "success");
        if (evictIdx === -1) return [...prev, item];
        const evicted = prev[evictIdx]!;
        clearTimer(evicted.id);
        return [...prev.filter((t) => t.id !== evicted.id), item];
      });
      if (item.duration > 0) armTimer(id, item.duration);
    },
    [armTimer, clearTimer],
  );

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="tv-toast-viewport" aria-live="polite" aria-label="Notifications">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`tv-toast tv-toast--${t.tone}`}
            role="status"
            onMouseEnter={() => pauseTimer(t.id)}
            onMouseLeave={() => resumeTimer(t.id)}
            onFocus={() => pauseTimer(t.id)}
            onBlur={() => resumeTimer(t.id)}
          >
            <div className="tv-toast-body">
              {t.title && <div className="tv-toast-title">{t.title}</div>}
              {t.message}
            </div>
            {t.action && (
              <button
                type="button"
                className="tv-toast-action"
                onClick={() => { t.action?.onAction(); dismiss(t.id); }}
              >
                {t.action.label}
              </button>
            )}
            <button
              type="button"
              className="tv-alert-close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
