import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Trophy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AuthLayout } from "@/components/layout/AuthLayout"
import { Field, FormAlert, PasswordField } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { MIN_PASSWORD_LENGTH } from "@/lib/auth"
import { claimByLink, getInvitation, invitationKeys, joinFromInvitation, type InvitationDetail } from "@/lib/guests"
import { getMe, meQueryKey, useMe } from "@/lib/session"

const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" })

/**
 * An invitation link (REQ-003). An organizer entered this player before they had an account and sent
 * them this link by email, WhatsApp or SMS. Somebody new sets their own details and password and the
 * entries are theirs at once; somebody already on Coast TT logs in and adds them to their account.
 */
export function JoinPage() {
  const token = useParams().token ?? ""
  const me = useMe()
  const invitation = useQuery({ queryKey: invitationKeys.detail(token), queryFn: () => getInvitation(token), retry: false })
  const next = `/join/${encodeURIComponent(token)}`
  const member = !!invitation.data?.is_member

  return (
    <AuthLayout
      title={
        !invitation.data ? "Your invitation" : member ? `Welcome to ${invitation.data.organization_name}` : "You've been entered"
      }
      description={
        invitation.data
          ? member
            ? `${invitation.data.organization_name} added you as a member. Set your password to sign in.`
            : `${invitation.data.organization_name} added you to Coast TT. Join to see your entries and check your details.`
          : undefined
      }
      footer={
        !me.data &&
        invitation.data && (
          <>
            Already on Coast TT?{" "}
            <Link to={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
              {member ? "Log in to add the membership to your account" : "Log in to add these to your account"}
            </Link>
          </>
        )
      }
    >
      {invitation.isPending && <p className="text-muted-foreground">Opening your invitation…</p>}
      {invitation.isError && (
        <FormAlert>
          {invitation.error instanceof ApiError && invitation.error.status === 404
            ? "This invitation link has been used, withdrawn or has expired. Ask the organizer for a new one."
            : errorMessage(invitation.error, "We couldn't open this invitation.")}
        </FormAlert>
      )}
      {invitation.data && (
        <>
          <Entered invitation={invitation.data} />
          {me.data ? <ClaimForAccount token={token} name={me.data.display_name} member={member} /> : <JoinForm token={token} invitation={invitation.data} />}
        </>
      )}
    </AuthLayout>
  )
}

function Entered({ invitation }: { invitation: InvitationDetail }) {
  return (
    <section aria-label={invitation.is_member ? "Your invitation" : "Your entries"} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p>
        {invitation.invited_by_name ?? "The organizer"} {invitation.is_member ? `added you to ${invitation.organization_name} as` : "entered you as"}{" "}
        <strong>{invitation.guest_name}</strong>.
      </p>
      {invitation.entries.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {invitation.entries.map((entry) => (
            <li key={`${entry.tournament_id}-${entry.event_name}`} className="flex items-start gap-2">
              <Trophy aria-hidden className="mt-0.5 size-5 shrink-0 text-brand-blue" />
              <span className="flex flex-col">
                <span className="font-semibold">
                  {entry.tournament_name} · {entry.event_name}
                </span>
                <span className="flex items-center gap-1 text-sm text-muted-foreground">
                  <CalendarDays aria-hidden className="size-4" /> {day(entry.starts_on)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        !invitation.is_member && <p className="text-sm text-muted-foreground">No tournament entries yet.</p>
      )}
    </section>
  )
}

function JoinForm({ token, invitation }: { token: string; invitation: InvitationDetail }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ display_name: invitation.guest_name, email: invitation.email, phone: invitation.phone, password: "" })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const join = useMutation({
    mutationFn: () =>
      joinFromInvitation(token, {
        display_name: form.display_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        password: form.password,
      }),
    onSuccess: async ({ signed_in }) => {
      if (!signed_in) {
        navigate("/signup/check-email", { state: { email: form.email.trim() } })
        return
      }
      queryClient.setQueryData(meQueryKey, await getMe())
      // Their details next: the profile the organizer couldn't fill in for them.
      navigate("/onboarding/profile", { replace: true })
    },
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
    const found: Record<string, string> = {}
    if (!form.display_name.trim()) found.display_name = "Enter the name other players will see."
    if (!form.email.trim() && !form.phone.trim()) found.email = "Give an email address or a phone number to log in with."
    if (form.email.trim() && !/^\S+@\S+\.\S+$/.test(form.email.trim())) found.email = "Enter a valid email address."
    if (form.password.length < MIN_PASSWORD_LENGTH) found.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`
    setErrors(found)
    if (Object.keys(found).length === 0) join.mutate()
  }

  const taken = join.error instanceof ApiError && (join.error.code === "email_taken" || join.error.code === "phone_taken")
  const shownInFields = Object.keys(errors).length > 0
  const changedEmail = !!invitation.email && form.email.trim().toLowerCase() !== invitation.email
  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
      {taken && (
        <FormAlert>
          {errorMessage(join.error)}{" "}
          <Link to={`/login?next=${encodeURIComponent(`/join/${encodeURIComponent(token)}`)}`} className="font-semibold underline underline-offset-4">
            Log in
          </Link>
        </FormAlert>
      )}
      {join.isError && !taken && !shownInFields && <FormAlert>{errorMessage(join.error)}</FormAlert>}
      <Field label="Your name" autoComplete="name" maxLength={80} value={form.display_name} onChange={set("display_name")} error={errors.display_name} hint="How other players and organizers will see you." />
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        inputMode="email"
        optional={!!form.phone.trim()}
        value={form.email}
        onChange={set("email")}
        error={errors.email}
        hint={changedEmail ? "We'll send a link to confirm this address before you can log in." : "Add it to get match calls, schedule changes and results by email."}
      />
      <Field
        label="Phone number"
        type="tel"
        autoComplete="tel"
        inputMode="tel"
        optional={!!form.email.trim()}
        value={form.phone}
        onChange={set("phone")}
        error={errors.phone}
        hint="You can log in with your email or this number."
      />
      <PasswordField label="Choose a password" autoComplete="new-password" value={form.password} onChange={set("password")} error={errors.password} hint={`At least ${MIN_PASSWORD_LENGTH} characters.`} />
      <Button type="submit" size="lg" disabled={join.isPending}>
        {join.isPending ? "Joining…" : invitation.is_member ? "Set password and sign in" : "Join and see my entries"}
      </Button>
    </form>
  )
}

function ClaimForAccount({ token, name, member }: { token: string; name: string; member: boolean }) {
  const navigate = useNavigate()
  const claim = useMutation({ mutationFn: () => claimByLink(token) })
  if (claim.data) {
    return claim.data.status === "merged" ? (
      <div role="status" className="flex flex-col gap-3">
        <p className="font-semibold text-success">Done: {member ? "the membership and any entries are" : "these entries are"} on your account now.</p>
        <Button size="lg" onClick={() => navigate("/play")}>
          See my tournaments
        </Button>
      </div>
    ) : (
      <FormAlert>
        Something on your account clashes with these entries ({claim.data.clashes.join("; ")}). {claim.data.organization_name} will sort it out; nothing has moved yet.
      </FormAlert>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      <p>
        You're logged in as <strong>{name}</strong>. {member ? "Add the membership, and any entries and results, to your account?" : "Add these entries and any results to your account?"}
      </p>
      {claim.isError && <FormAlert>{errorMessage(claim.error)}</FormAlert>}
      <Button size="lg" disabled={claim.isPending} onClick={() => claim.mutate()}>
        {claim.isPending ? "Adding…" : "Add them to my account"}
      </Button>
      <p className="text-sm text-muted-foreground">Not you? Log out first, then open the link again.</p>
    </div>
  )
}
