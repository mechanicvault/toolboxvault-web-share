import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, FileUpload, Panel, TextInput } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import {
  acceptForKind,
  photoFileError,
} from "../inventory/components/photoTransfer";
import {
  quickAddSeedState,
  type QuickAddSeed,
} from "../inventory/quickAddSeed";

/**
 * The empty Home's first-tool card (sheet row 108, outside
 * audit wave 1 — the owner circled this fix): when a member's
 * Home has no widgets on it, the page leads with the one
 * action that makes the product valuable — adding the first
 * tool — in its three real forms: type a name, snap a photo
 * (both open the add wizard seeded, the Quick Add widget's
 * own pattern), or import a spreadsheet. The widget gallery
 * stays one tap away underneath.
 */
export function FirstToolCard({
  onAddWidget,
}: {
  onAddWidget: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const openWizard = (seed?: QuickAddSeed) => {
    navigate(
      "/inventory/new",
      seed ? { state: quickAddSeedState(seed) } : undefined,
    );
  };

  const onPhoto = (files: File[]) => {
    const file = files[0];
    if (!file) return;
    const problem = photoFileError(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    openWizard({ photo: file });
  };

  return (
    <Panel title={t("home.firstTool.title")}>
      <div className="tv-first-tool">
        <p className="tv-first-tool-body">{t("home.firstTool.body")}</p>
        <div className="tv-quickadd">
          <form
            className="tv-quickadd-form"
            onSubmit={(e) => {
              e.preventDefault();
              const trimmed = name.trim();
              openWizard(trimmed ? { name: trimmed } : undefined);
            }}
          >
            <TextInput
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("home.widget.quickAdd.namePlaceholder")}
              aria-label={t("home.widget.quickAdd.nameLabel")}
            />
            <Button type="submit">{t("home.widget.quickAdd.go")}</Button>
          </form>
          <FileUpload
            onFiles={onPhoto}
            accept={acceptForKind("photo")}
            multiple={false}
            label={t("home.widget.quickAdd.dropLabel")}
            hint={t("home.widget.quickAdd.dropHint")}
          />
          {error && (
            <p className="tv-widget-entry-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="tv-first-tool-doors">
          <Button
            variant="ghost"
            onClick={() => navigate("/inventory/import")}
          >
            {t("home.firstTool.import")}
          </Button>
          <Button variant="ghost" onClick={onAddWidget}>
            {t("home.addWidget")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
