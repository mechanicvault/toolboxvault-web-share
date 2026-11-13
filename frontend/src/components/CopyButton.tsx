import { useToast } from "./Toast";

/**
 * One-tap copy for a phone number or address (corporate directory,
 * owner 2026-10-19): writes the text to the clipboard and confirms
 * with the standard "Copied" toast. Falls back to a hidden textarea
 * for contexts where the async clipboard API is unavailable.
 */
export function CopyButton({
  text,
  label = "Copy",
  ariaLabel,
}: {
  /** The exact text placed on the clipboard (an address copies as
   *  its multi-line mailing block). */
  text: string;
  label?: string;
  ariaLabel?: string;
}) {
  const { toast } = useToast();

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied", { tone: "success" });
      return;
    } catch {
      /* fall through to the legacy path */
    }
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      toast(ok ? "Copied" : "Couldn't copy — long-press to copy it manually.", {
        tone: ok ? "success" : "danger",
      });
    } catch {
      toast("Couldn't copy — long-press to copy it manually.", { tone: "danger" });
    }
  }

  return (
    <button
      type="button"
      className="tv-copy-btn"
      aria-label={ariaLabel ?? `Copy ${text}`}
      onClick={() => void copy()}
    >
      {label}
    </button>
  );
}
