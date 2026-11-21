/** The blocked member's notice (admin lane, owner ruling
 *  2026-11-06): when a god / moderator_admin seat has blocked
 *  the signed-in member from a community feature, the feature's
 *  pages say so at the top — which feature, and the road back
 *  (open a support ticket and ask for reinstatement). The
 *  inbox notice and the post-time refusal carry the same words;
 *  this is the third leg, so the member is never left guessing
 *  why the buttons stopped working. Renders nothing when the
 *  member isn't blocked from the named feature.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert } from "../../components";
import { getMyBlocks } from "./api";
import type { CommunityBlock } from "./types";

export function BlockedNotice({ feature }: { feature: string }) {
  const [block, setBlock] = useState<CommunityBlock | null>(null);

  useEffect(() => {
    let live = true;
    getMyBlocks()
      .then((rows) => {
        if (live) setBlock(rows.find((row) => row.feature === feature) ?? null);
      })
      .catch(() => {
        if (live) setBlock(null);
      });
    return () => {
      live = false;
    };
  }, [feature]);

  if (!block) return null;
  return (
    <Alert tone="warning">
      You're blocked from {block.feature_label} right now, so you can't post
      or reply there. Everything else on your account works as usual.
      {block.reason ? ` Reason given: ${block.reason}.` : ""} If you think
      that's wrong, <Link to="/help#tickets">open a support ticket</Link> and
      ask for your access back — the team can review it there.
    </Alert>
  );
}
