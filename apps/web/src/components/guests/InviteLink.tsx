import { useState } from "react"
import { Check, Copy, MessageCircle, MessageSquareText } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { whatsappLink } from "@/lib/guests"

/**
 * The link to join, shown to staff once, right after they invite somebody (only its hash is kept).
 * They share it by WhatsApp or SMS, or copy it; an emailed invitation already has it.
 */
export function InviteLink({ link, name, club, phone, emailed, member = false, onDone }: { link: string; name: string; club?: string; phone?: string | null; emailed?: boolean; /** Added as a club member, not entered in a tournament. */ member?: boolean; onDone?: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  const text = member
    ? `Hi ${name}, ${club || "the club"} added you as a member on Coast TT. Set your password and sign in: ${link}`
    : `Hi ${name}, ${club || "an organizer"} entered you on Coast TT. Join to see your entries: ${link}`
  const sms = `sms:${phone ?? ""}?body=${encodeURIComponent(text)}`
  return (
    <div role="status" className="flex basis-full flex-col gap-3 rounded-xl border border-brand-blue/40 bg-surface-selected p-4">
      <p className="font-semibold">
        {emailed ? `We emailed ${name} a link to ${member ? "set a password and sign in" : "join"}.` : `Send ${name} this link to ${member ? "set a password and sign in" : "join"}.`} It works once and lasts 14 days, and you'll only see it now.
      </p>
      <p className="rounded-lg border bg-card p-2 font-mono text-sm break-all select-all">{link}</p>
      <div className="flex flex-wrap gap-2">
        <a href={whatsappLink(link, name, club, phone, member)} target="_blank" rel="noopener noreferrer" className={buttonVariants({ size: "sm" })}>
          <MessageCircle aria-hidden className="size-4" /> WhatsApp
        </a>
        {phone && (
          <a href={sms} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <MessageSquareText aria-hidden className="size-4" /> SMS
          </a>
        )}
        <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
          {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />} {copied ? "Copied" : "Copy link"}
        </Button>
        {onDone && (
          <Button type="button" variant="ghost" size="sm" onClick={onDone}>
            Done
          </Button>
        )}
      </div>
    </div>
  )
}
