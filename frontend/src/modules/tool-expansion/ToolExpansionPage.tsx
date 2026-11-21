import { Navigate, useLocation } from "react-router-dom";

/**
 * The retired standalone Tool Expansion page's address
 * (/tool-expansion) lands here now (owner order, sheet row
 * 134, 2026-11-18: the whole page moved into the Inventory
 * page's EXPAND tab and the main-menu entry is gone). Old
 * links — bookmarks, the Home widget's doors, item-page
 * sections — translate and replace themselves:
 *
 * - ?kind=&id= (a scoped arrival from the inventory badge /
 *   item page) keeps its params, landing on the EXPAND tab
 *   scoped to that item;
 * - #matches / #archived become ?xsec= so the EXPAND tab
 *   opens on the same section the link named;
 * - anything else lands on the EXPAND tab's first section.
 */
export default function ToolExpansionPage() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const kind = params.get("kind");
  const id = params.get("id");
  const scoped =
    (kind === "tool" || kind === "battery") && id
      ? `?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`
      : "";
  const hash = location.hash.replace(/^#/, "");
  const section =
    !scoped && (hash === "matches" || hash === "archived")
      ? `?xsec=${hash}`
      : "";
  return <Navigate to={`/inventory${scoped || section}#expand`} replace />;
}
