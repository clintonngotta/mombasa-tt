import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { MailCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { requestPasswordReset } from "@/lib/auth"

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const [invalid, setInvalid] = useState(false)
  const mutation = useMutation({ mutationFn: requestPasswordReset })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const bad = !/^\S+@\S+\.\S+$/.test(email)
    setInvalid(bad)
    if (!bad) mutation.mutate(email.trim())
  }

  const backToLogin = (
    <Link to="/login" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
      Back to log in
    </Link>
  )

  if (mutation.isSuccess) {
    return (
      <AuthLayout
        title="Check your email"
        description="If an account uses that address, we've sent a link to reset its password. The link expires after one hour."
        footer={backToLogin}
      >
        <div className="flex justify-center rounded-xl border bg-card p-6">
          <span className="flex size-14 items-center justify-center rounded-full bg-surface-selected">
            <MailCheck aria-hidden className="size-7 text-brand-blue" />
          </span>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Reset your password"
      description="Enter the email you signed up with and we'll send you a reset link."
      footer={backToLogin}
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {mutation.isError && <FormAlert>{errorMessage(mutation.error)}</FormAlert>}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={invalid ? "Enter a valid email address." : undefined}
        />
        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Sending…" : "Send reset link"}
        </Button>
      </form>
    </AuthLayout>
  )
}
