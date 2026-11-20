import { cn } from "@/lib/utils"

/** A small set of mutually exclusive choices shown side by side. */
export function Segmented<T extends string>({ label, options, value, onChange }: { label: string; options: { value: T; label: string }[]; value: T; onChange: (value: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex w-fit rounded-lg border bg-card p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "h-12 rounded-md px-4 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            value === option.value && "bg-surface-selected text-brand-blue"
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
