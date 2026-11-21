import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  FileUpload,
  FormField,
  formGridStyle,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  Toggle,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  addRepresentation,
  createPrivateCompany,
  getMyProfile,
  listCompanies,
  listMyRepresentations,
  removeProfilePhoto,
  removeRepresentation,
  updateMyProfile,
  uploadProfilePhoto,
} from "./api";
// Deep audit F3-05: Leaflet (map library + CSS) rides in ONLY when
// this dealer-only section actually renders — lazy-split out of the
// Settings chunk every user downloads.
const ServiceAreaEditor = lazy(() => import("./components/ServiceAreaEditor"));
import { EMPTY_COMPANY } from "./components/CompanyForm";

import type { AgentProfile, DealerCompany, Representation } from "./types";

/**
 * Settings -> Dealer profile (dealer portal, 2026-10-19). Only
 * rendered for tool_dealer group holders (SettingsPage gates it).
 * The profile is the agent's public face — and it stays PRIVATE
 * until they flip "List me publicly" on: visibility is their
 * choice, off by default (owner spec).
 */
export default function DealerProfileSettings() {
  const { toast } = useToast();
  const t = useT();
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [form, setForm] = useState({
    display_name: "",
    phone: "",
    contact_email: "",
    service_area: "",
    bio: "",
  });
  const [reps, setReps] = useState<Representation[]>([]);
  const [companies, setCompanies] = useState<DealerCompany[]>([]);
  const [repCompany, setRepCompany] = useState("");
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customBusy, setCustomBusy] = useState(false);
  const [error, setError] = useState("");
  const [moduleOff, setModuleOff] = useState(false);
  const [saving, setSaving] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [p, rs, cs] = await Promise.all([
      getMyProfile(),
      listMyRepresentations(),
      listCompanies(),
    ]);
    setProfile(p);
    setForm({
      display_name: p.display_name,
      phone: p.phone,
      contact_email: p.contact_email,
      service_area: p.service_area,
      bio: p.bio,
    });
    setReps(rs);
    // The "Add a company" chooser offers the FULL directory
    // (owner sheet row 24, 2026-11-15): a dealer picking the
    // company he works under is not shopping his own dealer
    // pick list — a brand he trimmed from that list (as a
    // mechanic) must still be here when he claims it as his
    // employer. Representations already held render from
    // `reps`, untouched.
    setCompanies(cs.filter((c) => c.is_directory));
  }, []);

  useEffect(() => {
    refresh().catch((err) => {
      if (err instanceof ApiError && err.code === "module_unavailable") {
        setModuleOff(true);
      } else {
        setError(err instanceof ApiError ? err.message : t("settings.dealer.loadFailed"));
      }
    });
  }, [refresh]);

  if (moduleOff) {
    return (
      <Panel title={t("settings.dealer.title")} variant="plate">
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.dealer.moduleOff")}
        </p>
      </Panel>
    );
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const saved = await updateMyProfile({
        display_name: form.display_name,
        phone: form.phone,
        contact_email: form.contact_email,
        service_area: form.service_area,
        bio: form.bio,
      });
      setProfile(saved);
      toast(t("settings.dealer.savedToast"), { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.dealer.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function setListed(listed: boolean) {
    if (!profile) return;
    setError("");
    try {
      const saved = await updateMyProfile({ publicly_listed: listed });
      setProfile(saved);
      toast(
        listed
          ? t("settings.dealer.listedToast")
          : t("settings.dealer.unlistedToast"),
        { tone: "success" },
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.dealer.visibilityFailed"));
    }
  }

  async function onPhoto(files: File[]) {
    const file = files[0];
    if (!file) return;
    setError("");
    setPhotoBusy(true);
    try {
      const saved = await uploadProfilePhoto(file);
      setProfile(saved);
      toast(t("settings.dealer.photoToast"), { tone: "success" });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.dealer.photoFailed"));
    } finally {
      setPhotoBusy(false);
    }
  }

  async function addRep() {
    if (!repCompany) return;
    setError("");
    try {
      await addRepresentation(repCompany);
      setRepCompany("");
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.dealer.addCompanyFailed"));
    }
  }

  /* Owner sheet row 23 (2026-11-15): the company isn't in the
   * directory — create it as the dealer's own company and file
   * the representation against it in one move. */
  async function addCustomCompany() {
    const name = customName.trim();
    if (!name) return;
    setError("");
    setCustomBusy(true);
    try {
      const company = await createPrivateCompany({
        ...EMPTY_COMPANY,
        name,
      });
      await addRepresentation(company.id);
      setCustomName("");
      setCustomOpen(false);
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.dealer.customCompanyFailed"));
    } finally {
      setCustomBusy(false);
    }
  }

  async function removeRep(rep: Representation) {
    setError("");
    try {
      await removeRepresentation(rep.id);
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.dealer.removeCompanyFailed"));
    }
  }

  const representedIds = new Set(reps.map((r) => r.company_id));
  const addable = companies.filter((c) => !representedIds.has(c.id));

  return (
    <Panel title={t("settings.dealer.title")} variant="plate">
      {error && <Alert tone="danger">{error}</Alert>}
      {profile === null && !error ? (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> {t("shell.loading")}
        </p>
      ) : profile ? (
        <div style={{ display: "grid", gap: "var(--space-5)" }}>
          <form onSubmit={(e) => void save(e)} style={{ display: "grid", gap: "var(--space-3)" }}>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.dealer.intro")}
            </p>
            <div style={formGridStyle}>
              <FormField label={t("settings.dealer.displayName")}>
                <TextInput
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                />
              </FormField>
              <FormField label={t("settings.dealer.serviceArea")}>
                <TextInput
                  value={form.service_area}
                  onChange={(e) => setForm({ ...form, service_area: e.target.value })}
                  placeholder={t("settings.dealer.serviceAreaPlaceholder")}
                />
              </FormField>
              <FormField label={t("settings.dealer.phonePublic")}>
                <TextInput
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </FormField>
              <FormField label={t("settings.dealer.emailPublic")}>
                <TextInput
                  type="email"
                  value={form.contact_email}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                />
              </FormField>
            </div>
            {/* No route picker here (owner sheet row 22,
                2026-11-15): the route day is specific to each
                mechanic/shop — it lives on THEIR agent record,
                not in the dealer's own profile. The profile's
                stored route facts stay for migrated data and
                the route-day job; they are no longer edited
                from this surface. */}
            <FormField label={t("settings.dealer.bioLabel")}>
              <TextArea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
                rows={3}
                placeholder={t("settings.dealer.bioPlaceholder")}
              />
            </FormField>
            <div>
              <Button type="submit" loading={saving}>
                {t("settings.dealer.saveProfile")}
              </Button>
            </div>
          </form>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>{t("settings.dealer.photoHeading")}</p>
            {profile.photo_url && (
              <img
                src={profile.photo_url}
                alt={t("settings.dealer.photoAlt")}
                style={{
                  width: "96px",
                  height: "96px",
                  objectFit: "cover",
                  borderRadius: "var(--radius)",
                  display: "block",
                  marginBottom: "var(--space-3)",
                }}
              />
            )}
            <FileUpload
              multiple={false}
              accept="image/jpeg,image/png,image/webp"
              label={t("settings.dealer.photoDropLabel")}
              hint={t("settings.dealer.photoHint")}
              disabled={photoBusy}
              onFiles={(files) => void onPhoto(files)}
            />
            {profile.has_photo && (
              <div style={{ marginTop: "var(--space-2)" }}>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    void removeProfilePhoto().then(setProfile);
                  }}
                >
                  {t("settings.dealer.removePhoto")}
                </Button>
              </div>
            )}
          </div>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
              {t("settings.dealer.companiesHeading")}
            </p>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              {t("settings.dealer.companiesLead")}
              <strong>{t("settings.dealer.companiesStrong")}</strong>
              {t("settings.dealer.companiesTail")}
            </p>
            {reps.length === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>{t("settings.dealer.noneYet")}</p>
            ) : (
              <div style={{ display: "grid", gap: "0.4rem", marginBottom: "0.8rem" }}>
                {reps.map((rep) => (
                  <div
                    key={rep.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "1rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <p style={{ margin: 0 }}>
                      <strong>{rep.company_name}</strong>{" "}
                      {rep.verified ? (
                        <Badge tone="success">{t("settings.insurer.verifiedBadge")}</Badge>
                      ) : (
                        <Badge tone="neutral">{t("settings.dealer.unverifiedBadge")}</Badge>
                      )}
                    </p>
                    <Button size="sm" variant="secondary" onClick={() => void removeRep(rep)}>
                      {t("settings.dealer.removeBtn")}
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {addable.length > 0 && (
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "end", flexWrap: "wrap" }}>
                <FormField label={t("settings.dealer.addCompanyLabel")}>
                  <Select value={repCompany} onChange={(e) => setRepCompany(e.target.value)}>
                    <option value="">{t("settings.insurer.pickCompanyOption")}</option>
                    {addable.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <Button onClick={() => void addRep()} disabled={!repCompany}>
                  {t("settings.dealer.representBtn")}
                </Button>
              </div>
            )}
            {customOpen ? (
              <div style={{ marginTop: "var(--space-3)", display: "grid", gap: "var(--space-2)" }}>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "end", flexWrap: "wrap" }}>
                  <FormField label={t("settings.dealer.customCompanyLabel")}>
                    <TextInput
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      placeholder={t("settings.dealer.customCompanyPlaceholder")}
                    />
                  </FormField>
                  <Button
                    onClick={() => void addCustomCompany()}
                    disabled={!customName.trim()}
                    loading={customBusy}
                  >
                    {t("settings.dealer.customCompanyBtn")}
                  </Button>
                  <Button variant="ghost" onClick={() => setCustomOpen(false)}>
                    {t("settings.dealer.customCompanyCancel")}
                  </Button>
                </div>
                <p style={{ color: "var(--text-muted)", margin: 0 }}>
                  {t("settings.dealer.customCompanyHint")}
                </p>
              </div>
            ) : (
              <div style={{ marginTop: "var(--space-3)" }}>
                <Button variant="ghost" size="sm" onClick={() => setCustomOpen(true)}>
                  {t("settings.dealer.customCompanyToggle")}
                </Button>
              </div>
            )}
          </div>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
              {t("settings.dealer.serviceArea")}
            </p>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              {t("settings.dealer.serviceAreaIntro")}
            </p>
            <Suspense fallback={<Spinner />}>
              <ServiceAreaEditor profile={profile} onSaved={setProfile} />
            </Suspense>
            <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
              {profile.has_area
                ? profile.area_type === "polygon"
                  ? t("settings.dealer.areaPolygon")
                  : t("settings.dealer.areaRadius")
                      .replace("{miles}", String(profile.area_radius_miles ?? ""))
                      .replace("{zip}", profile.area_zip ?? "")
                : t("settings.dealer.areaNone")}
            </p>
          </div>

          <div>
            <p
              className="tv-setting-row-name"
              style={{ margin: "0 0 var(--space-2)" }}
            >
              {t("settings.dealer.publicListing")}
            </p>
            {/* The listing switch rides the standard setting-row
                anatomy (settings uniformity, 2026-11-13): name +
                description + state word + switch. The label text
                becomes the row name (and stays whole as the
                switch's aria-label); the state-dependent
                explanation becomes the row description. */}
            <div
              className="tv-setting-row is-clickable"
              onClick={(e) => {
                if (
                  (e.target as HTMLElement).closest(
                    "button, a, input, select, textarea",
                  )
                ) {
                  return;
                }
                e.currentTarget
                  .querySelector<HTMLButtonElement>('[role="switch"]')
                  ?.click();
              }}
            >
              <div className="tv-setting-row-main">
                <p className="tv-setting-row-name">
                  {t("settings.dealer.listMeLabel")}
                </p>
                <p className="tv-setting-row-desc">
                  {profile.publicly_listed
                    ? t("settings.dealer.listedDesc")
                    : profile.has_area
                      ? t("settings.dealer.unlistedDesc")
                      : t("settings.dealer.noAreaDesc")}
                </p>
              </div>
              <span className="tv-setting-row-state">
                <span className="tv-setting-row-state-word">
                  {profile.publicly_listed
                    ? t("settings.stateOn")
                    : t("settings.stateOff")}
                </span>
                <Toggle
                  checked={profile.publicly_listed}
                  onChange={(checked) => void setListed(checked)}
                  ariaLabel={t("settings.dealer.listMeLabel")}
                  disabled={!profile.publicly_listed && !profile.has_area}
                />
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
