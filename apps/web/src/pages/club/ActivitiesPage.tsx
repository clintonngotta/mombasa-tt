import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
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
import { activityKeys, AUDIENCE_LABEL, createActivity, KIND_LABEL, listActivities, type Activity, type Audience, type When } from "@/lib/activities"
import { can, isBodyKind, listMembers, useActiveMembership } from "@/lib/clubs"
import { MIN_SEARCH_LENGTH, searchPlayers } from "@/lib/profile"
import { listRegionClubs, regionKeys } from "@/lib/regions"
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
            <NewActivity
              orgId={orgId}
              timeZone={timeZone}
              welfareId={welfareId}
              canLinkWelfare={can(active, "welfare.manage")}
              body={!!active && isBodyKind(active.organization.kind)}
              regional={active?.organization.kind === "regional_body"}
              onClose={() => setAdding(false)}
            />
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

function NewActivity({ orgId, timeZone, welfareId, canLinkWelfare, body, regional, onClose }: { orgId: string; timeZone: string; welfareId: string; canLinkWelfare: boolean; body: boolean; regional: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const draft = useDraft(`activity-new:${orgId}`)
  const [title, setTitle] = useDraftState(draft, "title", "")
  const [kind, setKind] = useDraftState<Activity["kind"]>(draft, "kind", welfareId ? "visit" : "social")
  const [project, setProject] = useDraftState(draft, "project", canLinkWelfare ? welfareId : "")
  const projects = useQuery({ queryKey: welfareKeys(orgId), queryFn: () => listWelfare(orgId), enabled: canLinkWelfare })
  const openProjects = (projects.data ?? []).filter((p) => !p.closed)
  const [starts, setStarts] = useDraftState(draft, "starts", "")
  const [ends, setEnds] = useDraftState(draft, "ends", "")
  const [place, setPlace] = useDraftState(draft, "place", "")
  const [description, setDescription] = useDraftState(draft, "description", "")
  const [audience, setAudience] = useDraftState<Audience>(draft, "audience", "members")
  const [invitees, setInvitees] = useDraftState<string[]>(draft, "invitees", [])
  // Named people can be players outside the club: keep their names as they are picked.
  const [named, setNamed] = useDraftState<{ id: string; name: string }[]>(draft, "named", [])
  const [clubs, setClubs] = useDraftState<string[]>(draft, "clubs", [])
  const [capacity, setCapacity] = useDraftState(draft, "capacity", "")
  const [deadline, setDeadline] = useDraftState(draft, "deadline", "")
  const [isPublic, setPublic] = useDraftState(draft, "isPublic", false)
  const [cost, setCost] = useDraftState(draft, "cost", "")
  const [term, setTerm] = useDraftState(draft, "term", "")
  const search = useDeferredValue(term.trim())
  const members = useQuery({ queryKey: ["clubs", orgId, "members", search], queryFn: () => listMembers(orgId, search), enabled: audience === "selected" })
  const players = useQuery({ queryKey: ["players", "search", search], queryFn: () => searchPlayers(search), enabled: audience === "named" && search.length >= MIN_SEARCH_LENGTH })
  const senders = useQuery({ queryKey: regionKeys.clubs(orgId), queryFn: () => listRegionClubs(orgId), enabled: audience === "reps" && regional })
  const membersOnly = audience === "members" || audience === "selected"
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
        ...(audience === "selected" ? { invitee_ids: invitees } : {}),
        ...(audience === "named" ? { invitee_ids: named.map((person) => person.id) } : {}),
        ...(audience === "reps" && clubs.length ? { club_ids: clubs } : {}),
        capacity: capacity ? Number(capacity) : null,
        rsvp_deadline: deadline ? fromZonedInput(deadline, timeZone) : null,
        public: project ? false : isPublic,
        cost_note: cost.trim(),
        welfare_project_id: membersOnly ? project || null : null,
      }),
    onSuccess: (made) => {
      draft.clear()
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
      <p className="text-sm text-muted-foreground">It's saved as a draft. The people it's for see it once you publish it.</p>
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
        options={(Object.keys(AUDIENCE_LABEL) as Audience[]).filter((value) => body || value !== "reps").map((value) => ({ value, label: AUDIENCE_LABEL[value] }))}
        value={audience}
        onChange={setAudience}
        error={errors.invitee_ids ?? errors.audience ?? errors.club_ids}
      />
      {audience === "reps" && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">The representatives you have accepted are invited. {regional ? "Choose clubs to invite only theirs." : ""}</p>
          {regional && (senders.data?.length ?? 0) > 0 && (
            <ChoiceGroup legend={clubs.length ? `Only these clubs (${clubs.length})` : "Every club"} multiple options={(senders.data ?? []).map((club) => ({ value: club.id, label: club.name }))} value={clubs} onChange={setClubs} />
          )}
        </div>
      )}
      {audience === "named" && (
        <div className="flex flex-col gap-2">
          <label className="sr-only" htmlFor="name-search">
            Find a player
          </label>
          <Input id="name-search" type="search" placeholder="Find a player by name" value={term} onChange={(e) => setTerm(e.target.value)} />
          <p className="text-sm text-muted-foreground">Players listed in the directory. They see the event and can answer even if they aren't members.</p>
          <ul className="flex flex-col gap-1">
            {(players.data?.results ?? [])
              .filter((player) => !named.some((person) => person.id === player.id))
              .slice(0, 8)
              .map((player) => (
                <li key={player.id}>
                  <Button type="button" variant="outline" size="sm" onClick={() => setNamed([...named, { id: player.id, name: player.display_name }])}>
                    <Plus aria-hidden className="size-4" /> Invite {player.display_name}
                  </Button>
                </li>
              ))}
          </ul>
          {named.length > 0 && (
            <ul aria-label="People invited" className="flex flex-wrap gap-2">
              {named.map((person) => (
                <li key={person.id}>
                  <Button type="button" variant="secondary" size="sm" aria-label={`Remove ${person.name}`} onClick={() => setNamed(named.filter((other) => other.id !== person.id))}>
                    {person.name} ×
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
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
      {canLinkWelfare && membersOnly && openProjects.length > 0 && (
        <SelectField
          label="For a welfare project"
          value={project}
          onChange={setProject}
          options={[{ value: "", label: "None" }, ...openProjects.map((p) => ({ value: p.id, label: p.title }))]}
          hint="A planned visit or support activity. It shows on the project, is never public, and is hidden with the project."
        />
      )}
      {!project && audience !== "open" && (
        <label className="flex min-h-12 items-center gap-3">
          <input type="checkbox" className="size-5 accent-brand-blue" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} />
          <span>
            <span className="font-semibold">Public</span> <span className="text-muted-foreground">: everyone on Coast TT can see it; only the people it's for answer.</span>
          </span>
        </label>
      )}
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <DraftBar draft={draft} label="Finish later" />
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
