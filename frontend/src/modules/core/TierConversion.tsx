/**
 * Tier conversion (owner orders, 2026-11-10): the doors OUT of
 * the downloads level, shared by both seats that open them —
 * the slim bar at the top of the rung Home (the primary door)
 * and the Settings → Profile panel (the second door). ONE flow
 * body, so the two doors can never drift:
 *
 *   - the code form: the gate code the account was handed after
 *     signup, checked server-side by POST /core/convert-with-code
 *     (throttled per account; the honest error shows in place
 *     and the field clears);
 *   - the request zone: "I don't have a code — request
 *     approval". One request per account, EVER (server-enforced);
 *     once sent, the zone shows the request's standing — pending,
 *     approved, denied — and never offers the ask again. A denial
 *     leaves the code form as the route, and says so.
 *
 * Everything here renders ONLY for a downloads-tier account:
 * the server refuses every other rung anyway, and the reach
 * rule says a surface never enumerates what the seat can't use —
 * the components below all gate on the account's tier from the
 * auth payload, never a client guess.
 */
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "../../components/Button";
import { Modal } from "../../components/Modal";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError, api } from "../../lib/api";
import { useAuth } from "./AuthContext";

type RequestStatus = "pending" | "approved" | "denied" | null;

interface RequestState {
  status: RequestStatus;
}

export function ConversionFlowBody({
  onConverted,
}: {
  /** Fired after a successful code conversion (the seat closes
   *  its modal / navigates). Approval conversions happen on the
   *  god side; this account hears about them in its inbox. */
  onConverted: () => void;
}) {
  const t = useT();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [requestStatus, setRequestStatus] = useState<RequestStatus>(null);
  const [requestLoaded, setRequestLoaded] = useState(false);
  const [requestBusy, setRequestBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<RequestState>("/core/conversion-request")
      .then((state) => {
        if (!live) return;
        setRequestStatus(state.status);
        setRequestLoaded(true);
      })
      .catch(() => {
        // The state read is a nicety — the request POST still
        // enforces the one-ever rule server-side.
        if (live) setRequestLoaded(true);
      });
    return () => {
      live = false;
    };
  }, []);

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    if (busy || !code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api("/core/convert-with-code", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      onConverted();
    } catch (err) {
      setCode("");
      if (err instanceof ApiError && err.code === "invalid_gate_code") {
        setError(t("convert.wrong"));
      } else if (err instanceof ApiError && err.status === 429) {
        setError(t("convert.tooMany"));
      } else if (err instanceof ApiError && err.code === "already_full_access") {
        setError(t("convert.alreadyFull"));
      } else {
        setError(t("convert.wrong"));
      }
    } finally {
      setBusy(false);
    }
  }

  async function sendRequest() {
    if (requestBusy) return;
    setRequestBusy(true);
    setRequestError(null);
    try {
      const state = await api<RequestState>("/core/conversion-request", {
        method: "POST",
      });
      setRequestStatus(state.status);
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_requested") {
        // The server's standing is the truth — reflect it.
        setRequestStatus("pending");
        try {
          const state = await api<RequestState>("/core/conversion-request");
          setRequestStatus(state.status);
        } catch {
          /* keep the pending reading */
        }
      } else {
        setRequestError(t("convert.requestFailed"));
      }
    } finally {
      setRequestBusy(false);
    }
  }

  return (
    <div className="tv-convert-flow">
      <p className="tv-convert-intro">{t("convert.intro")}</p>
      <form onSubmit={submitCode}>
        <label className="tv-convert-label" htmlFor="tv-convert-code">
          {t("convert.codeLabel")}
        </label>
        <div className="tv-convert-row">
          <input
            id="tv-convert-code"
            className="tv-convert-input"
            type="text"
            autoComplete="off"
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={busy || !code.trim()}>
            {busy ? t("convert.converting") : t("convert.convertButton")}
          </Button>
        </div>
        {error ? (
          <p className="tv-convert-error" role="alert">
            {error}
          </p>
        ) : null}
      </form>
      <div className="tv-convert-divider">
        <span>{t("convert.requestDivider")}</span>
      </div>
      {requestStatus === "pending" ? (
        <p className="tv-convert-state">{t("convert.requestPending")}</p>
      ) : requestStatus === "approved" ? (
        <p className="tv-convert-state">{t("convert.requestApproved")}</p>
      ) : requestStatus === "denied" ? (
        <p className="tv-convert-state">{t("convert.requestDenied")}</p>
      ) : (
        <>
          <p className="tv-convert-intro">{t("convert.requestIntro")}</p>
          <Button
            type="button"
            variant="secondary"
            disabled={!requestLoaded || requestBusy}
            onClick={sendRequest}
          >
            {requestBusy ? t("convert.requesting") : t("convert.requestButton")}
          </Button>
          {requestError ? (
            <p className="tv-convert-error" role="alert">
              {requestError}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

/** The one-shot flag that carries the conversion's confirmation
 *  across the hard landing below. */
const CONVERTED_FLAG = "tv-just-converted";

/** The modal both doors open. Conversion success: land on Home
 *  with a HARD navigation — the account's whole world changed
 *  (tier, reach, rail, the re-shown tip), and a fresh load is
 *  the only landing that reads all of it fresh; an in-place
 *  swap would keep serving the rung session's cached reads
 *  (Home's scoped GET cache among them). The welcome toast is
 *  carried across the reload by the flag above and fired by
 *  ConvertAccountBar on the landing. */
export function ConversionModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();

  function handleConverted() {
    onClose();
    try {
      sessionStorage.setItem(CONVERTED_FLAG, "1");
    } catch {
      /* the landing still happens; only the toast is lost */
    }
    window.location.assign("/");
  }

  return (
    <Modal open={open} onClose={onClose} title={t("convert.title")} size="sm">
      <ConversionFlowBody onConverted={handleConverted} />
    </Modal>
  );
}

/** The primary door: a slim panel at the top of the rung Home.
 *  Self-contained — renders nothing at all for every other tier
 *  (the coordinator may re-seat it when the Home header is
 *  rebuilt; its contract is just "mount once on Home"). It also
 *  carries the converted landing's welcome toast (see
 *  ConversionModal): mounted on every Home load, it fires the
 *  one-shot flag's toast exactly once, for any tier. */
export function ConvertAccountBar() {
  const t = useT();
  const { user } = useAuth();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let flagged = false;
    try {
      flagged = sessionStorage.getItem(CONVERTED_FLAG) === "1";
      if (flagged) sessionStorage.removeItem(CONVERTED_FLAG);
    } catch {
      flagged = false;
    }
    if (flagged) toast(t("convert.done"), { tone: "success" });
    // Fire once on mount; the flag is consumed above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!user || user.tier !== "downloads") return null;
  return (
    <div className="tv-convert-bar">
      <p className="tv-convert-bar-text">{t("convert.barText")}</p>
      <Button type="button" variant="primary" size="sm" onClick={() => setOpen(true)}>
        {t("convert.barButton")}
      </Button>
      <ConversionModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

/** The second door: the Settings → Profile panel. Same tier
 *  gate, same flow — the settings surface renders it only for
 *  the rung, exactly like the Home bar. */
export function AccessCodeSettingsPanel({ tier }: { tier: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  if (tier !== "downloads") return null;
  return (
    <div className="tv-convert-settings">
      <p className="tv-convert-settings-title">{t("convert.settingsTitle")}</p>
      <p className="tv-convert-settings-body">{t("convert.settingsBody")}</p>
      <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
        {t("convert.settingsButton")}
      </Button>
      <ConversionModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
