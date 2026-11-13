import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Panel,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { useAuth } from "./AuthContext";
import { DealerPicker } from "../dealers/components/DealerFields";
import { LocationTreePicker } from "../inventory/components/LocationTreePicker";
import {
  parseWizardDefaults,
  WIZARD_SECTIONS,
  type WizardDefaults,
} from "../inventory/wizardDefaults";

const stackStyle = { display: "grid", gap: "var(--spacing)" } as const;
const checkColumnStyle = { display: "grid", gap: "0.55rem" } as const;
const hintStyle = {
  margin: 0,
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;

/**
 * Settings → Add-tool wizard defaults (Wizard Phase 1,
 * 2026-10-25): the user's Add wizard setup — which optional
 * tool sections are pre-checked on the wizard's include step,
 * and the usual storage location + usual dealer the wizard
 * pre-fills. Saved onto the ACCOUNT (PATCH /me wizard_defaults,
 * migration 0058), so the setup follows the user to every
 * device; saving an empty setup is a real save (the bare
 * minimum, explicit), distinct from never having saved.
 */
export default function WizardDefaultsSettings() {
  const t = useT();
  const { toast } = useToast();
  const { user, refreshUser } = useAuth();
  const [sections, setSections] = useState<string[]>([]);
  const [locationId, setLocationId] = useState("");
  const [dealerCompanyId, setDealerCompanyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Initialize from the account document once per user — a
  // refreshUser() after saving must not clobber in-flight edits
  // with the just-saved values (they are identical anyway, but
  // the guard keeps the form stable).
  const initializedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!user || initializedFor.current === user.id) return;
    initializedFor.current = user.id;
    const parsed = parseWizardDefaults(user.wizard_defaults);
    setSections(parsed.sections);
    setLocationId(parsed.location_id);
    setDealerCompanyId(parsed.dealer_company_id);
  }, [user]);

  function toggleSection(key: string, on: boolean) {
    setSections((prev) =>
      on ? [...prev, key] : prev.filter((s) => s !== key),
    );
  }

  async function onSave() {
    setBusy(true);
    setError("");
    const doc: WizardDefaults = {
      sections: WIZARD_SECTIONS.map((s) => s.key).filter((k) =>
        sections.includes(k),
      ),
      location_id: locationId,
      dealer_company_id: dealerCompanyId,
    };
    try {
      await api("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ wizard_defaults: doc }),
      });
      await refreshUser();
      toast(t("wizardDefaults.saved"), { title: "Saved", tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save your wizard defaults.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={stackStyle}>
      <p style={hintStyle}>{t("wizardDefaults.intro")}</p>
      {error && <Alert tone="danger">{error}</Alert>}
      <Panel title={t("wizardDefaults.sectionsTitle")}>
        <div style={checkColumnStyle}>
          <p style={hintStyle}>{t("wizardDefaults.sectionsBody")}</p>
          {WIZARD_SECTIONS.map((section) => (
            <Checkbox
              key={section.key}
              name={`wizard-default-${section.key}`}
              label={`${t(section.labelKey)}: ${t(section.hintKey)}`}
              checked={sections.includes(section.key)}
              onChange={(e) => toggleSection(section.key, e.target.checked)}
            />
          ))}
        </div>
      </Panel>
      <Panel title={t("wizardDefaults.usualLocation")}>
        <LocationTreePicker
          id="wizard-default-location"
          value={locationId || null}
          emptyLabel={t("wizardDefaults.noLocation")}
          onChange={(id) => setLocationId(id ?? "")}
        />
      </Panel>
      <Panel title={t("wizardDefaults.usualDealer")}>
        <DealerPicker
          id="wizard-default-dealer"
          label={t("wizardDefaults.usualDealer")}
          value={dealerCompanyId}
          onChange={setDealerCompanyId}
        />
      </Panel>
      <div>
        <Button onClick={() => void onSave()} loading={busy}>
          {t("wizardDefaults.save")}
        </Button>
      </div>
    </div>
  );
}
