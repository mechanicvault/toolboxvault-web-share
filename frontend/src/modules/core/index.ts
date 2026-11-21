/** Core module public surface.

Other modules import core ONLY through this file (blueprint §4, Law 4) —
never deep paths like `../core/auth/RequireAuth`. Add exports here
deliberately when another module genuinely needs a core component.
*/
export { RequireAuth } from "./auth/RequireAuth";
export { useAuth } from "./AuthContext";
export { accountTypeLabel } from "./accountTypes";
export {
  enabledShareGroups,
  LOCKED_SHARE_FIELDS,
  OPTIONAL_SHARE_FIELDS,
  SHARE_RECIPIENT_GROUPS,
  type ShareGroupState,
  type ShareItemRef,
  type ShareItemSummary,
  type ShareRecipientGroup,
  type SharingOverview,
} from "./sharing";
