import { useId } from "react"
import { Label } from "@/components/ui/label"

export const BIO_MAX = 280

export function BioField({ value, onChange, error }: { value: string; onChange: (value: string) => void; error?: string }) {
  const id = useId()
  const errorId = `${id}-error`
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id} className="text-base font-semibold">
        Bio <span className="font-normal text-muted-foreground">(optional)</span>
      </Label>
      <textarea
        id={id}
        rows={3}
        maxLength={BIO_MAX}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-input bg-card px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
      />
      {error ? (
        <p id={errorId} className="text-sm text-destructive">
          {error}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground tabular">
          {value.length}/{BIO_MAX}
        </p>
      )}
    </div>
  )
}
