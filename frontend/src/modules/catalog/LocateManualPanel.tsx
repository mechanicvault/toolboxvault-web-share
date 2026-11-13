import { Panel } from "../../components";
import { ManualFinder } from "./ManualFinder";

/** The item page's Find-the-manual block (wave 4; re-tiered by
 *  the owner 2026-11-05). The panel shell stays; everything
 *  inside is the SHARED ManualFinder the Add wizard also uses,
 *  so the two surfaces behave identically: proven manuals are
 *  offered as files to pull in, and website links appear only
 *  as the backup tier when no manual could be pulled. */
export function LocateManualPanel({
  segment,
  itemId,
  itemName,
  brand,
  model,
  onSaved,
}: {
  segment: "tools" | "batteries";
  itemId: string;
  itemName: string;
  brand: string;
  model: string;
  onSaved: () => void;
}) {
  return (
    <Panel title="User manual">
      <ManualFinder
        mode="item"
        segment={segment}
        itemId={itemId}
        itemName={itemName}
        brand={brand}
        model={model}
        onSaved={onSaved}
      />
    </Panel>
  );
}
