import { useState } from "react"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { errorMessage } from "@/lib/api"
import { changeAccount, dayLabel, listAccounts, platformKeys, type Account, type AccountChange, type AccountFilter } from "@/lib/platform"
import { useMe } from "@/lib/session"
import { ROW } from "@/lib/clubAdmin"
import { Pager, SearchBox, Tag } from "@/pages/admin/BackOffice"

const FILTERS: { value: AccountFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "admins", label: "Super admins" },
  { value: "inactive", label: "Switched off" },
]

type Step = { change: AccountChange; ask: string; confirm: string }

/** What can be done to an account, each with the question asked before it happens. */
function steps(account: Account): { label: string; step: Step }[] {
  const name = account.display_name
  return [
    account.is_active
      ? { label: "Switch off", step: { change: { is_active: false }, ask: `Switch off ${name}'s account? They are signed out everywhere and can't log in until it is switched on again.`, confirm: "Switch off" } }
      : { label: "Switch on", step: { change: { is_active: true }, ask: `Switch ${name}'s account back on? They can log in again.`, confirm: "Switch on" } },
    account.is_platform_admin
      ? { label: "Remove super admin", step: { change: { is_platform_admin: false }, ask: `Take platform authority from ${name}? They keep their account and their clubs.`, confirm: "Remove super admin" } }
      : { label: "Make super admin", step: { change: { is_platform_admin: true }, ask: `Make ${name} a platform super admin? They can do everything on Coast TT, including this.`, confirm: "Make super admin" } },
  ]
}

function AccountRow({ account, mine }: { account: Account; mine: boolean }) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<Step | null>(null)
  const change = useMutation({
    mutationFn: (body: AccountChange) => changeAccount(account.id, body),
    onSuccess: async () => {
      setStep(null)
      await queryClient.invalidateQueries({ queryKey: platformKeys.all })
    },
  })
  const contact = [account.email, account.phone].filter(Boolean).join(" · ") || "No email or phone"
  const verified = !!account.email_verified_at || !!account.phone_verified_at

  return (
    <li className={`${ROW} items-start`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="font-semibold break-words">{account.display_name}</span>
          {mine && <Tag>You</Tag>}
          {account.is_platform_admin && <Tag tone="strong">Super admin</Tag>}
          {!account.is_active && <Tag tone="warn">Switched off</Tag>}
          {!verified && <Tag>Not verified</Tag>}
        </p>
        <p className="text-sm break-all text-muted-foreground">{contact}</p>
        <p className="text-sm text-muted-foreground">
          Joined {dayLabel(account.date_joined)} · last login {dayLabel(account.last_login)} · {account.organizations}{" "}
          {account.organizations === 1 ? "organization" : "organizations"}
        </p>
        {step && (
          <div role="group" aria-label="Confirm" className="mt-2 flex flex-col gap-3 rounded-lg border bg-background p-3">
            <p>{step.ask}</p>
            {change.isError && <FormAlert>{errorMessage(change.error, "We couldn't change the account.")}</FormAlert>}
            <div className="flex flex-wrap gap-2">
              <Button variant={step.change.is_active === false || step.change.is_platform_admin === false ? "destructive" : "default"} disabled={change.isPending} onClick={() => change.mutate(step.change)}>
                {change.isPending ? "Saving…" : step.confirm}
              </Button>
              <Button variant="outline" disabled={change.isPending} onClick={() => { setStep(null); change.reset() }}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
      {!mine && !step && (
        <div className="flex flex-wrap gap-2">
          {steps(account).map((action) => (
            <Button key={action.label} variant="outline" onClick={() => setStep(action.step)}>
              {action.label}
            </Button>
          ))}
        </div>
      )}
    </li>
  )
}

/** Every account on the platform: find one, switch it off or on, give or take platform authority.
 * Nobody changes their own account here, so there is always a super admin left. */
export function AdminAccountsPage() {
  const me = useMe()
  const [search, setSearch] = useState("")
  const [show, setShow] = useState<AccountFilter>("all")
  const [page, setPage] = useState(1)
  const accounts = useQuery({
    queryKey: platformKeys.accounts(search, show, page),
    queryFn: () => listAccounts(search, show, page),
    placeholderData: keepPreviousData,
  })
  const rows = accounts.data?.results ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox label="Find an account" placeholder="Name, email or phone" onSearch={(term) => { setSearch(term); setPage(1) }} />
        <Segmented label="Which accounts" options={FILTERS} value={show} onChange={(value) => { setShow(value); setPage(1) }} />
      </div>
      <section aria-live="polite" className="flex flex-col gap-3">
        {accounts.isPending && <p className="text-muted-foreground">Loading…</p>}
        {accounts.isError && <FormAlert>{errorMessage(accounts.error, "We couldn't load the accounts.")}</FormAlert>}
        {accounts.isSuccess && (
          <p className="text-sm text-muted-foreground">
            {accounts.data.count.toLocaleString("en-KE")} {accounts.data.count === 1 ? "account" : "accounts"}
            {search && ` matching “${search}”`}
          </p>
        )}
        <ul className="flex flex-col gap-2">
          {rows.map((account) => (
            <AccountRow key={account.id} account={account} mine={account.id === me.data?.id} />
          ))}
        </ul>
      </section>
      {accounts.isSuccess && <Pager page={page} count={accounts.data.count} onPage={setPage} />}
    </div>
  )
}
