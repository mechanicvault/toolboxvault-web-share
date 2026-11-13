/** Flyers module wire types (backend: app/modules/flyers). */

export interface FlyerView {
  id: string;
  label: string;
  page_count: number;
  origin: "link" | "upload" | "photos" | "standing";
  starts_on: string;
  ends_on: string;
  thumb_url: string | null;
  pdf_url: string | null;
  is_current: boolean;
  created_at: string;
}

export interface FlyerSource {
  id: string | null;
  key: string;
  kind: "company" | "agent";
  company_id: string;
  company_name: string;
  agent_user_id: string | null;
  private_agent_id: string | null;
  agent_name: string;
  visible: boolean;
  history_visible: boolean;
  standing_url: string;
  can_post: boolean;
  current: FlyerView | null;
  history: FlyerView[];
}

export interface CompanyFlyers {
  company_id: string;
  sources: FlyerSource[];
  postable: FlyerSource[];
}

export interface DetectedPage {
  key: string;
  width: number;
  height: number;
  corners: number[][];
  detected: boolean;
}

/** One scanned page ready to assemble: its staged photo + the
 *  (possibly user-nudged) corners, normalized TL/TR/BR/BL. */
export interface ScanPage {
  key: string;
  corners: number[][];
}

/** The name a source's tab/row shows: the agent's name rides
 *  with the company so two agents of one dealer read apart. */
export function sourceTitle(source: FlyerSource): string {
  return source.agent_name
    ? `${source.agent_name} · ${source.company_name}`
    : source.company_name;
}
