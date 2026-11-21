import { ArtIcon } from "../../../components/ArtIcon";
import { ConverterBody } from "../DownloadsConverter";
import type { WidgetDef } from "./shared";
import { line } from "./shared";

export const converterWidget: WidgetDef = {
    icon: <ArtIcon name="converter" size={24} />,
    tone: "info",
    cta: "open",
    path: "/downloads#documents",
    load: async (t, ctx) => {
      // Converter widget (owner 2026-11-08): NOT a module widget —
      // the Downloads converter as a pinnable Home widget, seated
      // as its own block in CorePage (the board-widgets pattern)
      // but rendered through this frame like every module widget.
      // The body is the SAME ConverterBody the Downloads panel
      // renders: one component, one math, nothing to drift. It
      // rides the actions slot (the truck quick entry's seat),
      // above the whole-box cover, so its fields take real
      // clicks. In Edit view the frame hides the actions slot —
      // the load then answers with the converter's own sub as a
      // line, so the box describes itself while it is arranged.
      if (ctx?.editing) {
        return {
          lines: [
            line(
              t,
              "downloads.conv.sub",
              "The readings a shop converts every day — pick a kind, type a number, get the rest.",
            ),
          ],
        };
      }
      return {
        lines: [],
        actions: (
          <ConverterBody variant="widget" size={ctx?.size ?? "half"} />
        ),
      };
    },
  };
