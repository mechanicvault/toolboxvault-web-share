import { useEffect, useId, useState } from "react";
import { TextInput } from "../../../components";
import { api } from "../../../lib/api";

/** Self-learning field suggestions (Package B): a text input with a
 *  datalist fed from GET /inventory/suggestions?field=… — the
 *  caller's own distinct values for that field. Free entry is
 *  always allowed (that's how the vocabulary learns); a failed
 *  fetch just means no suggestions, never a blocked form. Mirrors
 *  the datalist pattern the item forms already use. */
export function FieldSuggest({
  field,
  value,
  onChange,
  id,
  placeholder,
}: {
  field: "brand" | "category" | "size" | "tag";
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
}) {
  const autoId = useId();
  const inputId = id ?? `fs-${field}-${autoId}`;
  const listId = `${inputId}-list`;
  const [options, setOptions] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    api<string[]>(`/inventory/suggestions?field=${field}`)
      .then((rows) => {
        if (live) setOptions(rows);
      })
      .catch(() => {
        if (live) setOptions([]);
      });
    return () => {
      live = false;
    };
  }, [field]);

  return (
    <>
      <TextInput
        id={inputId}
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      <datalist id={listId}>
        {options.map((option) => (
          <option key={option} value={option} />
        ))}
      </datalist>
    </>
  );
}
