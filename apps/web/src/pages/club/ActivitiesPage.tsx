import { useDeferredValue, useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, PartyPopper, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { activityKeys, createActivity, KIND_LABEL, listActivities, type Activity, type When } from "@/lib/activities"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { DEFAULT_TIME_ZONE, formatInstant, fromZonedInput } from "@/lib/dates"
import { listWelfare, welfareKeys } from "@/lib/finance"
import { cn } from "@/lib/utils"

const STATUS: Record<Activity["status"], string> = { draft: "Draft", published: "Published", cancelled: "Cancelled" }

/** Club activities for the activities officer (REQ-039): draft, publish, follow answers, cancel. */
export function ActivitiesPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const timeZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE
  const allowed = can(active, "activities.manage")
  const [when, setWhen] = useState<When>("upcoming")
  // "Plan a visit" on a welfare project opens the form already linked to it.
  const [params] = useSearchParams()
  const welfareId = params.get("welfare") ?? ""
  const [adding, setAdding] = useState(!!welfareId)
  const activities = useQuery({ queryKey: activityKeys.list(orgId, when), queryFn: () => listActivities(orgId, when), enabled: allowed })
  const accessLost = useAdminAccessLost(activities.error)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Activities</h1>
        {active && <p className="text-muted-foreground">{active.organization.name}</p>}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {adding ? (
            <NewActivity orgId={orgId} timeZone={timeZone} welfareId={welfareId} canLinkWelfare={can(active, "welfare.manage")} onClose={() => setAdding(false)} />
          ) : (
            <Button className="self-start" onClick={() => setAdding(true)}>
              <Plus aria-hidden className="size-5" /> New activity
            </Button>
          )}
          <div role="group" aria-label="Which activities" className="flex self-start rounded-lg border bg-card p-1">
            {(["upcoming", "past"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={when === value}
                onClick={() => setWhen(value)}
                className={cn("h-12 rounded-md px-4 font-semibold text-muted-foreground capitalize outline-none focus-visible:ring-3 focus-visible:ring-ring/50", when === value && "bg-surface-selected text-brand-blue")}
              >
                {value}
              </button>
            ))}
          </div>
          {activities.isError && <FormAlert>{errorMessage(activities.error, "We couldn't load the activities.")}</FormAlert>}
          {activities.isSuccess && activities.data.results.length === 0 && <p className="text-muted-foreground">No activities {when === "upcoming" ? "planned" : "yet"}.</p>}
          <ul className="flex flex-col gap-2">
            {(activities.data?.results ?? []).map((activity) => (
              <li key={activity.id}>
                <Link to={`/activities/${orgId}/${activity.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                  <PartyPopper aria-hidden className="size-5 text-brand-blue" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className={cn("truncate font-semibold", activity.status === "cancelled" && "line-through")}>{activity.title}</span>
                    <span className="text-sm text-muted-foreground">
                      {formatInstant(activity.starts_at, timeZone)} · {KIND_LABEL[activity.kind ?? "other"]} · {STATUS[activity.status]}
                    </span>
                    {activity.status === "published" && (
                      <span className="text-sm text-muted-foreground">
                        {activity.going} going{activity.capacity ? ` of ${activity.capacity}` : ""}
                        {activity.waitlisted > 0 && ` · ${activity.waitlisted} waiting`}
                      </span>
                    )}
                  </span>
                  <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function NewActivity({ orgId, timeZone, welfareId, canLinkWelfare, onClose }: { orgId: string; timeZone: string; welfareId: string; canLinkWelfare: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [title, setTitle] = useState("")
  const [kind, setKind] = useState<Activity["kind"]>(welfareId ? "visit" : "social")
  const [project, setProject] = useState(canLinkWelfare ? welfareId : "")
  const projects = useQuery({ queryKey: welfareKeys(orgId), queryFn: () => listWelfare(orgId), enabled: canLinkWelfare })
  const openProjects = (projects.data ?? []).filter((p) => !p.closed)
  const [starts, setStarts] = useState("")
  const [ends, setEnds] = useState("")
  const [place, setPlace] = useState("")
  const [description, setDescription] = useState("")
  const [audience, setAudience] = useState<Activity["audience"]>("members")
  const [invitees, setInvitees] = useState<string[]>([])
  const [capacity, setCapacity] = useState("")
  const [deadline, setDeadline] = useState("")
  const [isPublic, setPublic] = useState(false)
  const [cost, setCost] = useState("")
  const [term, setTerm] = useState("")
  const search = useDeferredValue(term.trim())
  const members = useQuery({ queryKey: ["clubs", orgId, "members", search], queryFn: () => listMembers(orgId, search), enabled: audience === "selected" })
  const save = useMutation({
    mutationFn: () =>
      createActivity(orgId, {
        title: title.trim(),
        kind,
        description: description.trim(),
        starts_at: fromZonedInput(starts, timeZone) ?? "",
        ends_at: fromZonedInput(ends, timeZone) ?? "",
        place: place.trim(),
        audience,
        invitee_ids: audience === "selected" ? invitees : [],
        capacity: capacity ? Number(capacity) : null,
        rsvp_deadline: deadline ? fromZonedInput(deadline, timeZone) : null,
        public: project ? false : isPublic,
        cost_note: cost.trim(),
        welfare_project_id: project || null,
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: activityKeys.all })
      navigate(`/activities/${orgId}/${made.id}`)
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  const options = (members.data?.results ?? []).map((m) => ({ value: m.user, label: m.display_name }))

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">New activity</h2>
      <p className="text-sm text-muted-foreground">It's saved as a draft. Members see it once you publish it.</p>
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="End-of-year night out" error={errors.title} />
      <SelectField label="Kind" value={kind ?? "social"} onChange={(value) => setKind(value as Activity["kind"])} options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} hint={`In ${timeZone}.`} error={errors.starts_at} />
        <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={errors.ends_at} />
      </div>
      <Field label="Where" optional maxLength={200} value={place} onChange={(e) => setPlace(e.target.value)} hint="A venue or a meeting point." error={errors.place} />
      <TextAreaField label="Details" optional maxLength={2000} rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      <ChoiceGroup
        legend="Who it's for"
        options={[
          { value: "members" as const, label: "All members" },
          { value: "selected" as const, label: "Selected members" },
        ]}
        value={audience ?? "members"}
        onChange={setAudience}
        error={errors.invitee_ids}
      />
      {audience === "selected" && (
        <div className="flex flex-col gap-2">
          <label className="sr-only" htmlFor="invite-search">
            Find a member
          </label>
          <Input id="invite-search" type="search" placeholder="Find a member" value={term} onChange={(e) => setTerm(e.target.value)} />
          <ChoiceGroup legend={`Invited (${invitees.length})`} multiple options={options} value={invitees} onChange={setInvitees} />
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Places" optional type="number" min={1} inputMode="numeric" value={capacity} onChange={(e) => setCapacity(e.target.value)} hint="Beyond this, Going puts people on a waiting list." error={errors.capacity} />
        <Field label="Answers close" optional type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} error={errors.rsvp_deadline} />
      </div>
      <Field label="Cost note" optional maxLength={200} value={cost} onChange={(e) => setCost(e.target.value)} placeholder="KES 500 each, pay on the night" hint="Shown as text only. Coast TT doesn't collect money." error={errors.cost_note} />
      {canLinkWelfare && openProjects.length > 0 && (
        <SelectField
          label="For a welfare project"
          value={project}
          onChange={setProject}
          options={[{ value: "", label: "None" }, ...openProjects.map((p) => ({ value: p.id, label: p.title }))]}
          hint="A planned visit or support activity. It shows on the project, is never public, and is hidden with the project."
        />
      )}
      {!project && (
        <label className="flex min-h-12 items-center gap-3">
          <input type="checkbox" className="size-5 accent-brand-blue" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} />
          <span>
            <span className="font-semibold">Public</span> <span className="text-muted-foreground">: everyone on Coast TT can see it; only your members answer.</span>
          </span>
        </label>
      )}
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending || !title.trim() || !starts || !ends}>
          {save.isPending ? "Saving…" : "Save draft"}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
