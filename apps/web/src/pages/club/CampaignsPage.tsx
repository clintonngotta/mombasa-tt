import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { CADENCE_LABEL, CLUB_OPERATIONS, campaignDuesKey, campaignKeys, closeCampaign, createCampaign, financeKeys, listCampaignDues, listCampaigns, remindCampaign, setCampaignTerm, STATUS_LABEL, toMinor, updateCampaign, type Campaign } from "@/lib/finance"

const SELECT = "h-12 rounded-md border bg-background px-3"

/** Contribution campaigns and dues (REQ-023): each period's due is made once per member, as it falls. */
export function CampaignsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "finances.view", "finances.manage")
  const manage = can(active, "finances.manage")
  const campaigns = useQuery({ queryKey: campaignKeys(orgId), queryFn: () => listCampaigns(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(campaigns.error)
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club/finance">Finances</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Dues and contributions</h1>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {campaigns.isError && <FormAlert>{errorMessage(campaigns.error)}</FormAlert>}
          {manage && <NewCampaign orgId={orgId} />}
          {campaigns.isSuccess && campaigns.data.length === 0 && <p className="text-muted-foreground">No campaigns yet.</p>}
          <ul className="flex flex-col gap-2">
            {(campaigns.data ?? []).map((c) => (
              <li key={c.id}>
                <CampaignCard orgId={orgId} campaign={c} manage={manage} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function useMembers(orgId: string) {
  return useQuery({ queryKey: ["finance", "members", orgId], queryFn: () => listMembers(orgId, "") })
}

function useCampaignMutation<T>(orgId: string, fn: (input: T) => Promise<unknown>, done?: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      done?.()
      return queryClient.invalidateQueries({ queryKey: financeKeys.ledger(orgId) })
    },
  })
}

function NewCampaign({ orgId }: { orgId: string }) {
  const members = useMembers(orgId)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [amount, setAmount] = useState("")
  const [cadence, setCadence] = useState<Campaign["cadence"]>("monthly")
  const [starts, setStarts] = useState("")
  const [ends, setEnds] = useState("")
  const [audience, setAudience] = useState<Campaign["audience"]>("all")
  const [chosen, setChosen] = useState<string[]>([])
  const add = useCampaignMutation(
    orgId,
    () =>
      createCampaign(orgId, {
        title: title.trim(),
        description,
        amount_minor: toMinor(amount) ?? 0,
        currency: "KES",
        cadence,
        starts_on: starts,
        ends_on: ends || null,
        audience,
        member_ids: audience === "selected" ? chosen : [],
      }),
    () => {
      setTitle("")
      setDescription("")
      setAmount("")
      setChosen([])
    },
  )
  const applyOperations = () => {
    setTitle(CLUB_OPERATIONS.title)
    setDescription(CLUB_OPERATIONS.description)
    setAudience(CLUB_OPERATIONS.audience)
    if (cadence !== "weekly") setCadence("monthly")
  }
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">New campaign</h2>
        <Button variant="outline" onClick={applyOperations}>
          Use "Club operations"
        </Button>
      </div>
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
      <Field label="What it pays for" optional value={description} onChange={(e) => setDescription(e.target.value)} />
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <label className="flex flex-col gap-1 text-sm font-semibold">
          How often
          <select className={SELECT} value={cadence} onChange={(e) => setCadence(e.target.value as Campaign["cadence"])}>
            {Object.entries(CADENCE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Field label="First due" type="date" className="w-44" value={starts} onChange={(e) => setStarts(e.target.value)} />
        <Field label="Last due" optional type="date" className="w-44" value={ends} onChange={(e) => setEnds(e.target.value)} />
      </div>
      <label className="flex flex-col gap-1 text-sm font-semibold">
        Who owes
        <select className={SELECT} value={audience} onChange={(e) => setAudience(e.target.value as Campaign["audience"])}>
          <option value="all">All active members</option>
          <option value="selected">Selected members</option>
        </select>
      </label>
      {audience === "selected" && (
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm font-semibold">Members</legend>
          {(members.data?.results ?? []).map((m) => (
            <label key={m.id} className="flex items-center gap-2">
              <input type="checkbox" checked={chosen.includes(m.user)} onChange={(e) => setChosen((now) => (e.target.checked ? [...now, m.user] : now.filter((id) => id !== m.user)))} />
              {m.display_name}
            </label>
          ))}
        </fieldset>
      )}
      <p className="text-sm text-muted-foreground">Members who join later owe from the next due after joining. Dues already made keep their amount if you change it.</p>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button className="self-start" disabled={!title.trim() || toMinor(amount) == null || !starts || (audience === "selected" && chosen.length === 0) || add.isPending} onClick={() => add.mutate(undefined)}>
        Start campaign
      </Button>
    </section>
  )
}

function CampaignCard({ orgId, campaign: c, manage }: { orgId: string; campaign: Campaign; manage: boolean }) {
  const members = useMembers(orgId)
  const [amount, setAmount] = useState("")
  const [member, setMember] = useState("")
  const [own, setOwn] = useState("")
  const [reason, setReason] = useState("")
  const change = useCampaignMutation(orgId, () => updateCampaign(orgId, c.id, { amount_minor: toMinor(amount) ?? 0 }), () => setAmount(""))
  const close = useCampaignMutation(orgId, () => closeCampaign(orgId, c.id))
  const term = useCampaignMutation(orgId, (waive: boolean) =>
    setCampaignTerm(orgId, c.id, { member_id: member, included: true, amount_minor: waive || !own ? null : toMinor(own), waived: waive, waive_reason: waive ? reason.trim() : "" }),
  )
  const error = change.error ?? close.error ?? term.error
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">{c.title}</p>
      <p className="text-sm text-muted-foreground">
        {formatMoney(c.amount_minor, c.currency)} · {CADENCE_LABEL[c.cadence]} from {c.starts_on}
        {c.ends_on && ` to ${c.ends_on}`} · {c.audience === "all" ? "all members" : "selected members"} · {c.dues_count} dues made
        {c.closed ? " · closed" : c.next_due_on ? ` · next ${c.next_due_on}` : ""}
      </p>
      {c.description && <p className="text-sm">{c.description}</p>}
      {c.terms.length > 0 && (
        <ul className="text-sm">
          {c.terms.map((t) => (
            <li key={t.member_id}>
              {t.member_name}: {t.waived ? `waived (${t.waive_reason})` : t.amount_minor != null ? formatMoney(t.amount_minor, c.currency) : "included"}
            </li>
          ))}
        </ul>
      )}
      <Dues orgId={orgId} campaign={c} manage={manage} />
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      {manage && !c.closed && (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="New amount (KES)" type="number" min={0} className="w-40" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Button variant="outline" disabled={toMinor(amount) == null || change.isPending} onClick={() => change.mutate(undefined)}>
              Change from next due
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm font-semibold">
              Member
              <select className={SELECT} value={member} onChange={(e) => setMember(e.target.value)}>
                <option value="">Choose a member</option>
                {(members.data?.results ?? []).map((m) => (
                  <option key={m.id} value={m.user}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </label>
            <Field label="Their amount (KES)" optional type="number" min={0} className="w-40" value={own} onChange={(e) => setOwn(e.target.value)} />
            <Button variant="outline" disabled={!member || term.isPending} onClick={() => term.mutate(false)}>
              Set amount
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Reason to waive this member" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
            <Button variant="outline" disabled={!member || !reason.trim() || term.isPending} onClick={() => term.mutate(true)}>
              Waive from next due
            </Button>
          </div>
          <Button variant="outline" className="self-start text-destructive" disabled={close.isPending} onClick={() => close.mutate(undefined)}>
            Close campaign
          </Button>
        </>
      )}
    </article>
  )
}

const DUE_TABS = [
  { value: "overdue", label: "Overdue" },
  { value: "partial", label: "Part paid" },
  { value: "pending", label: "Owed" },
  { value: "paid", label: "Paid" },
  { value: "", label: "All" },
]

/** Who owes what on the campaign, by status, and a once-a-day reminder to those overdue. */
function Dues({ orgId, campaign: c, manage }: { orgId: string; campaign: Campaign; manage: boolean }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState("overdue")
  const dues = useQuery({ queryKey: campaignDuesKey(orgId, c.id, tab), queryFn: () => listCampaignDues(orgId, c.id, tab), enabled: open })
  const remind = useMutation({ mutationFn: () => remindCampaign(orgId, c.id) })
  if (!open) {
    return (
      <Button variant="ghost" className="self-start" onClick={() => setOpen(true)}>
        See dues
      </Button>
    )
  }
  const data = dues.data
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      {data && (
        <p className="text-sm">
          {formatMoney(data.outstanding_minor, c.currency)} still owed, {formatMoney(data.overdue_minor, c.currency)} of it overdue
        </p>
      )}
      <div role="group" aria-label="Which dues" className="flex flex-wrap gap-1">
        {DUE_TABS.map((t) => (
          <Button key={t.value} variant={tab === t.value ? "default" : "outline"} aria-pressed={tab === t.value} onClick={() => setTab(t.value)}>
            {t.label}
            {data && t.value && data.counts[t.value] ? ` (${data.counts[t.value]})` : ""}
          </Button>
        ))}
      </div>
      {dues.isError && <FormAlert>{errorMessage(dues.error)}</FormAlert>}
      {data && data.dues.length === 0 && <p className="text-sm text-muted-foreground">None.</p>}
      <ul className="flex flex-col gap-1 text-sm">
        {(data?.dues ?? []).map((d) => (
          <li key={d.id} className="flex justify-between gap-2">
            <span>
              {d.member_name} · {d.period}
            </span>
            <span className="text-muted-foreground">
              {STATUS_LABEL[d.status] ?? d.status}
              {d.outstanding_minor > 0 && ` · ${formatMoney(d.outstanding_minor, d.currency)} left`}
            </span>
          </li>
        ))}
      </ul>
      {manage && !c.closed && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" disabled={remind.isPending} onClick={() => remind.mutate()}>
            Remind everyone overdue
          </Button>
          {remind.isSuccess && <span className="text-sm text-muted-foreground">{remind.data.sent ? `Reminded ${remind.data.sent}.` : "Everyone overdue was already reminded today."}</span>}
          {remind.isError && <FormAlert>{errorMessage(remind.error)}</FormAlert>}
        </div>
      )}
    </div>
  )
}
