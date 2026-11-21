/**
 * The inspection checklist wizard (owner order 2026-11-09):
 * the Documents shelf's inspection row trades its Download
 * button for Customize, and this popup is what it opens.
 *
 * Step 1 is the shop (name / address / phone — all optional;
 * whatever is given brands the generated PDF's header). Then
 * one screen per inspection category, every item a toggle,
 * everything ON by default so an untouched wizard reproduces
 * the full checklist. The last step generates the PDF from the
 * choices: the visitor previews it in this window (the site's
 * document-viewer pattern — the browser's own PDF viewer in a
 * frame), and the Download button there is the one that counts,
 * through the shelf's counted machinery on the server.
 *
 * Public like the page it lives on: no account, no email, no
 * gate. Closing the window loses nothing on the page behind it.
 * The options are DATA from the backend (code-defined,
 * bilingual) — the labels on screen and the labels in the PDF
 * are the same strings, in the language being browsed.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Alert,
  Button,
  Checkbox,
  FormField,
  Modal,
  Spinner,
  TextInput,
} from "../../components";
import { useLocale, useT } from "../../i18n/LocaleContext";
import "./downloads.css";

interface WizardItem {
  key: string;
  label: string;
}

interface WizardCategory {
  key: string;
  name: string;
  items: WizardItem[];
}

interface WizardPayload {
  shop_name: string;
  shop_address: string;
  shop_phone: string;
  items: string[];
  lang: string;
}

const PDF_FILENAME = "Vehicle-Inspection-Checklist.pdf";

export function InspectionWizard({
  open,
  onClose,
  onDownloaded,
}: {
  open: boolean;
  onClose: () => void;
  /** The shelf re-reads itself after a counted download so the
   * row's number is live, same as a plain row download. */
  onDownloaded: () => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const [categories, setCategories] = useState<WizardCategory[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [step, setStep] = useState(0);
  const [shopName, setShopName] = useState("");
  const [shopAddress, setShopAddress] = useState("");
  const [shopPhone, setShopPhone] = useState("");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(false);
  const previewUrlRef = useRef<string | null>(null);

  const totalSteps = (categories?.length ?? 0) + 1;

  const clearPreview = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setPreviewUrl(null);
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const res = await fetch(
          `/api/downloads/inspection/options?lang=${locale}`,
          { signal },
        );
        if (!res.ok) throw new Error("bad");
        const data = (await res.json()) as { categories: WizardCategory[] };
        setCategories(data.categories);
        setSelected(
          new Set(data.categories.flatMap((c) => c.items.map((i) => i.key))),
        );
        setLoadError(false);
      } catch {
        if (!signal?.aborted) setLoadError(true);
      }
    },
    [locale],
  );

  // A fresh run each time the window opens.
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setCategories(null);
    setGenError(false);
    setDownloadError(false);
    clearPreview();
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [open, load, clearPreview]);

  useEffect(() => clearPreview, [clearPreview]);

  function payload(): WizardPayload {
    return {
      shop_name: shopName.trim(),
      shop_address: shopAddress.trim(),
      shop_phone: shopPhone.trim(),
      items: [...selected],
      lang: locale,
    };
  }

  async function generate() {
    if (generating) return;
    setGenerating(true);
    setGenError(false);
    try {
      const res = await fetch("/api/downloads/inspection/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) throw new Error("bad");
      const blob = await res.blob();
      clearPreview();
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      setPreviewUrl(url);
    } catch {
      setGenError(true);
    } finally {
      setGenerating(false);
    }
  }

  async function downloadPdf() {
    if (downloading) return;
    setDownloading(true);
    setDownloadError(false);
    try {
      const res = await fetch("/api/downloads/inspection/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) throw new Error("bad");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = PDF_FILENAME;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      onDownloaded();
    } catch {
      setDownloadError(true);
    } finally {
      setDownloading(false);
    }
  }

  function toggle(itemKey: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(itemKey);
      else next.delete(itemKey);
      return next;
    });
  }

  function setCategory(category: WizardCategory, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const item of category.items) {
        if (on) next.add(item.key);
        else next.delete(item.key);
      }
      return next;
    });
  }

  const inPreview = previewUrl !== null;
  const category = step > 0 ? categories?.[step - 1] : undefined;
  const isLastStep = categories !== null && step === totalSteps - 1;

  const footer = inPreview ? (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          clearPreview();
          setDownloadError(false);
        }}
      >
        {t("downloads.insp.editChoices")}
      </Button>
      <Button
        onClick={() => void downloadPdf()}
        loading={downloading}
      >
        {t("downloads.docs.download")}
      </Button>
    </>
  ) : (
    <>
      {step > 0 && (
        <Button
          variant="secondary"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          {t("downloads.insp.back")}
        </Button>
      )}
      {!isLastStep && categories !== null && (
        <Button onClick={() => setStep((s) => s + 1)}>
          {t("downloads.insp.next")}
        </Button>
      )}
      {isLastStep && (
        <Button onClick={() => void generate()} loading={generating}>
          {generating
            ? t("downloads.insp.generating")
            : t("downloads.insp.generate")}
        </Button>
      )}
    </>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        inPreview
          ? t("downloads.insp.previewTitle")
          : t("downloads.insp.title")
      }
      size="lg"
      footer={footer}
    >
      <div className="dl-insp">
        {loadError && (
          <div className="dl-load-error">
            <Alert tone="danger">{t("downloads.insp.loadError")}</Alert>
            <Button variant="secondary" onClick={() => void load()}>
              {t("downloads.docs.retry")}
            </Button>
          </div>
        )}
        {!loadError && categories === null && (
          <Spinner label={t("downloads.docs.loading")} />
        )}
        {!loadError && categories !== null && !inPreview && (
          <>
            <p className="dl-insp-progress">
              {t("downloads.insp.stepOf")
                .replace("{step}", String(step + 1))
                .replace("{total}", String(totalSteps))}
            </p>
            {step === 0 && (
              <div className="dl-insp-shop">
                <h3>{t("downloads.insp.shopTitle")}</h3>
                <p>{t("downloads.insp.shopBody")}</p>
                <FormField
                  label={t("downloads.insp.shopName")}
                  htmlFor="insp-shop-name"
                >
                  <TextInput
                    id="insp-shop-name"
                    value={shopName}
                    maxLength={60}
                    placeholder={t("downloads.insp.shopNamePh")}
                    onChange={(e) => setShopName(e.target.value)}
                  />
                </FormField>
                <FormField
                  label={t("downloads.insp.shopAddress")}
                  htmlFor="insp-shop-address"
                >
                  <TextInput
                    id="insp-shop-address"
                    value={shopAddress}
                    maxLength={90}
                    placeholder={t("downloads.insp.shopAddressPh")}
                    onChange={(e) => setShopAddress(e.target.value)}
                  />
                </FormField>
                <FormField
                  label={t("downloads.insp.shopPhone")}
                  htmlFor="insp-shop-phone"
                >
                  <TextInput
                    id="insp-shop-phone"
                    type="tel"
                    value={shopPhone}
                    maxLength={30}
                    onChange={(e) => setShopPhone(e.target.value)}
                  />
                </FormField>
              </div>
            )}
            {category && (
              <div className="dl-insp-category">
                <h3>{category.name}</h3>
                <p className="dl-insp-note">{t("downloads.insp.catNote")}</p>
                <div className="dl-insp-bulk">
                  <Button
                    variant="secondary"
                    onClick={() => setCategory(category, true)}
                  >
                    {t("downloads.insp.selectAll")}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => setCategory(category, false)}
                  >
                    {t("downloads.insp.selectNone")}
                  </Button>
                  <span className="dl-insp-count">
                    {t("downloads.insp.onCount")
                      .replace(
                        "{on}",
                        String(
                          category.items.filter((i) => selected.has(i.key))
                            .length,
                        ),
                      )
                      .replace("{total}", String(category.items.length))}
                  </span>
                </div>
                <div className="dl-insp-items">
                  {category.items.map((item) => (
                    <Checkbox
                      key={item.key}
                      label={item.label}
                      checked={selected.has(item.key)}
                      onChange={(e) => toggle(item.key, e.target.checked)}
                    />
                  ))}
                </div>
              </div>
            )}
            {genError && (
              <Alert tone="danger">{t("downloads.insp.genError")}</Alert>
            )}
          </>
        )}
        {!loadError && categories !== null && inPreview && (
          <div className="dl-insp-preview">
            <p className="dl-insp-note">{t("downloads.insp.previewNote")}</p>
            <iframe
              className="dl-insp-frame"
              title={t("downloads.insp.previewTitle")}
              src={previewUrl}
            />
            {downloadError && (
              <Alert tone="danger">{t("downloads.insp.genError")}</Alert>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
