/**
 * The prints module's designed file door (Sweep C1, 07-F4):
 * the raw browser "Choose File" widget is retired from the
 * Upload and Edit pages. A door is the shared `.tv-upload`
 * drop-zone face — "Drop … here, or" in words over a labelled
 * Choose button — with the real input hidden behind it, drag
 * highlighting, and the pick cleared after every use so the
 * same file can be picked again. The shared FileUpload
 * component's labels are hardcoded English, so the module
 * wears the same face with its own dictionary strings
 * (single language per user).
 */

import { useRef, useState } from "react";

import { Button } from "../../components";

export function sizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function FileDoor({
  accept,
  multiple = false,
  disabled,
  onPick,
  dropText,
  buttonLabel,
}: {
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  onPick: (files: FileList) => void;
  dropText: string;
  buttonLabel: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function handle(list: FileList | null) {
    if (!list || list.length === 0) return;
    onPick(list);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
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
      <p className="pr-door-drop">{dropText}</p>
      <Button
        type="button"
        variant="secondary"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {buttonLabel}
      </Button>
      <input
        ref={inputRef}
        className="pr-door-input"
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(e) => handle(e.target.files)}
        aria-label={buttonLabel}
      />
    </div>
  );
}

/** The live state of a single-file seat: what was picked, its
 * size, that it is ready, and the remove door — the shared
 * `.tv-upload-files` row treatment. */
export function PickedFileRow({
  name,
  size,
  readyLabel,
  removeLabel,
  onRemove,
}: {
  name: string;
  size: number;
  readyLabel: string;
  removeLabel: string;
  onRemove: () => void;
}) {
  return (
    <ul className="tv-upload-files">
      <li className="tv-upload-file">
        <div className="tv-upload-file-row">
          <span className="tv-upload-file-name" title={name}>
            {name} · {sizeLabel(size)}
          </span>
          <span className="tv-upload-file-status tv-upload-file-status--done">
            ✓ {readyLabel}
          </span>
          <button
            type="button"
            className="tv-list-remove-btn pr-media-remove"
            aria-label={removeLabel}
            title={removeLabel}
            onClick={onRemove}
          >
            {"−"}
          </button>
        </div>
      </li>
    </ul>
  );
}
