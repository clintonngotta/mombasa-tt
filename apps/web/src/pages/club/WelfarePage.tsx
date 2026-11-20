import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { formatMoney } from "@/lib/coaching"
import {
  closeWelfare,
  createWelfare,
  hideWelfare,
  listContributions,
  listWelfare,
  METHOD_LABEL,
  recordContribution,
  recordWelfareExpense,
  reverseContribution,
  toMinor,
  updateWelfare,
  welfareKeys,
  type Payment,
  type WelfareProject,
} from "@/lib/finance"
import { useMe } from "@/lib/session"
import { cn } from "@/lib/utils"

const SELECT = "h-12 rounded-md border bg-background px-3"
const today = () => new Date().toISOString().slice(0, 10)

/** Welfare projects (REQ-038): giving is voluntary, so nobody here ever owes or is overdue. Members see
 * totals and their own gift; welfare and finance staff record gifts and spending. */
export function WelfarePage() {
  const { active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const setUp = can(active, "welfare.manage")
  const record = can(active, "welfare.manage", "finances.manage")
  const staff = can(active, "welfare.manage", "finances.view", "finances.manage")
  const projects = useQuery({ queryKey: welfareKeys(orgId), queryFn: () => listWelfare(orgId), enabled: !!orgId })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Welfare</h1>
      <p className="text-muted-foreground">Giving is voluntary. A suggested amount is only a suggestion.</p>
      {projects.isError && <FormAlert>{errorMessage(projects.error)}</FormAlert>}
      {setUp && <NewProject orgId={orgId} />}
      {projects.isSuccess && projects.data.length === 0 && <p className="text-muted-foreground">No welfare projects.</p>}
      <ul className="flex flex-col gap-3">
        {(projects.data ?? []).map((p) => (
          <li key={p.id}>
            <ProjectCard orgId={orgId} project={p} setUp={setUp} record={record} staff={staff} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function useMembers(orgId: string) {
  return useQuery({ queryKey: ["finance", "members", orgId], queryFn: () => listMembers(orgId, "") })
}

function useWelfareMutation<T>(orgId: string, fn: (input: T) => Promise<unknown>, done?: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      done?.()
      return queryClient.invalidateQueries({ queryKey: welfareKeys(orgId) })
    },
  })
}

function MemberSelect({ orgId, value, onChange, label, optional }: { orgId: string; value: string; onChange: (id: string) => void; label: string; optional?: boolean }) {
  const members = useMembers(orgId)
  return (
    <label className="flex flex-col gap-1 text-sm font-semibold">
      {label}
      <select className={SELECT} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? "Nobody in particular" : "Choose a member"}</option>
        {(members.data?.results ?? []).map((m) => (
          <option key={m.id} value={m.user}>
            {m.display_name}
          </option>
        ))}
      </select>
    </label>
  )
}

function NewProject({ orgId }: { orgId: string }) {
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [beneficiary, setBeneficiary] = useState("")
  const [suggested, setSuggested] = useState("")
  const [target, setTarget] = useState("")
  const [deadline, setDeadline] = useState("")
  const add = useWelfareMutation(
    orgId,
    () =>
      createWelfare(orgId, {
        title: title.trim(),
        description,
        beneficiary_id: beneficiary || null,
        suggested_minor: toMinor(suggested),
        target_minor: toMinor(target),
        deadline: deadline || null,
        currency: "KES",
        audience: "all",
        member_ids: [],
      }),
    () => {
      setTitle("")
      setDescription("")
      setSuggested("")
      setTarget("")
    },
  )
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-semibold">New welfare project</h2>
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
      <Field label="What members should know" optional value={description} onChange={(e) => setDescription(e.target.value)} />
      <p className="text-sm text-muted-foreground">Write only what the member or their family agreed to share. Members are told a project opened, never what it is about.</p>
      <MemberSelect orgId={orgId} value={beneficiary} onChange={setBeneficiary} label="For" optional />
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Suggested gift (KES)" optional type="number" min={0} className="w-44" value={suggested} onChange={(e) => setSuggested(e.target.value)} />
        <Field label="Target (KES)" optional type="number" min={0} className="w-40" value={target} onChange={(e) => setTarget(e.target.value)} />
        <Field label="Until" optional type="date" className="w-44" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
      </div>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button className="self-start" disabled={!title.trim() || add.isPending} onClick={() => add.mutate(undefined)}>
        Open project
      </Button>
    </section>
  )
}

function ProjectCard({ orgId, project: p, setUp, record, staff }: { orgId: string; project: WelfareProject; setUp: boolean; record: boolean; staff: boolean }) {
  const me = useMe()
  const hide = useWelfareMutation(orgId, () => hideWelfare(orgId, p.id))
  const close = useWelfareMutation(orgId, () => closeWelfare(orgId, p.id))
  const toggle = useWelfareMutation(orgId, () => updateWelfare(orgId, p.id, { show_contributors: !p.show_contributors }))
  const error = hide.error ?? close.error ?? toggle.error
  const isBeneficiary = !!me.data && p.beneficiary_id === me.data.id
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {p.title}
        {p.closed && " · closed"}
        {p.hidden && " · hidden from members"}
      </p>
      {p.description && <p className="text-sm">{p.description}</p>}
      <p className="text-sm">
        Raised {formatMoney(p.received_minor, p.currency)}
        {p.target_minor != null && ` of ${formatMoney(p.target_minor, p.currency)}`} · spent {formatMoney(p.spent_minor, p.currency)} ·{" "}
        <span className={cn("font-semibold", p.remaining_minor < 0 && "text-destructive")}>
          {p.remaining_minor < 0 ? `deficit ${formatMoney(-p.remaining_minor, p.currency)}` : `${formatMoney(p.remaining_minor, p.currency)} left`}
        </span>
      </p>
      <p className="text-sm text-muted-foreground">
        {p.suggested_minor != null && `Suggested ${formatMoney(p.suggested_minor, p.currency)} · `}
        {p.my_contribution_minor > 0 ? `You gave ${formatMoney(p.my_contribution_minor, p.currency)}` : "You haven't given"}
        {p.deadline && ` · until ${p.deadline}`}
      </p>
      {p.contributors && (
        <ul className="text-sm">
          {p.contributors.map((c, i) => (
            <li key={i}>
              {c.name} · {formatMoney(c.amount_minor, p.currency)}
            </li>
          ))}
        </ul>
      )}
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        {(isBeneficiary || setUp) && !p.hidden && (
          <Button variant="outline" disabled={hide.isPending} onClick={() => hide.mutate(undefined)}>
            Hide from members
          </Button>
        )}
        {setUp && !p.closed && (
          <>
            <Button variant="outline" disabled={toggle.isPending} onClick={() => toggle.mutate(undefined)}>
              {p.show_contributors ? "Stop showing who gave" : "Show who gave"}
            </Button>
            <Button variant="outline" className="text-destructive" disabled={close.isPending} onClick={() => close.mutate(undefined)}>
              Close project
            </Button>
          </>
        )}
      </div>
      {staff && <Gifts orgId={orgId} project={p} record={record && !p.closed} />}
    </article>
  )
}

function Gifts({ orgId, project: p, record }: { orgId: string; project: WelfareProject; record: boolean }) {
  const [open, setOpen] = useState(false)
  const gifts = useQuery({ queryKey: [...welfareKeys(orgId), p.id, "gifts"], queryFn: () => listContributions(orgId, p.id), enabled: open })
  const [giver, setGiver] = useState("")
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<Payment["method"]>("cash")
  const [reference, setReference] = useState("")
  const [anonymous, setAnonymous] = useState(false)
  const [key, setKey] = useState(() => crypto.randomUUID())
  const [spentOn, setSpentOn] = useState(today)
  const [what, setWhat] = useState("")
  const [cost, setCost] = useState("")
  const [reason, setReason] = useState("")
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: welfareKeys(orgId) })
  const give = useMutation({
    mutationFn: () => recordContribution(orgId, p.id, { contributor_id: giver, amount_minor: toMinor(amount) ?? 0, currency: "KES", method, reference: reference.trim(), received_on: today(), request_key: key, anonymous }),
    onSuccess: () => {
      setAmount("")
      setReference("")
      setAnonymous(false)
      setKey(crypto.randomUUID())
      return refresh()
    },
  })
  const undo = useMutation({ mutationFn: (id: string) => reverseContribution(orgId, p.id, id, reason.trim()), onSuccess: refresh })
  const spend = useMutation({
    mutationFn: () => recordWelfareExpense(orgId, p.id, { description: what.trim(), amount_minor: toMinor(cost) ?? 0, currency: "KES", spent_on: spentOn }),
    onSuccess: () => {
      setWhat("")
      setCost("")
      return refresh()
    },
  })
  if (!open) {
    return (
      <Button variant="ghost" className="self-start" onClick={() => setOpen(true)}>
        Gifts and spending
      </Button>
    )
  }
  const error = gifts.error ?? give.error ?? undo.error ?? spend.error
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3">
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      <ul className="flex flex-col gap-1 text-sm">
        {(gifts.data ?? []).map((g) => (
          <li key={g.id} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {g.contributor_name}
              {g.anonymous && " (anonymous to members)"} · {formatMoney(g.amount_minor, g.currency)} by {METHOD_LABEL[g.method]} · {g.received_on}
              {g.reversed && " · reversed"}
            </span>
            {record && !g.reversed && (
              <Button variant="ghost" disabled={!reason.trim() || undo.isPending} onClick={() => undo.mutate(g.id)}>
                Reverse
              </Button>
            )}
          </li>
        ))}
      </ul>
      {record && (
        <>
          <Field label="Reason to reverse a gift" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          <h3 className="font-semibold">Record a gift</h3>
          <MemberSelect orgId={orgId} value={giver} onChange={setGiver} label="From" />
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <label className="flex flex-col gap-1 text-sm font-semibold">
              Method
              <select className={SELECT} value={method} onChange={(e) => setMethod(e.target.value as Payment["method"])}>
                {Object.entries(METHOD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <Field label="Reference" optional className="w-40" maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={anonymous} onChange={(e) => setAnonymous(e.target.checked)} />
            Keep their name out of the list members see
          </label>
          <Button className="self-start" disabled={!giver || toMinor(amount) == null || give.isPending} onClick={() => give.mutate()}>
            Record gift
          </Button>
          <h3 className="font-semibold">Record spending</h3>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="What for" className="min-w-48 flex-1" maxLength={200} value={what} onChange={(e) => setWhat(e.target.value)} />
            <Field label="Amount (KES)" type="number" min={0} className="w-36" value={cost} onChange={(e) => setCost(e.target.value)} />
            <Field label="Spent on" type="date" className="w-44" value={spentOn} onChange={(e) => setSpentOn(e.target.value)} />
          </div>
          <Button variant="outline" className="self-start" disabled={!what.trim() || toMinor(cost) == null || spend.isPending} onClick={() => spend.mutate()}>
            Record spending
          </Button>
        </>
      )}
    </div>
  )
}
