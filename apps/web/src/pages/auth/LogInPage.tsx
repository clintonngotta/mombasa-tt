import { useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { logIn } from "@/lib/auth"
import { meQueryKey, safeNext } from "@/lib/session"
import { getProfile, profileKeys } from "@/lib/profile"

export function LogInPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const requested = useSearchParams()[0].get("next")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [missing, setMissing] = useState(false)

  const mutation = useMutation({
    mutationFn: async (credentials: Parameters<typeof logIn>[0]) => {
      const user = await logIn(credentials)
      // A player who left onboarding unfinished picks it up again, unless they were heading somewhere.
      // If the profile can't be read, just carry on to the app.
      const profile = requested ? null : await getProfile().catch(() => null)
      return { user, profile }
    },
    onSuccess: ({ user, profile }) => {
      queryClient.setQueryData(meQueryKey, user)
      if (profile) queryClient.setQueryData(profileKeys.me, profile)
      navigate(profile && !profile.onboarding_completed ? "/onboarding/profile" : safeNext(requested), { replace: true })
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const incomplete = !email.trim() || !password
    setMissing(incomplete)
    if (!incomplete) mutation.mutate({ login: email.trim(), password })
  }

  // The API already returns one message for an unknown email or phone and a wrong password (no enumeration).
  const unverified = mutation.error instanceof ApiError && mutation.error.code === "email_unverified"
  const failure = mutation.error && !unverified ? errorMessage(mutation.error) : undefined

  return (
    <AuthLayout
      title="Log in"
      footer={
        <>
          New to Coast TT?{" "}
          <Link to="/signup" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {failure && <FormAlert>{failure}</FormAlert>}
        {unverified && (
          <FormAlert>
            Verify your email before logging in.{" "}
            <Link
              to="/signup/check-email"
              state={{ email: email.includes("@") ? email.trim() : "" }}
              className="font-semibold underline underline-offset-4"
            >
              Resend the link
            </Link>
          </FormAlert>
        )}
        {missing && <FormAlert>Enter your email or phone number, and your password.</FormAlert>}
        <Field
          label="Email or phone number"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          hint="A phone number works if it's on your account, for example 0712 345 678."
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
