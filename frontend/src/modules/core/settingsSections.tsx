/**
 * The settings SECTION components (settings restructure, owner
 * review round 1, 2026-10-19). These used to be stacked in one
 * long SettingsPage scroll; now each is a registry section (see
 * settingsRegistry.tsx) rendered one at a time by the shell.
 * Profile data is REAL (the /me payload behind useAuth); sections
 * whose systems don't exist yet say so plainly instead of faking
 * controls.
 */
export { ProfileSection } from "./settings/profile";
export { SecuritySection } from "./settings/security";
export { PublicProfileSection } from "./settings/publicProfile";
export { AppearanceSection } from "./settings/appearance";
export { NotificationsSection } from "./settings/notifications";
