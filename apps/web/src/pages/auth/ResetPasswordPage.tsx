import { useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { CircleCheckBig } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { MIN_PASSWORD_LENGTH, confirmPasswordReset } from "@/lib/auth"

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const uid = params.get("uid") ?? ""
  const token = params.get("token") ?? ""
  const [password, setPassword] = useState("")
  const [localError, setLocalError] = useState<string>()

  const mutation = useMutation({ mutationFn: confirmPasswordReset })
  const fieldError = mutation.error instanceof ApiError ? mutation.error.fieldErrors().password : undefined
  const linkInvalid = !uid || !token || (mutation.error instanceof ApiError && mutation.error.code === "invalid_token")

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (password.length < MIN_PASSWORD_LENGTH) {
      setLocalError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    setLocalError(undefined)
    mutation.mutate({ uid, token, password })
  }

  const backToLogin = (
    <Link to="/login" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
      Back to log in
    </Link>
  )

  if (mutation.isSuccess) {
    return (
      <AuthLayout title="Password changed" description="You've been signed out everywhere else. Log in with your new password.">
        <CircleCheckBig aria-hidden className="size-12 text-success" />
        <Link to="/login" className={buttonVariants({ size: "lg" })}>
          Log in
        </Link>
      </AuthLayout>
    )
  }

  if (linkInvalid) {
    return (
      <AuthLayout title="Link not valid" footer={backToLogin}>
        <FormAlert>This reset link is invalid, already used or expired. Request a new one.</FormAlert>
        <Link to="/forgot-password" className={buttonVariants({ size: "lg" })}>
          Send a new link
        </Link>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Choose a new password" footer={backToLogin}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {mutation.isError && !fieldError && <FormAlert>{errorMessage(mutation.error)}</FormAlert>}
        <PasswordField
          label="New password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={localError ?? fieldError}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        />
        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Set new password"}
        </Button>
      </form>
    </AuthLayout>
  )
}
