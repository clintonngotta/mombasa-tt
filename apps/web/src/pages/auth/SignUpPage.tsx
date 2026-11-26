import { useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { LocationFields } from "@/components/forms/LocationFields"
import { ApiError, errorMessage } from "@/lib/api"
import { MIN_PASSWORD_LENGTH, signUp } from "@/lib/auth"
import { safeNext } from "@/lib/session"
import { EMPTY_LOCATION, locationErrors } from "@/lib/geography"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { isSignUpAs, SIGN_UP_AS, type SignUpAs } from "@/lib/onboarding"

export function SignUpPage() {
  const navigate = useNavigate()
  // Where they came from, such as an event to enter: the verification link and "Log in" both keep it.
  const [params] = useSearchParams()
  const returnTo = safeNext(params.get("next"), "")
  const asParam = params.get("as")
  const [signUpAs, setSignUpAs] = useState<SignUpAs>(isSignUpAs(asParam) ? asParam : "player")
  const [form, setForm] = useState({ display_name: "", email: "", password: "", ...EMPTY_LOCATION })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const mutation = useMutation({
    mutationFn: signUp,
    onSuccess: () => navigate("/signup/check-email", { state: { email: form.email, next: returnTo } }),
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
    const next = locationErrors(form)
    if (!form.display_name.trim()) next.display_name = "Enter the name other players will see."
    if (!/^\S+@\S+\.\S+$/.test(form.email)) next.email = "Enter a valid email address."
    if (form.password.length < MIN_PASSWORD_LENGTH) next.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`
    setErrors(next)
    // A coach, club or facility goes on to set that up after onboarding; a player goes back where they came from.
    const after = SIGN_UP_AS.find((option) => option.value === signUpAs)?.next ?? returnTo
    if (Object.keys(next).length === 0) mutation.mutate({ ...form, display_name: form.display_name.trim(), ...(after && { next: after }) })
  }

  const fieldErrorShown = Object.keys(errors).length > 0
  return (
    <AuthLayout
      title="Create your account"
      description="One account works across every club and tournament on Coast TT."
      footer={
        <>
          Already have an account?{" "}
          <Link to={returnTo ? `/login?next=${encodeURIComponent(returnTo)}` : "/login"} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {mutation.isError && !fieldErrorShown && <FormAlert>{errorMessage(mutation.error)}</FormAlert>}
        <ChoiceGroup legend="I'm signing up as" options={SIGN_UP_AS.map(({ value, label, description }) => ({ value, label, description }))} value={signUpAs} onChange={setSignUpAs} />
        <p className="-mt-2 text-sm text-muted-foreground">
          {signUpAs === "player"
            ? "You can become a coach or register a club or facility later."
            : "You get a player account first, then we take you to set this up."}{" "}
          Regional and national officials are added by the platform admin.
        </p>
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
        <LocationFields
          value={form}
          onChange={(location) => {
            setForm((prev) => ({ ...prev, ...location }))
            setErrors(({ country: _country, region: _region, city: _city, ...rest }) => rest)
          }}
          errors={errors}
        />
        <p className="text-sm text-muted-foreground">Your location counts toward geographic rankings. Other players won’t see it on your profile.</p>
        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  )
}
