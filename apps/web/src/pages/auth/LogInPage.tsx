import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { logIn } from "@/lib/auth"
import { DEV_ACCOUNTS } from "@/lib/devAccounts"
import { cn } from "@/lib/utils"

export function LogInPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState(DEV_ACCOUNTS[0]?.email ?? "")
  const [password, setPassword] = useState(DEV_ACCOUNTS[0]?.password ?? "")
  const [missing, setMissing] = useState(false)

  const mutation = useMutation({
    mutationFn: logIn,
    onSuccess: () => navigate("/home", { replace: true }),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const incomplete = !email.trim() || !password
    setMissing(incomplete)
    if (!incomplete) mutation.mutate({ email: email.trim(), password })
  }

  // The API already returns one message for unknown email and wrong password (no enumeration).
  const unverified = mutation.error instanceof ApiError && mutation.error.code === "email_unverified"
  const failure = mutation.error && !unverified ? errorMessage(mutation.error) : undefined

  return (
    <AuthLayout
      title="Log in"
      footer={
        <>
          New to mombasa-tt?{" "}
          <Link to="/signup" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {DEV_ACCOUNTS.length > 0 && (
        <div className="flex flex-col gap-2 rounded-xl border border-dashed border-warning/50 bg-card p-3">
          <p className="text-sm font-semibold text-warning">Test accounts (development only)</p>
          <div className="flex flex-wrap gap-2">
            {DEV_ACCOUNTS.map((account) => (
              <button
                key={account.email}
                type="button"
                aria-pressed={email === account.email}
                onClick={() => {
                  setEmail(account.email)
                  setPassword(account.password)
                  mutation.reset()
                }}
                className={cn(
                  "h-12 rounded-lg border px-4 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  email === account.email ? "border-brand-blue bg-surface-selected text-brand-blue" : "bg-card text-muted-foreground"
                )}
              >
                {account.role}
              </button>
            ))}
          </div>
        </div>
      )}
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {failure && <FormAlert>{failure}</FormAlert>}
        {unverified && (
          <FormAlert>
            Verify your email before logging in.{" "}
            <Link
              to="/signup/check-email"
              state={{ email: email.trim() }}
              className="font-semibold underline underline-offset-4"
            >
              Resend the link
            </Link>
          </FormAlert>
        )}
        {missing && <FormAlert>Enter your email and password.</FormAlert>}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <PasswordField
          label="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Link
          to="/forgot-password"
          className="-mt-2 self-end py-2 font-semibold text-brand-blue underline-offset-4 hover:underline"
        >
          Forgot password?
        </Link>
        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </AuthLayout>
  )
}
