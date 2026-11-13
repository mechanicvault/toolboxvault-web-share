import { Checkbox, DatePicker, FormField, Select, TextInput } from "../../../components";
import type { FieldDefinition } from "../types";

interface Props {
  def: FieldDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  error?: string;
}

/** Renders the right shared control for a custom field definition's type. */
export function CustomFieldInput({ def, value, onChange, error }: Props) {
  const id = `cf-${def.id}`;

  if (def.field_type === "boolean") {
    return (
      <div className="tv-field">
        <Checkbox
          id={id}
          label={
            <>
              {def.label}
              {def.required && (
                <span className="tv-field-required" aria-hidden="true">
                  {" "}
                  *
                </span>
              )}
            </>
          }
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
        {error && (
          <p role="alert" className="tv-field-error">
            {error}
          </p>
        )}
      </div>
    );
  }

  let control: React.ReactNode;
  switch (def.field_type) {
    case "number":
      control = (
        <TextInput
          id={id}
          type="number"
          step="any"
          invalid={Boolean(error)}
          value={typeof value === "number" ? value : ""}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      );
      break;
    case "date":
      control = (
        <DatePicker
          id={id}
          invalid={Boolean(error)}
          value={typeof value === "string" ? value : ""}
          onChange={(v) => onChange(v || null)}
          clearable
        />
      );
      break;
    case "dropdown":
      control = (
        <Select
          id={id}
          invalid={Boolean(error)}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value || null)}
        >
          <option value="">— Select —</option>
          {def.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
      );
      break;
    case "text":
    default:
      control = (
        <TextInput
          id={id}
          type="text"
          invalid={Boolean(error)}
          value={typeof value === "string" ? value : String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
      break;
  }

  return (
    <FormField label={def.label} htmlFor={id} required={def.required} error={error}>
      {control}
    </FormField>
  );
}
