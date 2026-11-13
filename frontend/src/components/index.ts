/* Shared component library — the ONLY way modules render common visuals
 * (blueprint §4). Everything is token-driven via the theme layer. */

export { AppShell, type ShellNavItem } from "./AppShell";
export { Alert, type AlertTone } from "./Alert";
export { Avatar } from "./Avatar";
export { SpinningEmblem } from "./SpinningEmblem";
export { SocialLinks, FACEBOOK_URL, FacebookGlyph } from "./SocialLinks";
export { BrandIcon, type BrandIconName } from "./BrandIcon";
export { Badge, type BadgeTone } from "./Badge";
export { Breadcrumbs, type Crumb } from "./Breadcrumbs";
export { Button, HrefButton, LinkButton, buttonClasses, type ButtonSize, type ButtonVariant } from "./Button";
export { Checkbox, type CheckboxProps } from "./Checkbox";
export { CopyButton } from "./CopyButton";
export { ConstructionBanner } from "./ConstructionBanner";
export { DataTable, type Column, type DataTableProps, type SortDirection } from "./DataTable";
export { EmptyState, type EmptyStateProps } from "./EmptyState";
export { ErrorBoundary } from "./ErrorBoundary";
export { FileTypeArt, type FileArtKind } from "./FileTypeArt";
export { FileUpload, type UploadFileItem } from "./FileUpload";
export { FormField, Field, type FormFieldProps } from "./FormField";
export { FramedImage } from "./FramedImage";
export { ItemThumb, NO_PHOTO_PLACEHOLDER_SRC } from "./ItemThumb";
export {
  AttachmentViewer,
  fileTypeLabel,
  formatBytes,
  type ViewableAttachment,
} from "./AttachmentViewer";
export { Modal } from "./Modal";
export {
  useUnsavedWorkGuard,
  useDraftDirty,
  type UnsavedWorkGuard,
} from "./UnsavedWorkGuard";
export {
  NotificationTicker,
  useNotifications,
  type NotificationItem,
} from "./NotificationTicker";
export { TagChip, TAG_COLORS, type TagColor } from "./TagChip";
export { PillTipHost } from "./PillTip";
export {
  OverviewRow,
  OVERVIEW_STATS,
  type InventoryStats,
  type OverviewRowProps,
  type StatDefinition,
} from "./OverviewRow";
export { Pagination } from "./Pagination";
export { PageBlocks, type PageBlocksProps } from "./PageBlocks";
export { AddBlockMenu, type AddMenuItem } from "./AddBlockMenu";
export { Panel, type PanelProps } from "./Panel";
export { SectionHeader, type SectionHeaderProps } from "./SectionHeader";
export {
  SectionPageHeader,
  type SectionPageHeaderProps,
  type SectionPageFact,
} from "./SectionPageHeader";
export { StatCard, type StatCardProps } from "./StatCard";
export { BoxIcon, ChatIcon, CoinIcon, GridIcon, HomeIcon, PinIcon, SwapIcon, TagIcon, UsersIcon } from "./icons";
export { VaultPanel, VaultFrameStack, type VaultPanelProps } from "./VaultPanel";
export { ProgressBar } from "./ProgressBar";
export { DatePicker, type DatePickerProps } from "./DatePicker";
export { Radio, type RadioProps } from "./Radio";
export { SearchBar } from "./SearchBar";
export { Select, type SelectProps } from "./Select";
export { Spinner } from "./Spinner";
export { StickySaveButton } from "./StickySaveButton";
export { AiWorking } from "./AiWorking";
export {
  DetailSkeleton,
  HomeSkeleton,
  InventorySkeleton,
  PageSkeleton,
  QuietSkeleton,
  SkeletonBar,
  SkeletonPanel,
} from "./Skeleton";
export { Tabs, type TabItem } from "./Tabs";
export { TextArea, type TextAreaProps } from "./TextArea";
export { TextInput, type TextInputProps } from "./TextInput";
export { ToastProvider, useToast, type ToastOptions, type ToastTone } from "./Toast";
export { Toggle } from "./Toggle";
export { UserMenu, type UserMenuUser } from "./UserMenu";
export { VisitorPreviewBanner } from "./VisitorPreviewBanner";

/* Legacy style helpers (deprecated; kept for existing imports). */
export { inputStyle, labelStyle, formGridStyle, errorTextStyle } from "./formStyles";
