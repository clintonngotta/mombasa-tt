import { useId, type ComponentProps, type ReactNode } from "react"
import { Label } from "@/components/ui/label"
import { FieldError } from "@/components/forms/Field"

export const CONTROL =
  "w-full rounded-lg border border-input bg-card px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 aria-invalid:border-destructive"

type Shared = { label: string; hint?: ReactNode; error?: string; optional?: boolean }

function Frame({ id, label, hint, error, optional, children }: Shared & { id: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id} className="text-base font-semibold">
        {label}
        {optional && <span className="font-normal text-muted-foreground">(optional)</span>}
      </Label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  )
}

const describedBy = (id: string, hint: ReactNode, error?: string) => [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined

/** A native select with the same label, hint and error treatment as Field. */
export function SelectField({ label, hint, error, optional, children, ...props }: Shared & ComponentProps<"select">) {
  const id = useId()
  return (
    <Frame id={id} label={label} hint={hint} error={error} optional={optional}>
      <select id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} className={`${CONTROL} h-12`} {...props}>
        {children}
      </select>
    </Frame>
  )
}

export function TextAreaField({ label, hint, error, optional, ...props }: Shared & ComponentProps<"textarea">) {
  const id = useId()
  return (
    <Frame id={id} label={label} hint={hint} error={error} optional={optional}>
      <textarea id={id} rows={4} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} className={CONTROL} {...props} />
    </Frame>
  )
}
