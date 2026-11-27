import { useId } from "react"
import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/** A search field that filters a list as you type. */
export function SearchBox({ label, value, onChange, placeholder, className }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; className?: string }) {
  const id = useId()
  return (
    <div role="search" className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted-foreground" />
        <Input id={id} type="search" maxLength={100} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} className="pl-10" />
      </div>
    </div>
  )
}
