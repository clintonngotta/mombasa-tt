import { useId, type ComponentProps, type ReactNode } from "react"
import { Combobox } from "@base-ui/react/combobox"
import { Check, ChevronsUpDown } from "lucide-react"
import { Label } from "@/components/ui/label"
import { FieldError } from "@/components/forms/Field"
import { cn } from "@/lib/utils"

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

/** `badge` is a short word shown beside the label (a club or a team, say); searching uses the label. */
type SelectOption = { value: string; label: string; disabled?: boolean; badge?: ReactNode }

type SearchSelectProps = Pick<ComponentProps<"button">, "id" | "aria-label" | "aria-describedby" | "aria-invalid" | "className" | "disabled"> & {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

/** A select whose open list can be searched with the keyboard or pointer. */
export function SearchSelect({ options, value, onChange, placeholder = "Choose an option", disabled, className, ...triggerProps }: SearchSelectProps) {
  const chosen = options.find((option) => option.value === value)
  return (
    <Combobox.Root
      items={options}
      value={options.find((option) => option.value === value) ?? null}
      onValueChange={(option) => { if (option) onChange(option.value) }}
      disabled={disabled}
      autoHighlight
    >
      <Combobox.Trigger type="button" className={cn(CONTROL, "flex h-12 min-w-0 items-center justify-between gap-2 text-left", className)} {...triggerProps}>
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate"><Combobox.Value placeholder={placeholder} /></span>
          {chosen?.badge}
        </span>
        <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      </Combobox.Trigger>
      <Combobox.Portal>
        <Combobox.Positioner align="start" sideOffset={4} className="z-50">
          <Combobox.Popup className="flex max-h-[var(--available-height)] w-[var(--anchor-width)] min-w-44 max-w-[var(--available-width)] flex-col gap-1 overflow-hidden rounded-lg border bg-card p-1.5 text-card-foreground shadow-md">
            <Combobox.Input
              aria-label="Search options"
              placeholder="Search options"
              className={cn(CONTROL, "h-10 shrink-0")}
            />
            <Combobox.Empty className="px-2 py-2 text-sm text-muted-foreground">No matching options.</Combobox.Empty>
            <Combobox.List className="max-h-60 overflow-y-auto overscroll-contain">
              {(option: SelectOption) => (
                <Combobox.Item
                  key={option.value}
                  value={option}
                  disabled={option.disabled}
                  className="flex min-h-10 cursor-default items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm data-highlighted:bg-accent data-highlighted:text-accent-foreground data-disabled:opacity-50"
                >
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="min-w-0 break-words">{option.label}</span>
                    {option.badge}
                  </span>
                  <Combobox.ItemIndicator><Check aria-hidden className="size-4" /></Combobox.ItemIndicator>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  )
}

export function SelectField({ label, hint, error, optional, ...props }: Shared & SearchSelectProps) {
  const id = useId()
  return (
    <Frame id={id} label={label} hint={hint} error={error} optional={optional}>
      <SearchSelect id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...props} />
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
