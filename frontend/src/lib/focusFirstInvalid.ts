/**
 * Focus the first invalid field (B-05, Deep Audit Round 2 — the
 * gate §2 forms model clause Round 1 fixed on signup/Add-tool/
 * settings and the rebuilt wizard family regressed): on a failed
 * Next/submit, focus MOVES to the first field carrying
 * aria-invalid="true" (FormField wires that attribute from the
 * field error). Deferred one frame so the error state that marks
 * the field has rendered. Returns true when a field was found —
 * when no field is marked (a step-level error with no owning
 * field), focus stays where it is, exactly as before.
 */
export function focusFirstInvalid(root: ParentNode = document): void {
  requestAnimationFrame(() => {
    const el = root.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (el) {
      el.focus();
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        el.select?.();
      }
    }
  });
}
