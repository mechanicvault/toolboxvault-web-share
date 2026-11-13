import type { ReactNode } from "react";

import AccountDataSettings from "./AccountDataSettings";
import AiCreditsSettings from "./AiCreditsSettings";
import CloudBackupSettings from "./CloudBackupSettings";
import CrewSettings from "./CrewSettings";
import InsurerProfileSettings from "./InsurerProfileSettings";
import MyShopSettings from "./MyShopSettings";
import { BillingPlanSettings, RedeemReferralsSettings } from "./BillingSettings";
import CustomFieldsSettings from "./CustomFieldsSettings";
import DealerProfileSettings from "../dealers/DealerProfileSettings";
import DealerListSettings from "../dealers/DealerListSettings";
import HistorySettings from "./HistorySettings";
import ImportMatchingSettings from "../inventory/ImportMatchingSettings";
import InsuranceSettings from "./InsuranceSettings";
import ModulesSettings from "./ModulesSettings";
import SetupSettings from "./SetupSettings";
import SharingSettings from "./SharingSettings";
import WizardDefaultsSettings from "./WizardDefaultsSettings";
import {
  sectionVisibleFor,
  SETTINGS_SECTIONS,
  type SettingsSectionMeta,
} from "./settingsMeta";
import {
  AppearanceSection,
  NotificationsSection,
  ProfileSection,
  PublicProfileSection,
  SecuritySection,
} from "./settingsSections";
import type { User } from "./AuthContext";

/**
 * SETTINGS SECTION REGISTRY (settings restructure, owner review
 * round 1, 2026-10-19): the section metadata (settingsMeta.ts —
 * id, label, group, dealer gating) mapped to the component that
 * renders it. The shell (SettingsPage) renders ONE registered
 * section per route; the gear menu and the sidebar accordion link
 * the same ids. Later packages register a section by adding one
 * meta entry + one line here.
 *
 * Plan & billing's section renders the plan panel with the AI
 * credits wallet directly under it (the owner's grouping: the
 * wallet is part of the plan surface); redeem & referrals is its
 * own section next door.
 */
export interface SettingsSection extends SettingsSectionMeta {
  render: (user: User) => ReactNode;
}

const RENDERERS: Record<string, (user: User) => ReactNode> = {
  profile: (user) => <ProfileSection user={user} />,
  setup: () => <SetupSettings />,
  security: (user) => <SecuritySection user={user} />,
  billing: () => (
    <>
      <BillingPlanSettings />
      <AiCreditsSettings />
    </>
  ),
  insurance: () => <InsuranceSettings />,
  redeem: (user) => (
    <RedeemReferralsSettings accountNumber={user.account_number} />
  ),
  history: () => <HistorySettings />,
  "import-matching": () => <ImportMatchingSettings />,
  "cloud-backup": () => <CloudBackupSettings />,
  data: () => <AccountDataSettings />,
  modules: () => <ModulesSettings />,
  appearance: () => <AppearanceSection />,
  sharing: () => <SharingSettings />,
  "custom-fields": () => <CustomFieldsSettings />,
  "wizard-defaults": () => <WizardDefaultsSettings />,
  "dealer-list": () => <DealerListSettings />,
  "dealer-profile": () => <DealerProfileSettings />,
  crew: () => <CrewSettings />,
  "my-shop": () => <MyShopSettings />,
  "insurer-profile": () => <InsurerProfileSettings />,
  "public-profile": (user) => <PublicProfileSection user={user} />,
  notifications: () => <NotificationsSection />,
};

export const SETTINGS_REGISTRY: SettingsSection[] = SETTINGS_SECTIONS.map(
  (meta) => ({
    ...meta,
    render: RENDERERS[meta.id] ?? (() => null),
  }),
);

/** The sections this user actually gets (group-gated and
 * reach-gated ones hide — settings follow reach, 2026-11-09;
 * `modules` is the caller's effective module set, the nav's own
 * authority, or an empty set while that read is in flight). */
export function visibleSettingsSections(
  user: User,
  modules?: ReadonlySet<string>,
  bareRung = false,
): SettingsSection[] {
  return SETTINGS_REGISTRY.filter((s) =>
    sectionVisibleFor(s, user.account_types, modules, bareRung),
  );
}

export function settingsSectionById(
  user: User,
  id: string | undefined,
  modules?: ReadonlySet<string>,
  bareRung = false,
): SettingsSection | undefined {
  return visibleSettingsSections(user, modules, bareRung).find(
    (s) => s.id === id,
  );
}
