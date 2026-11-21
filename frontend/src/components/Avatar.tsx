interface AvatarProps {
  /** Display name; initials are derived from it. */
  name: string;
  /** Optional photo URL; falls back to initials. */
  src?: string;
  size?: "sm" | "md" | "lg";
}

/** Round user avatar: photo when available, initials placeholder otherwise. */
export function Avatar({ name, src, size = "md" }: AvatarProps) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
  return (
    <span className={`tv-avatar tv-avatar--${size}`} aria-hidden={src ? undefined : true}>
      {src ? <img src={src} alt="" width={64} height={64} /> : initials || "?"}
    </span>
  );
}
