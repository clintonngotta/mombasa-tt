import { Link, useLocation } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { MailCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { resendVerification } from "@/lib/auth"

export function CheckEmailPage() {
  const { email, next } = (useLocation().state as { email?: string; next?: string } | null) ?? {}
  // A fresh link keeps where the player started, as the first one did.
  const resend = useMutation({ mutationFn: (to: string) => resendVerification(to, next) })

  return (
    <AuthLayout
      title="Check your email"
      description={
        <>
          We sent a verification link to {email ? <strong className="text-foreground">{email}</strong> : "your email address"}.
          Open it to finish creating your account.
        </>
      }
      footer={
        <Link to={next ? `/login?next=${encodeURIComponent(next)}` : "/login"} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
          Back to log in
        </Link>
      }
    >
      <div className="flex flex-col items-center gap-3 rounded-xl border bg-card p-6 text-center">
        <span className="flex size-14 items-center justify-center rounded-full bg-surface-selected">
          <MailCheck aria-hidden className="size-7 text-brand-blue" />
        </span>
        <p className="text-muted-foreground">The link expires after 24 hours. Check spam if it hasn't arrived in a few minutes.</p>
      </div>

      {resend.isError && <FormAlert>{errorMessage(resend.error)}</FormAlert>}
      {resend.isSuccess && (
        <p role="status" className="text-center font-semibold text-success">
          If that address needs verifying, a new link is on its way.
        </p>
      )}
      {email && (
        <Button variant="outline" size="lg" disabled={resend.isPending} onClick={() => resend.mutate(email)}>
          {resend.isPending ? "Sending…" : "Resend link"}
        </Button>
      )}
    </AuthLayout>
  )
}
