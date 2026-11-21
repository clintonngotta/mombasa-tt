import { useEffect } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { LoaderCircle } from "lucide-react"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { verifyEmail } from "@/lib/auth"
import { rememberReturn } from "@/lib/onboarding"

export function VerifyEmailPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get("token") ?? ""
  const next = params.get("next")
  const { mutate, isError, error } = useMutation({
    mutationFn: verifyEmail,
    // Verifying signs the player in; onboarding picks up from there and ends where they started.
    onSuccess: () => {
      rememberReturn(next)
      navigate("/onboarding/profile", { replace: true })
    },
  })

  useEffect(() => {
    if (token) mutate(token)
  }, [token, mutate])

  if (!token || isError) {
    return (
      <AuthLayout
        title="Link not valid"
        footer={
          <Link to="/login" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Back to log in
          </Link>
        }
      >
        <FormAlert>
          {token ? errorMessage(error) : "This verification link is incomplete."} Log in with your email and
          password to get a fresh link.
        </FormAlert>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Verifying your email">
      <p role="status" className="flex items-center gap-2 text-muted-foreground">
        <LoaderCircle aria-hidden className="size-5 animate-spin" />
        One moment…
      </p>
    </AuthLayout>
  )
}
