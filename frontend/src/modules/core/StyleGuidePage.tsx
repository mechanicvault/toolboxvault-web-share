import { useState, type ReactNode } from "react";
import {
  Alert,
  Avatar,
  Badge,
  Breadcrumbs,
  Button,
  Checkbox,
  DataTable,
  EmptyState,
  FileUpload,
  FormField,
  FramedImage,
  Modal,
  NotificationTicker,
  Pagination,
  Panel,
  ProgressBar,
  Radio,
  SearchBar,
  Select,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
  Toggle,
  useToast,
  type UploadFileItem,
} from "../../components";
import { AccentSwatches } from "../../theme/AccentDots";
import { useTheme } from "../../theme/ThemeContext";
import { ThemeSwitcher } from "../../theme/ThemeSwitcher";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Panel title={title} variant="plate">
      <div style={{ display: "grid", gap: "var(--spacing)" }}>{children}</div>
    </Panel>
  );
}

function Row({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
      {children}
    </div>
  );
}

const DEMO_IMG =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">
       <rect width="640" height="480" fill="gray"/>
       <rect x="70" y="90" width="500" height="300" rx="18" fill="dimgray"/>
       <circle cx="320" cy="240" r="70" fill="orange"/>
     </svg>`,
  );

const TABLE_ROWS = [
  { id: "1", name: "DEWALT 20V Cordless Drill", brand: "DEWALT", price: 129.5, standing: "Available" },
  { id: "2", name: "Snap-On Combination Wrench Set", brand: "Snap-On", price: 87.2, standing: "Available" },
  { id: "3", name: "Husky 46in Rolling Toolbox", brand: "Husky", price: 340.0, standing: "In repair" },
  { id: "4", name: "Milwaukee M18 Impact Driver", brand: "Milwaukee", price: 149.99, standing: "Available" },
];

/**
 * Style guide: the whole design system on one page. Flip the theme and
 * the accent and judge every component at a glance. Not in the nav —
 * visit /style-guide directly.
 */
export default function StyleGuidePage() {
  const { theme } = useTheme();
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [toggleOn, setToggleOn] = useState(true);
  const [page, setPage] = useState(2);
  const [modalOpen, setModalOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<UploadFileItem[]>([]);

  function demoUpload(files: File[]) {
    const items: UploadFileItem[] = files.map((f, i) => ({
      id: `${f.name}-${Date.now()}-${i}`,
      name: f.name,
      status: "uploading",
      progress: 35,
    }));
    setUploadFiles(items);
    window.setTimeout(
      () =>
        setUploadFiles((prev) =>
          prev.map((f) => ({ ...f, status: "done" as const, progress: 100 })),
        ),
      1200,
    );
  }

  return (
    <div style={{ display: "grid", gap: "var(--spacing)" }}>
      <div>
        <Breadcrumbs
          items={[{ label: "Home", to: "/" }, { label: "Style guide" }]}
        />
        <h1 style={{ margin: "0.35rem 0 0.25rem", fontSize: "var(--font-size-2xl)" }}>
          Style guide
        </h1>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          Every shared component, in every variant and state — currently the{" "}
          <strong style={{ color: "var(--text)" }}>{theme}</strong> theme. Switch the
          theme or spin the accent wheel and the whole page re-tints.
        </p>
      </div>

      <Section title="Appearance controls">
        <div
          style={{
            display: "grid",
            gap: "1.25rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
          }}
        >
          <div>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>Theme</p>
            <ThemeSwitcher />
          </div>
          <div>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>Accent color</p>
            <AccentSwatches />
          </div>
        </div>
      </Section>

      <Section title="Notifications ticker">
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          The header-center ticker with three sample notifications:
          one at a time, ~3s dwell, vertical roll, pauses on hover,
          instant swap under reduced-motion. Live data comes from{" "}
          <code>GET /api/core/notifications</code> — until that endpoint
          exists the header stays empty (no reserved space).
        </p>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            padding: "var(--space-3)",
            border: "1px solid var(--edge)",
            borderRadius: "var(--radius)",
            background: "var(--header-bg)",
          }}
        >
          <NotificationTicker
            items={[
              { id: "demo-1", text: "Welcome to the new Toolbox Vault website" },
              { id: "demo-2", text: "Steel Light theme just landed — try it in Appearance", tone: "success" },
              { id: "demo-3", text: "Reminder: verify your email to secure your account", tone: "warning" },
            ]}
          />
        </div>
      </Section>

      <Section title="Buttons">
        <Row>
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="ghost">Ghost</Button>
        </Row>
        <Row>
          <Button size="sm">Small</Button>
          <Button size="md">Medium</Button>
          <Button size="lg">Large</Button>
        </Row>
        <Row>
          <Button loading>Saving</Button>
          <Button disabled>Disabled</Button>
          <Button variant="secondary" loading>
            Working
          </Button>
        </Row>
        <Button block>Full-width primary</Button>
      </Section>

      <Section title="Form controls">
        <div
          style={{
            display: "grid",
            gap: "0.9rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
          }}
        >
          <FormField label="Text input" htmlFor="sg-text" hint="A helpful hint.">
            <TextInput id="sg-text" placeholder="e.g. Torque wrench" />
          </FormField>
          <FormField label="Invalid input" htmlFor="sg-invalid" error="This field is required.">
            <TextInput id="sg-invalid" invalid defaultValue="" placeholder="Required" />
          </FormField>
          <FormField label="Disabled input" htmlFor="sg-disabled">
            <TextInput id="sg-disabled" disabled defaultValue="Can't touch this" />
          </FormField>
          <FormField label="Select" htmlFor="sg-select">
            <Select id="sg-select" defaultValue="good">
              <option value="new">New</option>
              <option value="good">Good</option>
              <option value="fair">Fair</option>
              <option value="poor">Poor</option>
            </Select>
          </FormField>
        </div>
        <FormField label="Text area" htmlFor="sg-notes">
          <TextArea id="sg-notes" placeholder="Notes — searchable later." />
        </FormField>
        <FormField label="Search bar" htmlFor="sg-search">
          <SearchBar id="sg-search" value={search} onChange={setSearch} placeholder="Search tools, dealers, claims…" />
        </FormField>
        <Row>
          <Checkbox label="Checked option" defaultChecked />
          <Checkbox label="Unchecked option" />
          <Checkbox label="Disabled option" disabled />
        </Row>
        <Row>
          <Radio name="sg-radio" label="First choice" value="a" defaultChecked />
          <Radio name="sg-radio" label="Second choice" value="b" />
          <Radio name="sg-radio" label="Disabled choice" value="c" disabled />
        </Row>
        <Row>
          <Toggle checked={toggleOn} onChange={setToggleOn} label="Toggle switch" />
          <Toggle checked={false} onChange={() => undefined} label="Off + fixed" disabled />
        </Row>
      </Section>

      <Section title="Panels & cards">
        <div
          style={{
            display: "grid",
            gap: "var(--spacing)",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
          }}
        >
          <Panel title="Default panel">
            <p style={{ margin: 0 }}>Standard boxed content.</p>
          </Panel>
          <Panel title="Raised panel" variant="raised">
            <p style={{ margin: 0 }}>Sits a step above the surface.</p>
          </Panel>
          <Panel title="Accent edge" variant="accent-edge">
            <p style={{ margin: 0 }}>Accent-tinted left edge.</p>
          </Panel>
          <Panel
            title="Nameplate panel"
            variant="plate"
            actions={<Badge tone="accent" dot>Live</Badge>}
          >
            <p style={{ margin: 0 }}>
              The riveted nameplate look — Steel's signature header.
            </p>
          </Panel>
        </div>
        <FramedImage src={DEMO_IMG} alt="Framed image demo" caption="Framed image demo — captions render only when a caption is passed" aspectRatio="16 / 9" />
      </Section>

      <Section title="Data table">
        <DataTable
          columns={[
            { key: "name", header: "Tool", render: (r) => r.name, sortable: true, sortValue: (r) => r.name },
            { key: "brand", header: "Brand", render: (r) => r.brand, sortable: true, sortValue: (r) => r.brand },
            {
              key: "price",
              header: "Price",
              align: "right",
              render: (r) => `$${r.price.toFixed(2)}`,
              sortable: true,
              sortValue: (r) => r.price,
            },
            {
              key: "standing",
              header: "Standing",
              render: (r) => (
                <Badge tone={r.standing === "In repair" ? "warning" : "success"} dot>
                  {r.standing}
                </Badge>
              ),
            },
          ]}
          rows={TABLE_ROWS}
          rowKey={(r) => r.id}
        />
        <DataTable
          columns={[{ key: "name", header: "Tool", render: (r: { name: string }) => r.name }]}
          rows={[] as { name: string }[]}
          rowKey={() => "x"}
          emptyState="Empty tables get the standard empty treatment."
        />
        <Pagination page={page} pageCount={9} onChange={setPage} summary="Page navigation" />
      </Section>

      <Section title="Feedback & status">
        <Row>
          <Badge>Neutral</Badge>
          <Badge tone="accent">Accent</Badge>
          <Badge tone="success" dot>Good</Badge>
          <Badge tone="warning" dot>Fair</Badge>
          <Badge tone="danger" dot>Urgent</Badge>
        </Row>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <Alert tone="info" title="Heads up">Information message with a title.</Alert>
          <Alert tone="success">Saved successfully.</Alert>
          <Alert tone="warning">Two items need attention before this can be finalized.</Alert>
          <Alert tone="danger" dismissible>
            Something failed — and this one can be dismissed.
          </Alert>
        </div>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <ProgressBar value={75} label="Claim completion" />
          <ProgressBar value={40} tone="warning" label="Storage used" />
          <ProgressBar value={92} tone="danger" label="Almost full" />
          <ProgressBar value={100} tone="success" label="Complete" />
        </div>
        <Row>
          <Spinner size="sm" label="Small spinner" />
          <Spinner size="md" label="Medium spinner" />
          <Spinner size="lg" label="Large spinner" />
          <Avatar name="John Doe" size="sm" />
          <Avatar name="Ryan M" size="md" />
          <Avatar name="Tool Vault" size="lg" />
        </Row>
        <Row>
          <Button
            variant="secondary"
            onClick={() => toast("Your changes were saved.", { tone: "success", title: "Saved" })}
          >
            Show a toast
          </Button>
          <Button
            variant="secondary"
            onClick={() => toast("A claim needs your attention.", { tone: "warning" })}
          >
            Warning toast
          </Button>
          <Button onClick={() => setModalOpen(true)}>Open modal</Button>
        </Row>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Example dialog"
          footer={
            <>
              <Button variant="secondary" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setModalOpen(false);
                  toast("Confirmed.", { tone: "success" });
                }}
              >
                Confirm
              </Button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            Dialogs share the panel chrome, trap attention over a dimmed
            backdrop, and close with Escape or a backdrop click.
          </p>
        </Modal>
      </Section>

      <Section title="Tabs, empty state & upload">
        <Tabs
          tabs={[
            { id: "a", label: "Overview", content: <p style={{ margin: 0 }}>First tab panel.</p> },
            { id: "b", label: "Details", content: <p style={{ margin: 0 }}>Second tab panel.</p> },
            { id: "c", label: "History", content: <p style={{ margin: 0 }}>Third tab panel.</p> },
            { id: "d", label: "Disabled", disabled: true, content: null },
          ]}
        />
        <EmptyState
          title="Nothing here yet"
          description="Empty states explain what belongs here and offer the next action."
          action={<Button>Add something</Button>}
        />
        <FileUpload
          onFiles={demoUpload}
          files={uploadFiles}
          hint="Demo only — files finish 'uploading' after a moment."
        />
      </Section>
    </div>
  );
}
