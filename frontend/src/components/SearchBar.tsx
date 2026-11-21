import { TextInput } from "./TextInput";

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  id?: string;
  ariaLabel?: string;
  autoFocus?: boolean;
}

/** Search input with a magnifier glyph and a clear (×) affordance. */
export function SearchBar({
  value,
  onChange,
  placeholder = "Search…",
  id,
  ariaLabel = "Search",
  autoFocus,
}: SearchBarProps) {
  return (
    <span className="tv-search">
      <span className="tv-search-icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" />
          <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </span>
      <TextInput
        id={id}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoFocus={autoFocus}
      />
      {value && (
        <button
          type="button"
          className="tv-search-clear"
          aria-label="Clear search"
          onClick={() => onChange("")}
        >
          ×
        </button>
      )}
    </span>
  );
}
