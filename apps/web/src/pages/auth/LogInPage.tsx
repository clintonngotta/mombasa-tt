import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { logIn } from "@/lib/auth"

export function LogInPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
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

  // One message for unknown email and wrong password, so the form never reveals which accounts exist.
  const failure =
    mutation.error instanceof ApiError && (mutation.error.status === 400 || mutation.error.status === 401)
      ? "That email and password don't match an account."
      : mutation.error && errorMessage(mutation.error)

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
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {failure && <FormAlert>{failure}</FormAlert>}
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
