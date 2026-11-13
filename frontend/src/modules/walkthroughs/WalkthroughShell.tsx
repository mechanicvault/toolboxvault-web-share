import type { ReactNode } from "react";
import { Button, Modal, ProgressBar } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import "../core/onboarding.css";
import "./walkthroughs.css";

/**
 * The shared shell for the "Do it with me" walkthroughs
 * (sweep D3) — built from the SETUP WIZARD's own kit, not a
 * new tour dialect: the wizard's step shell classes
 * (tv-setup-step / tv-setup-intro / tv-setup-example), its
 * progress words ("Step 1 of 3", via the same {done} of
 * {total} phrasing the setup progress uses), its footer
 * layout (tv-setup-actions: Back left, spacer, then the
 * step's own doors), and the shared Modal + ProgressBar.
 *
 * Every step carries Exit: the footer's Exit button and the
 * modal's own close both leave the pass. Nothing is written
 * anywhere until a walkthrough's final submit, so exiting
 * mid-way leaves no trace — re-entering starts again from
 * step 1 (the recorded decision: a half-finished lend or
 * claim is never silently resumed, because the real flow's
 * state may have changed underneath it).
 */
export function WalkthroughShell({
  open,
  title,
  stepIndex,
  totalSteps,
  onExit,
  footer,
  children,
}: {
  open: boolean;
  title: string;
  /** 0-based current step. */
  stepIndex: number;
  totalSteps: number;
  onExit: () => void;
  footer: ReactNode;
  children: ReactNode;
}) {
  const t = useT();
  return (
    <Modal open={open} onClose={onExit} title={title} size="lg" footer={footer}>
      <p className="tv-walk-stepof">
        {t("walk.stepOf" as never)
          .replace("{step}", String(stepIndex + 1))
          .replace("{total}", String(totalSteps))}
      </p>
      <div className="tv-walk-progress">
        <ProgressBar
          value={((stepIndex + 1) / totalSteps) * 100}
          label={t("walk.stepOf" as never)
            .replace("{step}", String(stepIndex + 1))
            .replace("{total}", String(totalSteps))}
        />
      </div>
      <div className="tv-walk-stepanim" key={stepIndex}>
        {children}
      </div>
    </Modal>
  );
}

/** The wizard's footer, walkthrough edition: Back on the
 *  left; Exit, an optional Skip-this-step, and the step's
 *  Continue/submit on the right. Exit rides EVERY step. */
export function WalkthroughFooter({
  onBack,
  onExit,
  onSkip,
  onContinue,
  continueLabel,
  continueDisabled,
  busy,
}: {
  onBack?: () => void;
  onExit: () => void;
  onSkip?: () => void;
  onContinue: () => void;
  continueLabel: string;
  continueDisabled?: boolean;
  busy?: boolean;
}) {
  const t = useT();
  return (
    <div className="tv-setup-actions">
      {onBack && (
        <Button variant="ghost" onClick={onBack} disabled={busy}>
          {t("setup.back" as never)}
        </Button>
      )}
      <span className="tv-setup-actions-spacer" />
      <Button variant="ghost" onClick={onExit} disabled={busy}>
        {t("walk.exit" as never)}
      </Button>
      {onSkip && (
        <Button variant="ghost" onClick={onSkip} disabled={busy}>
          {t("setup.skip" as never)}
        </Button>
      )}
      <Button
        onClick={onContinue}
        loading={busy}
        disabled={continueDisabled || busy}
      >
        {continueLabel}
      </Button>
    </div>
  );
}

/** The standing entry point — the wizard banner's furniture
 *  (tv-setup-banner) with a plain-words door: what this is,
 *  one sentence on why, and a button that says what it does. */
export function WalkthroughDoor({
  title,
  body,
  onStart,
  testId,
}: {
  title: string;
  body: string;
  onStart: () => void;
  testId?: string;
}) {
  const t = useT();
  return (
    <div className="tv-setup-banner tv-walk-door" role="region" aria-label={title}>
      <div className="tv-setup-banner-main">
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
      <div className="tv-setup-banner-actions">
        <button
          type="button"
          className="tv-setup-banner-cta"
          data-testid={testId}
          onClick={onStart}
        >
          {t("walk.doorCta" as never)}
        </button>
      </div>
    </div>
  );
}

/** The gentle one-time offer inside a real flow (the checkout
 *  modal, the claim form): shown only while real data says
 *  the user has never completed that flow. */
export function WalkthroughOffer({
  body,
  onStart,
  testId,
}: {
  body: string;
  onStart: () => void;
  testId?: string;
}) {
  const t = useT();
  return (
    <div className="tv-walk-offer">
      <p>{body}</p>
      <Button size="sm" data-testid={testId} onClick={onStart}>
        {t("walk.doorCta" as never)}
      </Button>
    </div>
  );
}
