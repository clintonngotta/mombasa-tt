import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, FileText, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { formatDay } from "@/lib/dates"
import {
  amendReport,
  deleteReport,
  draftReport,
  getFinanceSettings,
  listReports,
  moneyText,
  publishReport,
  reportFileUrl,
  reportKeys,
  saveFinanceSettings,
  updateReport,
  type AnnualReport,
  type ReportCurrency,
} from "@/lib/finance"
import { cn } from "@/lib/utils"

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
const LINK = "flex items-center gap-2 font-semibold text-brand-blue underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"

/** The club's annual financial reports (REQ-041). Members read the published ones; finance managers draft
 * a finished year, add a summary, publish, and amend later. Totals only: no member, payer or payee. */
export function AnnualReportsPage() {
  const { active } = useActiveMembership()
  const queryClient = useQueryClient()
  const orgId = active?.organization.id ?? ""
  const manager = can(active, "finances.manage")
  const reports = useQuery({ queryKey: reportKeys.list(orgId), queryFn: () => listReports(orgId), enabled: !!orgId, staleTime: 0 })
  const refresh = () => queryClient.invalidateQueries({ queryKey: reportKeys.list(orgId) })
  const draft = useMutation({ mutationFn: () => draftReport(orgId), onSuccess: refresh })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">{active?.organization.name ?? "Club"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Annual reports</h1>
        <p className="text-muted-foreground">The club's accounts, year by year: what came in, what was spent and what is left.</p>
      </div>
      {reports.isError && <FormAlert>{errorMessage(reports.error, "We couldn't load the reports.")}</FormAlert>}
      {manager && <YearEnd orgId={orgId} />}
      {manager && (
        <div className="flex flex-col gap-2">
          <Button className="self-start" disabled={draft.isPending} onClick={() => draft.mutate()}>
            <Plus aria-hidden className="size-4" /> {draft.isPending ? "Preparing…" : "Draft the report for the last finished year"}
          </Button>
          {draft.isError && <FormAlert>{errorMessage(draft.error)}</FormAlert>}
        </div>
      )}
      {reports.isSuccess && reports.data.length === 0 && <p className="text-muted-foreground">No reports yet.</p>}
      {reports.data?.map((report) => (
        <Report key={report.id} orgId={orgId} report={report} onChange={refresh} />
      ))}
    </div>
  )
}

function YearEnd({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: reportKeys.settings(orgId), queryFn: () => getFinanceSettings(orgId), enabled: !!orgId })
  const save = useMutation({
    mutationFn: (month: number) => saveFinanceSettings(orgId, { year_end_month: month, year_end_day: new Date(2001, month, 0).getDate() }),
    onSuccess: (fresh) => queryClient.setQueryData(reportKeys.settings(orgId), fresh),
  })
  if (!settings.data) return null
  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="max-w-xs">
        <SelectField
          label="Financial year ends at the end of"
          options={MONTHS.map((month, i) => ({ value: String(i + 1), label: month }))}
          value={String(settings.data.year_end_month)}
          onChange={(value) => save.mutate(Number(value))}
          hint="Change it before drafting a report, not after."
        />
      </div>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
    </div>
  )
}

function Report({ orgId, report, onChange }: { orgId: string; report: AnnualReport; onChange: () => void }) {
  const [narrative, setNarrative] = useState(report.narrative)
  const draft = report.status === "draft"
  const save = useMutation({ mutationFn: () => updateReport(orgId, report.id, { narrative: narrative.trim() }), onSuccess: onChange })
  const publish = useMutation({
    mutationFn: async () => {
      if (narrative.trim() !== report.narrative) await updateReport(orgId, report.id, { narrative: narrative.trim() })
      return publishReport(orgId, report.id)
    },
    onSuccess: onChange,
  })
  const amend = useMutation({ mutationFn: () => amendReport(orgId, report.id), onSuccess: onChange })
  const discard = useMutation({ mutationFn: () => deleteReport(orgId, report.id), onSuccess: onChange })
  const share = useMutation({ mutationFn: (value: boolean) => updateReport(orgId, report.id, { public: value }), onSuccess: onChange })
  const failed = save.error ?? publish.error ?? amend.error ?? discard.error ?? share.error
  return (
    <article aria-label={`Report to ${report.period_end}, version ${report.version}`} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <header className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-xl font-bold">
          <FileText aria-hidden className="size-5 text-brand-blue" /> {formatDay(report.period_start)} to {formatDay(report.period_end)}
        </h2>
        <p className="text-sm text-muted-foreground">
          {draft ? "Draft: figures follow the ledger until you publish" : `Published${report.published_at ? ` ${formatDay(report.published_at.slice(0, 10))}` : ""}`}
          {report.version > 1 && ` · version ${report.version}, amended`}
          {report.public && " · public"}
        </p>
      </header>
      {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
      {report.changes.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border px-3 py-2">
          <h3 className="font-semibold">What this version changes</h3>
          <ul className="list-disc pl-6 text-sm">
            {report.changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
        </div>
      )}
      {report.figures.currencies.map((block) => (
        <Figures key={block.currency} block={block} />
      ))}
      {draft && report.can_edit ? (
        <TextAreaField label="Summary" optional rows={4} maxLength={5000} value={narrative} onChange={(e) => setNarrative(e.target.value)} hint="A few sentences on the year, shown with the figures." />
      ) : (
        report.narrative && <p className="whitespace-pre-wrap">{report.narrative}</p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {draft && report.can_edit && (
          <>
            <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
              {publish.isPending ? "Publishing…" : "Publish: freeze these figures"}
            </Button>
            <Button variant="outline" disabled={save.isPending || narrative.trim() === report.narrative} onClick={() => save.mutate()}>
              Save summary
            </Button>
            <Button variant="outline" disabled={discard.isPending} onClick={() => discard.mutate()}>
              Discard draft
            </Button>
          </>
        )}
        {!draft && report.can_edit && (
          <>
            <Button variant="outline" disabled={amend.isPending} onClick={() => amend.mutate()}>
              Amend: start a corrected version
            </Button>
            <label className="flex min-h-12 items-center gap-2">
              <input type="checkbox" className="size-5 accent-brand-blue" checked={report.public} disabled={share.isPending} onChange={(e) => share.mutate(e.target.checked)} />
              Public: anyone can read it
            </label>
          </>
        )}
        <a href={reportFileUrl(orgId, report.id, "pdf")} className={LINK}>
          <Download aria-hidden className="size-4" /> PDF
        </a>
        <a href={reportFileUrl(orgId, report.id, "csv")} className={LINK}>
          <Download aria-hidden className="size-4" /> CSV
        </a>
      </div>
    </article>
  )
}

function Row({ label, amount, strong, indent }: { label: string; amount: number; strong?: boolean; indent?: boolean }) {
  return (
    <tr className={cn(strong && "font-semibold")}>
      <th scope="row" className={cn("py-1 text-left font-[inherit]", indent && "pl-4 font-normal")}>
        {label}
      </th>
      <td className={cn("py-1 text-right tabular-nums", amount < 0 && "text-destructive")}>{moneyText(amount)}</td>
    </tr>
  )
}

function Figures({ block }: { block: ReportCurrency }) {
  return (
    <table className="w-full border-collapse text-sm">
      <caption className="pb-1 text-left text-muted-foreground">Amounts in {block.currency}</caption>
      <tbody className="[&>tr]:border-b">
        <Row label="Opening balance" amount={block.opening_minor} strong />
        {block.receipts.map((row) => (
          <Row key={`in-${row.label}`} label={`Received: ${row.label}`} amount={row.amount_minor} indent />
        ))}
        <Row label="Total receipts" amount={block.receipts_minor} strong />
        {block.expenses.map((row) => (
          <Row key={`out-${row.label}`} label={`Spent: ${row.label}`} amount={row.amount_minor} indent />
        ))}
        <Row label="Total expenses" amount={block.expenses_minor} strong />
        <Row label="Closing balance" amount={block.closing_minor} strong />
        <Row label="Dues still owed at the year end" amount={block.outstanding_dues_minor} />
        <Row label="Dues waived in the year" amount={block.waived_minor} />
        {block.purposes.map((row) => (
          <Row key={`p-${row.title}`} label={`${row.title}: received less spent`} amount={row.net_minor} indent />
        ))}
      </tbody>
    </table>
  )
}
