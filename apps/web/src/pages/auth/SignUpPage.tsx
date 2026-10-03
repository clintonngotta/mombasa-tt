import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { MIN_PASSWORD_LENGTH, signUp } from "@/lib/auth"

export function SignUpPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ display_name: "", email: "", password: "" })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const mutation = useMutation({
    mutationFn: signUp,
    onSuccess: () => navigate("/signup/check-email", { state: { email: form.email } }),
    onError: (error) => {
      if (error instanceof ApiError) setErrors(error.fieldErrors())
    },
  })

  const set = (field: keyof typeof form) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [field]: e.target.value }))
    setErrors(({ [field]: _removed, ...rest }) => rest)
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (!form.display_name.trim()) next.display_name = "Enter the name other players will see."
    if (!/^\S+@\S+\.\S+$/.test(form.email)) next.email = "Enter a valid email address."
    if (form.password.length < MIN_PASSWORD_LENGTH) next.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`
    setErrors(next)
    if (Object.keys(next).length === 0) mutation.mutate({ ...form, display_name: form.display_name.trim() })
  }

  const fieldErrorShown = Object.keys(errors).length > 0
  return (
    <AuthLayout
      title="Create your account"
      description="One player profile works across every club and tournament on mombasa-tt."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {mutation.isError && !fieldErrorShown && <FormAlert>{errorMessage(mutation.error)}</FormAlert>}
        <Field
          label="Display name"
          autoComplete="name"
          value={form.display_name}
          onChange={set("display_name")}
          error={errors.display_name}
          hint="Shown on draws, results and the player directory if you join it."
        />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={form.email}
          onChange={set("email")}
          error={errors.email}
        />
        <PasswordField
          label="Password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          error={errors.password}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        />
        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  )
}
