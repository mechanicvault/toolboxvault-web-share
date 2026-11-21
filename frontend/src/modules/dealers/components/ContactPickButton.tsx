import { Button } from "../../../components";

/**
 * "Add from contacts" (owner pick 2026-10-18) — the Contact Picker
 * API. It exists on Android Chrome and NOT on iOS Safari (no website
 * can open the iPhone contact list; the future native app will).
 * The button renders ONLY where the API exists — never a dead
 * button. Picking fills the surrounding form; nothing is saved
 * until the user saves the form.
 */
interface ContactInfoLike {
  name?: string[];
  tel?: string[];
  email?: string[];
}

interface ContactsNavigator {
  contacts?: {
    select: (
      properties: string[],
      options?: { multiple?: boolean },
    ) => Promise<ContactInfoLike[]>;
  };
}

export function contactsSupported(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as unknown as ContactsNavigator;
  return typeof nav.contacts?.select === "function";
}

export function ContactPickButton({
  onPick,
}: {
  onPick: (contact: { name?: string; phone?: string; email?: string }) => void;
}) {
  if (!contactsSupported()) return null;
  const nav = navigator as unknown as ContactsNavigator;

  async function pick() {
    try {
      const picked = await nav.contacts!.select(["name", "tel", "email"], {
        multiple: false,
      });
      const contact = picked[0];
      if (!contact) return;
      onPick({
        name: contact.name?.[0],
        phone: contact.tel?.[0],
        email: contact.email?.[0],
      });
    } catch {
      /* user dismissed the picker — nothing to do */
    }
  }

  return (
    <Button type="button" variant="secondary" size="sm" onClick={() => void pick()}>
      Add from contacts
    </Button>
  );
}
