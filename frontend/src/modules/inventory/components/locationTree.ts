/** Location tree (Package B) — API calls + tree math shared by the
 *  picker and the manager modal. The tree is the owner's own
 *  toolbox/drawer filing system; the backend derives each filed
 *  item's `location` text from its node's path. */

import { api } from "../../../lib/api";
import type { LocationNode } from "../types";

export function listLocationNodes(): Promise<LocationNode[]> {
  return api<LocationNode[]>("/inventory/location-tree");
}

export function createLocationNode(body: {
  name: string;
  parent_id?: string | null;
  sort_order?: number;
  parent_layout_id?: string | null;
  drawer_index?: number | null;
}): Promise<LocationNode> {
  return api<LocationNode>("/inventory/location-tree", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** AI drawer lookup (2026-10-25, grounded rework same day):
 *  the factory drawer configurations for a toolbox make +
 *  model entered in the lookup's OWN box (the location's name
 *  is never the query), or read off a pasted product-page
 *  link. grounded=true means the configurations came off a
 *  real page (source + source_url name it); grounded=false is
 *  AI recall — ONE configuration, labeled unverified by the
 *  UI. found=false is the honest miss (nothing charged); a
 *  pasted link that can't be read answers link_error instead
 *  of a guess. Errors ride the catalog AI surfaces' codes
 *  (ai_not_configured 503 / insufficient_credits 402 /
 *  ai_provider_error 502) on ApiError.code. */
export interface DrawerConfiguration {
  drawer_count: number;
  extra_sections: string[];
}

export interface DrawerLookupResult {
  found: boolean;
  grounded: boolean;
  drawer_count: number | null;
  source: string | null;
  source_url: string | null;
  configurations: DrawerConfiguration[];
  extra_sections: string[];
  link_error: boolean;
  charged: number;
}

export function lookupDrawers(
  model: string,
  link = "",
): Promise<DrawerLookupResult> {
  return api<DrawerLookupResult>("/inventory/location-tree/drawer-lookup", {
    method: "POST",
    body: JSON.stringify({ model, link }),
  });
}

export function updateLocationNode(
  id: string,
  body: {
    name?: string;
    parent_id?: string | null;
    sort_order?: number;
    parent_layout_id?: string | null;
    drawer_index?: number | null;
  },
): Promise<LocationNode> {
  return api<LocationNode>(`/inventory/location-tree/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** Delete a node. An occupied node (items and/or child nodes) needs
 *  a decision: `{reassign_to_id}` moves everything, `{detach: true}`
 *  unfiles items and lifts children to the deleted node's parent.
 *  Without one the backend 422s with friendly copy in `detail`. */
export function deleteLocationNode(
  id: string,
  decision: { reassign_to_id: string } | { detach: true },
): Promise<void> {
  return api<void>(`/inventory/location-tree/${id}`, {
    method: "DELETE",
    body: JSON.stringify(decision),
  });
}

export interface LocationTreeNode extends LocationNode {
  children: LocationTreeNode[];
  depth: number;
}

/** Nest the flat node list into a tree (roots first), children
 *  ordered by sort_order then name — mirrors the Used Parts page's
 *  buildTree pattern, adapted for this module's node shape. */
export function buildLocationTree(nodes: LocationNode[]): LocationTreeNode[] {
  const byId = new Map<string, LocationTreeNode>(
    nodes.map((n) => [n.id, { ...n, children: [], depth: 0 }]),
  );
  const roots: LocationTreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sortLevel = (level: LocationTreeNode[], depth: number) => {
    // Drawers first in their grid order (audit A3): a node with a
    // drawer_index sorts by it ahead of the plain sort_order/name
    // order its siblings use.
    level.sort(
      (a, b) =>
        (a.drawer_index ?? Number.MAX_SAFE_INTEGER) -
          (b.drawer_index ?? Number.MAX_SAFE_INTEGER) ||
        a.sort_order - b.sort_order ||
        a.name.localeCompare(b.name),
    );
    for (const node of level) {
      node.depth = depth;
      sortLevel(node.children, depth + 1);
    }
  };
  sortLevel(roots, 0);
  return roots;
}

/** The flat list in tree order (roots first, depth-first) — the
 *  order select options render in, with `depth` for indenting. */
export function flattenLocationTree(
  nodes: LocationNode[],
): LocationTreeNode[] {
  const out: LocationTreeNode[] = [];
  const walk = (level: LocationTreeNode[]) => {
    for (const node of level) {
      out.push(node);
      walk(node.children);
    }
  };
  walk(buildLocationTree(nodes));
  return out;
}

/** Depth of one node, computed from its parent chain. */

/** Ids a node may NOT be moved/reassigned into: itself + subtree. */
export function locationSubtreeIds(
  nodes: LocationNode[],
  rootId: string,
): Set<string> {
  const children = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.parent_id) {
      const list = children.get(node.parent_id) ?? [];
      list.push(node.id);
      children.set(node.parent_id, list);
    }
  }
  const found = new Set<string>();
  const stack = [rootId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    if (found.has(id)) continue;
    found.add(id);
    stack.push(...(children.get(id) ?? []));
  }
  return found;
}

/** Select-option label for a node: its name indented by depth.
 *  Clean treatment (owner, 2026-10-25): growing whitespace per
 *  tier plus ONE quiet "›" marker on nested rows — the old
 *  bar-and-arrow glyph ("\u21B3") read as a stray graphic in
 *  every dropdown. Native <option> text can't be styled per
 *  part, so the marker stays a plain character and the indent
 *  does the real work. */
export function indentedNodeLabel(node: LocationTreeNode): string {
  if (node.depth <= 0) return node.name;
  return `${"\u00A0\u00A0\u00A0".repeat(node.depth)}\u203A ${node.name}`;
}
