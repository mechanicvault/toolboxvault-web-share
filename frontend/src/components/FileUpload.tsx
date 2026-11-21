import { useRef, useState } from "react";
import { Button } from "./Button";
import { ProgressBar } from "./ProgressBar";

export interface UploadFileItem {
  id: string;
  name: string;
  status: "queued" | "uploading" | "done" | "error";
  /** 0–100 while uploading. */
  progress?: number;
  message?: string;
}

interface FileUploadProps {
  /** Called with the picked/dropped files; the owner drives the upload. */
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  /** Controlled per-file status rows (owner keeps upload state). */
  files?: UploadFileItem[];
  label?: string;
  hint?: string;
}

/**
 * Shared file picker: drop zone + per-file progress list.
 * Presentational only — the owning module performs the actual transfer
 * (see inventory's PhotoUploader, which wraps this component).
 */
export function FileUpload({
  onFiles,
  accept,
  multiple = true,
  disabled,
  files = [],
  label = "Drop files here, or",
  hint,
}: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function handle(list: FileList | null) {
    if (!list || list.length === 0) return;
    onFiles([...list]);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div>
      <div
        className={`tv-upload${dragOver ? " is-dragover" : ""}${disabled ? " is-disabled" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (!disabled) handle(e.dataTransfer.files);
        }}
      >
        <p style={{ margin: "0 0 var(--space-3)" }}>{label}</p>
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </Button>
        {hint && (
          <p style={{ margin: "var(--space-3) 0 0", fontSize: "var(--font-size-sm)" }}>{hint}</p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => handle(e.target.files)}
          aria-label="Choose files to upload"
          style={{ display: "none" }}
        />
      </div>
      {files.length > 0 && (
        <ul className="tv-upload-files">
          {files.map((f) => (
            <li key={f.id} className="tv-upload-file">
              <div className="tv-upload-file-row">
                <span className="tv-upload-file-name">{f.name}</span>
                {f.status === "uploading" && (
                  <span className="tv-upload-file-status">{Math.round(f.progress ?? 0)}%</span>
                )}
                {f.status === "queued" && <span className="tv-upload-file-status">Waiting…</span>}
                {f.status === "done" && (
                  <span className="tv-upload-file-status tv-upload-file-status--done">✓ Done</span>
                )}
                {f.status === "error" && (
                  <span className="tv-upload-file-status tv-upload-file-status--error">
                    {f.message ?? "Failed"}
                  </span>
                )}
              </div>
              {f.status === "uploading" && <ProgressBar value={f.progress ?? 0} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
