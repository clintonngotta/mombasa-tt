import { useState, type FormEvent } from "react"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { ApiError, errorMessage } from "@/lib/api"
import type { FieldValue, FieldValues, MemberField } from "@/lib/clubs"

/** A field with its value: member fields (REQ-005) and committee fields (REQ-045) both have this shape. */
type Entry = { field: Pick<MemberField, "id" | "label" | "kind" | "options" | "required" | "visibility">; value: FieldValue }

// Inputs hold strings; yes/no fields hold "yes", "no" or "" (unanswered).
type Draft = Record<string, string>

function toDraft(value: FieldValue): string {
  if (value === null) return ""
  if (typeof value === "boolean") return value ? "yes" : "no"
  return String(value)
}

function fromDraft(entry: Entry, text: string): FieldValue {
  const trimmed = text.trim()
  if (trimmed === "") return null
  if (entry.field.kind === "boolean") return trimmed === "yes"
  if (entry.field.kind === "number") {
    // JSON can't carry Infinity or NaN (they become null, which would clear the answer), so send the
    // text and let the server explain.
    const number = Number(trimmed)
    return Number.isFinite(number) ? number : trimmed
  }
  return trimmed
}

/**
 * Edits a member's custom field values (REQ-005). Used by staff for any member and by members for their
 * own member-visible fields; `entries` is whatever the server chose to show this viewer. Also edits a
 * committee position's values (REQ-045).
 */
export function MemberFieldValuesForm<E extends Entry, R>({
  entries,
  save,
  onSaved,
  onCancel,
  markStaffOnly,
  submitLabel = "Save details",
}: {
  entries: E[]
  save: (values: FieldValues) => Promise<R>
  onSaved?: (saved: R) => void
  onCancel?: () => void
  /** Staff view: point out the fields the member can't see. */
  markStaffOnly?: boolean
  submitLabel?: string
}) {
  // Only what the person has typed since the last save; untouched fields follow the server's answers.
  const [draft, setDraft] = useState<Draft>({})
  const set = (id: string, text: string) => setDraft((current) => ({ ...current, [id]: text }))
  const shown = (entry: E) => draft[entry.field.id] ?? toDraft(entry.value)

  const mutation = useMutation({
    mutationFn: () => {
      // Send what changed, plus required fields still empty so the server can say so.
      const values: FieldValues = {}
      for (const entry of entries) {
        const next = fromDraft(entry, shown(entry))
        if (next !== entry.value || (next === null && entry.field.required)) values[entry.field.id] = next
      }
      return save(values)
    },
    onSuccess: (saved) => {
      setDraft({})
      onSaved?.(saved)
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }

  const errors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {}
  const hasFieldErrors = entries.some((entry) => errors[entry.field.id])

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-4" noValidate>
      {entries.map((entry) => {
        const { field } = entry
        const staffOnly = markStaffOnly && field.visibility === "staff"
        const value = shown(entry)
        const error = errors[field.id]
        if (field.kind === "boolean" || field.kind === "choice") {
          const options =
            field.kind === "boolean"
              ? [
                  { value: "yes", label: "Yes" },
                  { value: "no", label: "No" },
                ]
              : field.options.map((option) => ({ value: option, label: option }))
          return (
            <ChoiceGroup
              key={field.id}
              legend={staffOnly ? `${field.label} · staff only` : field.label}
              optional={!field.required}
              columns={3}
              options={options}
              value={value}
              onChange={(next) => set(field.id, next)}
              onClear={field.required ? undefined : () => set(field.id, "")}
              error={error}
            />
          )
        }
        return (
          <Field
            key={field.id}
            label={field.label}
            optional={!field.required}
            type={field.kind === "text" ? "text" : field.kind}
            inputMode={field.kind === "number" ? "decimal" : undefined}
            step={field.kind === "number" ? "any" : undefined}
            maxLength={field.kind === "text" ? 500 : undefined}
            value={value}
            onChange={(e) => set(field.id, e.target.value)}
            hint={staffOnly ? "Staff only. The member doesn't see this." : undefined}
            error={error}
          />
        )
      })}
      {mutation.isError && !hasFieldErrors && <FormAlert>{errorMessage(mutation.error)}</FormAlert>}
      {mutation.isSuccess && Object.keys(draft).length === 0 && (
        <p role="status" className="text-sm text-success">
          Saved.
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Close
          </Button>
        )}
      </div>
    </form>
  )
}
