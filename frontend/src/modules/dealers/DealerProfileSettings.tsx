import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
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
import {
  addRepresentation,
  getMyProfile,
  getPickList,
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
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [form, setForm] = useState({
    display_name: "",
    phone: "",
    contact_email: "",
    service_area: "",
    bio: "",
    // Route schedule (audit A2): "" = unset in each control.
    route_frequency: "",
    route_day_of_week: "",
    route_anchor_date: "",
  });
  const [reps, setReps] = useState<Representation[]>([]);
  const [companies, setCompanies] = useState<DealerCompany[]>([]);
  const [repCompany, setRepCompany] = useState("");
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
      route_frequency: p.route_frequency ?? "",
      route_day_of_week: p.route_day_of_week === null ? "" : String(p.route_day_of_week),
      route_anchor_date: p.route_anchor_date ?? "",
    });
    setReps(rs);
    // The "Add a company" chooser is a pick surface, so it
    // follows the user's own dealer list (owner fix, 2026-11-01):
    // a directory brand they removed is not offered for a NEW
    // representation claim. Representations already held are
    // records — they render from `reps`, untouched. If the pick
    // list doesn't answer, fall back to the full directory rather
    // than break the section.
    const pick = await getPickList().catch(() => null);
    const directory = cs.filter((c) => c.is_directory);
    setCompanies(
      pick
        ? directory.filter((c) =>
            pick.companies.some((p) => p.id === c.id),
          )
        : directory,
    );
  }, []);

  useEffect(() => {
    refresh().catch((err) => {
      if (err instanceof ApiError && err.code === "module_unavailable") {
        setModuleOff(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't load your dealer profile.");
      }
    });
  }, [refresh]);

  if (moduleOff) {
    return (
      <Panel title="Dealer profile" variant="plate">
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          The Dealers module isn't enabled for your account right now,
          so your dealer profile is unavailable. Your saved profile
          is kept — it comes back with the module.
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
        route_frequency:
          form.route_frequency === ""
            ? null
            : (form.route_frequency as "weekly" | "biweekly" | "monthly"),
        route_day_of_week:
          form.route_day_of_week === "" ? null : Number(form.route_day_of_week),
        route_anchor_date: form.route_anchor_date === "" ? null : form.route_anchor_date,
      });
      setProfile(saved);
      toast("Dealer profile saved.", { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your profile.");
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
          ? "You're listed publicly on the companies you represent."
          : "You're no longer listed publicly.",
        { tone: "success" },
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change visibility.");
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
      toast("Profile photo updated.", { tone: "success" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't upload the photo.");
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
      setError(err instanceof ApiError ? err.message : "Couldn't add that company.");
    }
  }

  async function removeRep(rep: Representation) {
    setError("");
    try {
      await removeRepresentation(rep.id);
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove that company.");
    }
  }

  const representedIds = new Set(reps.map((r) => r.company_id));
  const addable = companies.filter((c) => !representedIds.has(c.id));

  return (
    <Panel title="Dealer profile" variant="plate">
      {error && <Alert tone="danger">{error}</Alert>}
      {profile === null && !error ? (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> Loading…
        </p>
      ) : profile ? (
        <div style={{ display: "grid", gap: "var(--space-5)" }}>
          <form onSubmit={(e) => void save(e)} style={{ display: "grid", gap: "var(--space-3)" }}>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              How you appear to mechanics and shops. The contact
              details here are the ones shown publicly when you're
              listed — they're yours to choose, and your account
              email is never shown in their place.
            </p>
            <div style={formGridStyle}>
              <FormField label="Display name">
                <TextInput
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                />
              </FormField>
              <FormField label="Service area">
                <TextInput
                  value={form.service_area}
                  onChange={(e) => setForm({ ...form, service_area: e.target.value })}
                  placeholder="e.g. Central Minnesota"
                />
              </FormField>
              <FormField label="Phone (public)">
                <TextInput
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </FormField>
              <FormField label="Email (public)">
                <TextInput
                  type="email"
                  value={form.contact_email}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                />
              </FormField>
            </div>
            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              <p style={{ margin: 0, fontWeight: 600 }}>Route schedule</p>
              <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "0.9rem" }}>
                Your fixed route: how often, which weekday, and one
                date the route definitely ran (the cycles count from
                it). You'll get an inbox reminder on each route day.
                Leave the frequency unset if you don't run a fixed
                route.
              </p>
              <div style={formGridStyle}>
                <FormField label="Route frequency">
                  <Select
                    value={form.route_frequency}
                    onChange={(e) => setForm({ ...form, route_frequency: e.target.value })}
                  >
                    <option value="">No fixed route</option>
                    <option value="weekly">Every week</option>
                    <option value="biweekly">Every two weeks</option>
                    <option value="monthly">Monthly</option>
                  </Select>
                </FormField>
                <FormField label="Route day">
                  <Select
                    value={form.route_day_of_week}
                    onChange={(e) => setForm({ ...form, route_day_of_week: e.target.value })}
                  >
                    <option value="">Pick a weekday</option>
                    {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map(
                      (day, i) => (
                        <option key={day} value={String(i)}>
                          {day}
                        </option>
                      ),
                    )}
                  </Select>
                </FormField>
                <FormField label="Anchor date (a day the route ran)">
                  <DatePicker
                    value={form.route_anchor_date}
                    onChange={(v) => setForm({ ...form, route_anchor_date: v })}
                    clearable
                  />
                </FormField>
              </div>
              {profile.route_next_visit && (
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "0.9rem" }}>
                  Next route visit:{" "}
                  <strong style={{ color: "var(--text)" }}>
                    {new Date(`${profile.route_next_visit}T00:00:00`).toLocaleDateString("en-US", {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                    })}
                  </strong>
                </p>
              )}
            </div>
            <FormField label="Bio">
              <TextArea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
                rows={3}
                placeholder="Your truck, your route days, the brands you carry…"
              />
            </FormField>
            <div>
              <Button type="submit" loading={saving}>
                Save profile
              </Button>
            </div>
          </form>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>Photo</p>
            {profile.photo_url && (
              <img
                src={profile.photo_url}
                alt="Your profile"
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
              label="Drop a photo here, or"
              hint="JPG, PNG, or WebP."
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
                  Remove photo
                </Button>
              </div>
            )}
          </div>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
              Companies you represent
            </p>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              The directory companies you run a truck for. A new
              company shows as <strong>Unverified</strong> until an
              operator confirms it.
            </p>
            {reps.length === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>None yet.</p>
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
                        <Badge tone="success">Verified</Badge>
                      ) : (
                        <Badge tone="neutral">Unverified</Badge>
                      )}
                    </p>
                    <Button size="sm" variant="secondary" onClick={() => void removeRep(rep)}>
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {addable.length > 0 && (
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "end", flexWrap: "wrap" }}>
                <FormField label="Add a company">
                  <Select value={repCompany} onChange={(e) => setRepCompany(e.target.value)}>
                    <option value="">Pick a company…</option>
                    {addable.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <Button onClick={() => void addRep()} disabled={!repCompany}>
                  Represent
                </Button>
              </div>
            )}
          </div>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
              Service area
            </p>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              The territory you cover — this is how people find you
              in Find an Agent. Draw it on the map (any shape, any
              size) or use the blunt option: a ZIP code plus a
              radius, where customers confirm specifics with you
              directly. Territories overlap freely; everyone whose
              area covers a customer shows up.
            </p>
            <Suspense fallback={<Spinner />}>
              <ServiceAreaEditor profile={profile} onSaved={setProfile} />
            </Suspense>
            <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
              {profile.has_area
                ? profile.area_type === "polygon"
                  ? "Your territory is a drawn map shape."
                  : `Your territory is ${profile.area_radius_miles ?? ""} miles around ZIP ${profile.area_zip}.`
                : "No service area set yet — a public listing needs one, because Find an Agent matches on territory."}
            </p>
          </div>

          <div>
            <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
              Public listing
            </p>
            <Toggle
              checked={profile.publicly_listed}
              onChange={(checked) => void setListed(checked)}
              label="List me publicly on my companies' pages"
              disabled={!profile.publicly_listed && !profile.has_area}
            />
            <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
              {profile.publicly_listed
                ? "Mechanics browsing your companies see your card — name, service area, and the contact details above — and can add you as their preferred agent in one tap. Anyone searching Find an Agent inside your territory sees you too."
                : profile.has_area
                  ? "Nobody can see you in the directory. Turn this on to appear on the pages of the companies you represent and in Find an Agent."
                  : "Set your service area above first — a public listing needs a territory so Find an Agent can match you to the people you cover."}
            </p>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
