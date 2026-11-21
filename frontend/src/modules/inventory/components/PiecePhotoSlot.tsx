import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components";

/**
 * A set piece's own photo option (row 199), for the piece
 * editors (the add wizard's set step and the tool form).
 *
 * Row 201: Ryan testing the live wizard reported the set
 * pieces had "no spot for photo input" — the control was a
 * small text button tucked under the piece's fields and
 * was not findable in use. So the control is now a proper
 * photo row of its own: a labelled tile (the piece's photo
 * as a thumbnail, or an outlined camera tile when it has
 * none) with the word "Photo" beside it and clear
 * add/replace/remove controls. Draft-side only: a picked
 * file is held on the draft and uploaded to the saved
 * piece after the save (see piecePhotoUpload); clearing a
 * lookup photo drops it from the save payload.
 */
export function PiecePhotoSlot({
  photoUrl,
  file,
  index,
  labelText,
  addText,
  replaceText,
  removeText,
  onPick,
  onClear,
}: {
  /** The lookup-seeded page photo, if the draft carries one. */
  photoUrl?: string | null;
  /** A photo file the user picked for this piece. */
  file?: File | null;
  index: number;
  labelText: string;
  addText: string;
  replaceText: string;
  removeText: string;
  onPick: (file: File) => void;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setFilePreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setFilePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const shown = filePreview || photoUrl || null;
  const [imgFailed, setImgFailed] = useState(false);
  useEffect(() => {
    setImgFailed(false);
  }, [shown]);
  const pick = () => inputRef.current?.click();
  return (
    <div className="tv-piece-photo">
      <button
        type="button"
        className={
          shown ? "tv-piece-photo-tile tv-piece-photo-tile--filled" : "tv-piece-photo-tile"
        }
        onClick={pick}
        aria-label={`${shown ? replaceText : addText} ${index + 1}`}
        title={shown ? replaceText : addText}
      >
        {shown && !imgFailed ? (
          <img src={shown} alt="" onError={() => setImgFailed(true)} />
        ) : (
          // No photo yet — or the page's photo can't preview
          // here (the site's security policy blocks most
          // outside image hosts; it still attaches for real
          // when the item saves) — the camera tile says what
          // this spot is either way.
          <svg
            className="tv-piece-photo-glyph"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M4 8h3l2-2.5h6L17 8h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" />
            <circle cx="12" cy="13.5" r="3.5" />
          </svg>
        )}
      </button>
      <div className="tv-piece-photo-side">
        <span className="tv-piece-photo-label">{labelText}</span>
        <div className="tv-piece-photo-actions">
          <Button type="button" size="sm" variant="secondary" onClick={pick}>
            {shown ? replaceText : addText}
          </Button>
          {shown && (
            <button
              type="button"
              className="tv-list-remove-btn"
              aria-label={`${removeText} ${index + 1}`}
              title={`${removeText} ${index + 1}`}
              onClick={onClear}
            >
              {"−"}
            </button>
          )}
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        aria-label={`Piece ${index + 1} photo`}
        hidden
        onChange={(e) => {
          const picked = e.target.files?.[0];
          if (picked) onPick(picked);
          e.target.value = "";
        }}
      />
    </div>
  );
}
