import { useId } from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

type Option<T extends string> = { value: T; label: string; description?: string }

type ChoiceGroupProps<T extends string> = {
  legend: string
  options: Option<T>[]
  optional?: boolean
  columns?: 2 | 3
} & (
  | { multiple?: false; value: T | ""; onChange: (value: T) => void }
  | { multiple: true; value: T[]; onChange: (value: T[]) => void }
)

/** Native radios/checkboxes styled as chips, so keyboard and screen-reader behaviour stays standard. */
export function ChoiceGroup<T extends string>(props: ChoiceGroupProps<T>) {
  const { legend, options, optional, columns = 2 } = props
  const name = useId()

  const isChecked = (value: T) => (props.multiple ? props.value.includes(value) : props.value === value)

  const toggle = (value: T) => {
    if (props.multiple) {
      props.onChange(isChecked(value) ? props.value.filter((v) => v !== value) : [...props.value, value])
    } else {
      props.onChange(value)
    }
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 font-semibold">
        {legend}
        {optional && <span className="font-normal text-muted-foreground"> (optional)</span>}
      </legend>
      <div className={cn("grid gap-2", columns === 3 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-1 sm:grid-cols-2")}>
        {options.map((option) => {
          const checked = isChecked(option.value)
          return (
            <label
              key={option.value}
              className={cn(
                "relative flex min-h-12 cursor-pointer items-start gap-3 rounded-lg border bg-card px-3 py-3 has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
                checked && "border-brand-blue bg-surface-selected"
              )}
            >
              <input
                type={props.multiple ? "checkbox" : "radio"}
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => toggle(option.value)}
                className="sr-only"
              />
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 flex size-5 shrink-0 items-center justify-center border-2",
                  props.multiple ? "rounded" : "rounded-full",
                  checked ? "border-brand-blue bg-brand-blue text-white" : "border-border"
                )}
              >
                {checked && <Check className="size-3.5" strokeWidth={3} />}
              </span>
              <span className="flex flex-col">
                <span className="font-semibold">{option.label}</span>
                {option.description && <span className="text-sm text-muted-foreground">{option.description}</span>}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
