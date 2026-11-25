import { useState, type FormEvent } from "react"
import { useMutation } from "@tanstack/react-query"
import { Mail } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { addEmail } from "@/lib/auth"
import { useMe } from "@/lib/session"

/** For a player who signs in by phone only (added by an organizer): ask for an email address, so match
 * calls, schedule changes and results also reach them by email. Hidden once the account has one. */
export function AddEmailPrompt() {
  const me = useMe()
  const [email, setEmail] = useState("")
  const send = useMutation({ mutationFn: () => addEmail(email.trim()) })
  if (!me.data || me.data.email) return null
  const fields: Record<string, string | undefined> = send.error instanceof ApiError ? send.error.fieldErrors() : {}

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    send.mutate()
  }

  return (
    <section aria-labelledby="add-email-heading" className="flex flex-col gap-3 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <h2 id="add-email-heading" className="flex items-center gap-2 text-xl font-bold">
        <Mail aria-hidden className="size-5 text-brand-blue" /> Add your email
      </h2>
      {send.isSuccess ? (
        <p role="status">
          Check <span className="font-semibold">{email.trim()}</span> for a link from us and open it to finish. Until then you keep logging in with your phone number.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <p>You log in with your phone number. Add an email to get match calls, schedule changes and results by email too, and to log in with either.</p>
          {send.isError && !fields.email && <FormAlert>{errorMessage(send.error, "We couldn't send the link. Try again.")}</FormAlert>}
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Email" type="email" autoComplete="email" className="min-w-56 flex-1" value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email} />
            <Button type="submit" disabled={!email.trim() || send.isPending}>
              {send.isPending ? "Sending…" : "Send me the link"}
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}
