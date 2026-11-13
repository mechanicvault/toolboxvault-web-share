import { useEffect, useId, useRef, useState } from "react";
import "../wizard.css";
import { Button, FormField, TextInput, useToast } from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { fetchAiStatus } from "../../catalog/api";
import {
  lookupDrawers,
  type DrawerConfiguration,
  type DrawerLookupResult,
} from "./locationTree";

/**
 * AI drawer lookup (owner spec, 2026-10-25; grounded rework
 * the same day after the Lookup Truth Audit).
 *
 * The user's own NAME for the new location lives in the
 * parent's form and is never touched here. This block carries
 * its OWN make + model box — prefilled from the name until the
 * user edits it, so what's being looked up is always on screen
 * ("We'll look up: …") — plus an optional product-page link.
 *
 * Answers come back as drawer CONFIGURATIONS:
 *  - read off a real product page (grounded) — the source is
 *    named and linked; when the model comes in more than one
 *    layout, the user picks theirs ("Does yours have 10
 *    drawers or 19 drawers?");
 *  - or AI recall — ONE configuration, labeled UNVERIFIED in
 *    plain words (the audit proved recall contradicts itself;
 *    a menu of guesses is never offered).
 * Either way the user then sees the drawer list by name and
 * can edit every name (or save them as they are) before
 * anything is created. Creation happens only through the
 * parent's onConfirm, on the Create click — nothing is ever
 * created silently.
 *
 * MANUAL COUNT (Ryan, 2026-11-07): the same add step also
 * takes a typed NUMBER of locations (17 drawers, 17
 * cabinets) for when the user skips the lookup or the lookup
 * can't verify the model. The number produces the SAME
 * confirm-and-name list the AI path produces — same editor,
 * same Create, same onConfirm — so the two paths can never
 * drift. The manual block is NOT an AI surface: it renders
 * whether or not the seam is lit. Only the lookup block
 * above it follows the dark-seam contract (renders nothing
 * while the AI is dark); a wallet that can't pay gets the
 * server refusal as a toast, the established AI-surface
 * pattern.
 *
 * Text here is plain body type at normal weights — the
 * condensed display face never renders this prose (the owner's
 * standing wizard-type fix, applied by class in components.css).
 */
export function DrawerAutofill({
  nameText,
  parentId,
  onConfirm,
}: {
  /** The user's own name for the tier-2 location (parent's
   *  field). Only a prefill for the model box — never the
   *  query once the user edits the model box, and never
   *  modified by this block. */
  nameText: string;
  /** The tier-1 parent the toolbox is being added under. Part
   *  of the reset key: changing the target retires a result. */
  parentId: string;
  /** Create the toolbox (parent's name) + these child names,
   *  in order. The parent owns the creation machinery and its
   *  own error surface; it rethrows on failure so this block
   *  can leave its busy state with the list still open. */
  onConfirm: (names: string[]) => Promise<void>;
}) {
  const t = useT();
  const { toast } = useToast();
  const [aiOn, setAiOn] = useState(false);
  const [phase, setPhase] = useState<
    "idle" | "busy" | "choose" | "list" | "miss" | "linkfail" | "failed" | "creating"
  >("idle");
  const [result, setResult] = useState<DrawerLookupResult | null>(null);
  const [modelTouched, setModelTouched] = useState(false);
  const [modelText, setModelText] = useState("");
  const [link, setLink] = useState("");
  const [chosen, setChosen] = useState<DrawerConfiguration | null>(null);
  const [names, setNames] = useState<string[]>([]);
  // Which path produced the name list on screen: the AI
  // lookup (with its source lines) or the typed manual count.
  // Both converge on the one list editor below.
  const [listOrigin, setListOrigin] = useState<"ai" | "manual" | null>(null);
  const [manualCount, setManualCount] = useState("");
  const uid = useId().replace(/:/g, "");
  const aliveRef = useRef(true);

  const model = (modelTouched ? modelText : nameText).trim();

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  // The dark-seam contract: while no AI provider is configured
  // (or the status read fails), this surface simply isn't
  // offered — the manual flow is whole without it.
  useEffect(() => {
    let cancelled = false;
    fetchAiStatus()
      .then((s) => {
        if (!cancelled) setAiOn(s.configured);
      })
      .catch(() => {
        if (!cancelled) setAiOn(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A new add target starts the block fresh: the model box
  // mirrors the (new) name again until the user edits it.
  const lastParentRef = useRef(parentId);
  useEffect(() => {
    if (lastParentRef.current !== parentId) {
      lastParentRef.current = parentId;
      setModelTouched(false);
      setModelText("");
      setLink("");
      setManualCount("");
      setListOrigin(null);
    }
  }, [parentId]);

  // Editing the model, the link, or the target retires any
  // result — the confirm on screen always matches the boxes
  // above it (the wizard lookup's standing rule).
  const resetKey = `${parentId}|${model}|${link}`;
  const lastKeyRef = useRef(resetKey);
  useEffect(() => {
    if (lastKeyRef.current !== resetKey) {
      lastKeyRef.current = resetKey;
      setPhase("idle");
      setResult(null);
      setChosen(null);
      setNames([]);
      setListOrigin(null);
    }
  }, [resetKey]);

  function namesFor(config: DrawerConfiguration): string[] {
    const pattern = t("inventory.drawerAutofill.patternDefault");
    return [
      ...Array.from({ length: config.drawer_count }, (_, i) => `${pattern} ${i + 1}`),
      ...config.extra_sections,
    ];
  }

  function pickConfiguration(config: DrawerConfiguration) {
    setChosen(config);
    setNames(namesFor(config));
    setListOrigin("ai");
    setPhase("list");
  }

  // The manual path into the SAME list: a typed count becomes
  // that many default-named rows, editable before creation —
  // identical editor, identical Create, identical onConfirm.
  const manualCountValue = Number(manualCount);
  const manualCountValid =
    Number.isInteger(manualCountValue) &&
    manualCountValue >= 1 &&
    manualCountValue <= 100;

  function startManualList() {
    if (!manualCountValid) return;
    const pattern = t("inventory.drawerAutofill.patternDefault");
    setResult(null);
    setChosen(null);
    setNames(
      Array.from(
        { length: manualCountValue },
        (_, i) => `${pattern} ${i + 1}`,
      ),
    );
    setListOrigin("manual");
    setPhase("list");
  }

  async function runLookup() {
    if (!model && !link.trim()) return;
    setPhase("busy");
    try {
      const data = await lookupDrawers(model, link.trim());
      if (!aliveRef.current) return;
      if (data.link_error) {
        setResult(null);
        setPhase("linkfail");
        return;
      }
      if (data.found && data.configurations.length > 0) {
        setResult(data);
        if (data.configurations.length > 1) {
          setChosen(null);
          setPhase("choose");
        } else {
          pickConfiguration(data.configurations[0]);
        }
      } else {
        setResult(null);
        setPhase("miss");
      }
    } catch (err) {
      if (!aliveRef.current) return;
      if (err instanceof ApiError && err.code === "insufficient_credits") {
        toast(err.message, { tone: "danger" });
        setPhase("idle");
        return;
      }
      setResult(null);
      setPhase("failed");
    }
  }

  async function create() {
    const cleaned = names.map((name) => name.trim()).filter(Boolean);
    if (cleaned.length === 0) return;
    setPhase("creating");
    try {
      await onConfirm(cleaned);
      // The parent closes/resets its own form on success; this
      // block unmounts with it. If it stays mounted, retire to
      // idle rather than offering the same create twice.
      if (aliveRef.current) {
        setResult(null);
        setChosen(null);
        setNames([]);
        setListOrigin(null);
        setManualCount("");
        setPhase("idle");
      }
    } catch {
      if (aliveRef.current) setPhase("list");
    }
  }

  const busy = phase === "busy" || phase === "creating";

  return (
    <div className="tv-drawer-autofill">
      {phase !== "choose" && phase !== "list" && phase !== "creating" && (
        <>
          {aiOn && (
            <>
          <FormField
            label={t("inventory.drawerAutofill.modelLabel")}
            htmlFor={`tv-drawer-model-${uid}`}
            hint={t("inventory.drawerAutofill.modelHint")}
          >
            <TextInput
              id={`tv-drawer-model-${uid}`}
              value={model}
              onChange={(e) => {
                setModelTouched(true);
                setModelText(e.target.value);
              }}
              placeholder={t("inventory.locationGuide.placeholder2")}
            />
          </FormField>
          <FormField
            label={t("inventory.drawerAutofill.linkLabel")}
            htmlFor={`tv-drawer-link-${uid}`}
          >
            <TextInput
              id={`tv-drawer-link-${uid}`}
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://"
              inputMode="url"
            />
          </FormField>
          <div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void runLookup()}
              loading={phase === "busy"}
              disabled={!model && !link.trim()}
            >
              {t("inventory.drawerAutofill.button")}
            </Button>
          </div>
          {model && (
            <p className="tv-drawer-autofill-hint">
              {t("inventory.drawerAutofill.lookingUpLine").replace(
                "{model}",
                model,
              )}
            </p>
          )}
          <p className="tv-drawer-autofill-hint">
            {t("inventory.drawerAutofill.hint")}
          </p>
            </>
          )}
          {/* The manual count (Ryan, 2026-11-07): always
              offered — it is not an AI surface — for the runs
              where the lookup is skipped or can't verify the
              model. It feeds the same name list below. */}
          <FormField
            label={t("inventory.drawerAutofill.manualCountLabel")}
            htmlFor={`tv-drawer-count-${uid}`}
            hint={t("inventory.drawerAutofill.manualCountHint")}
          >
            <TextInput
              id={`tv-drawer-count-${uid}`}
              type="number"
              min="1"
              max="100"
              step="1"
              value={manualCount}
              onChange={(e) => setManualCount(e.target.value)}
              placeholder="17"
              inputMode="numeric"
            />
          </FormField>
          <div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={startManualList}
              disabled={!manualCountValid}
            >
              {t("inventory.drawerAutofill.manualMakeList")}
            </Button>
          </div>
        </>
      )}
      {phase === "miss" && (
        <p className="tv-drawer-autofill-note" role="status">
          {t("inventory.drawerAutofill.notFound")}
        </p>
      )}
      {phase === "linkfail" && (
        <p className="tv-drawer-autofill-note" role="status">
          {t("inventory.drawerAutofill.linkFailed")}
        </p>
      )}
      {phase === "failed" && (
        <p className="tv-drawer-autofill-note" role="status">
          {t("inventory.drawerAutofill.failed")}
        </p>
      )}

      {phase === "choose" && result && (
        <div className="tv-drawer-autofill-confirm">
          <p className="tv-drawer-autofill-found">
            {t("inventory.drawerAutofill.chooseIntro")}
          </p>
          {result.source && (
            <p className="tv-drawer-autofill-source">
              {result.grounded && result.source_url ? (
                <>
                  {t("inventory.drawerAutofill.groundedSource").replace(
                    "{source}",
                    "",
                  )}
                  <a href={result.source_url} target="_blank" rel="noreferrer">
                    {result.source}
                  </a>
                </>
              ) : (
                t("inventory.drawerAutofill.source").replace(
                  "{source}",
                  result.source,
                )
              )}
            </p>
          )}
          <div className="tv-drawer-autofill-configs">
            {result.configurations.map((config) => (
              <Button
                key={config.drawer_count}
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => pickConfiguration(config)}
              >
                {config.extra_sections.length > 0
                  ? t("inventory.drawerAutofill.chooseConfigSections")
                      .replace("{count}", String(config.drawer_count))
                      .replace("{names}", config.extra_sections.join(", "))
                  : t("inventory.drawerAutofill.chooseConfig").replace(
                      "{count}",
                      String(config.drawer_count),
                    )}
              </Button>
            ))}
          </div>
          <div className="tv-drawer-autofill-actions">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                setResult(null);
                setPhase("idle");
              }}
            >
              {t("inventory.drawerAutofill.cancel")}
            </Button>
          </div>
        </div>
      )}

      {(phase === "list" || phase === "creating") &&
        (listOrigin === "manual" || (result && chosen)) && (
        <div className="tv-drawer-autofill-confirm">
          {listOrigin === "manual" ? (
            <p className="tv-drawer-autofill-found">
              {t("inventory.drawerAutofill.manualFoundLine").replace(
                "{count}",
                String(names.length),
              )}
            </p>
          ) : (
            result &&
            chosen && (
              <p className="tv-drawer-autofill-found">
                {t("inventory.drawerAutofill.foundLine")
                  .replace("{name}", model)
                  .replace("{count}", String(chosen.drawer_count))}
              </p>
            )
          )}
          {result && result.source && (
            <p className="tv-drawer-autofill-source">
              {result.grounded && result.source_url ? (
                <>
                  {t("inventory.drawerAutofill.groundedSource").replace(
                    "{source}",
                    "",
                  )}
                  <a href={result.source_url} target="_blank" rel="noreferrer">
                    {result.source}
                  </a>
                </>
              ) : (
                t("inventory.drawerAutofill.source").replace(
                  "{source}",
                  result.source,
                )
              )}
            </p>
          )}
          {result && !result.grounded && (
            <p className="tv-drawer-autofill-note" role="status">
              {t("inventory.drawerAutofill.unverifiedNote")}
            </p>
          )}
          <p className="tv-drawer-autofill-hint">
            {t("inventory.drawerAutofill.namesIntro")}
          </p>
          <div className="tv-drawer-autofill-names">
            {names.map((name, index) => (
              <div className="tv-drawer-autofill-name-row" key={index}>
                <TextInput
                  value={name}
                  aria-label={`${t("inventory.drawerAutofill.patternDefault")} ${index + 1}`}
                  onChange={(e) =>
                    setNames((rows) =>
                      rows.map((row, i) => (i === index ? e.target.value : row)),
                    )
                  }
                />
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    setNames((rows) => rows.filter((_, i) => i !== index))
                  }
                >
                  {t("inventory.drawerAutofill.removeName")}
                </Button>
              </div>
            ))}
          </div>
          <div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() =>
                setNames((rows) => [
                  ...rows,
                  `${t("inventory.drawerAutofill.patternDefault")} ${rows.length + 1}`,
                ])
              }
            >
              {t("inventory.drawerAutofill.addDrawer")}
            </Button>
          </div>
          <div className="tv-drawer-autofill-actions">
            <Button
              type="button"
              size="sm"
              onClick={() => void create()}
              loading={phase === "creating"}
              disabled={names.every((name) => !name.trim())}
            >
              {t("inventory.drawerAutofill.create")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setResult(null);
                setChosen(null);
                setNames([]);
                setListOrigin(null);
                setPhase("idle");
              }}
            >
              {t("inventory.drawerAutofill.cancel")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
