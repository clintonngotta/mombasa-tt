import { useState, type FormEvent } from "react"
import { useMutation } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { sendAnnouncement } from "@/lib/notifications"

/** Send an announcement to every member's inbox (REQ-019). */
export function AnnouncePage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "announcements.manage")
  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const send = useMutation({ mutationFn: () => sendAnnouncement(orgId, { title: title.trim(), body: body.trim(), audience: "members" }) })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    send.mutate()
  }
  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Announce to members</h1>
      {memberships.isSuccess && !allowed && <AccessLost />}
      {allowed && (
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <Field label="Title" maxLength={140} value={title} onChange={(e) => setTitle(e.target.value)} />
          <TextAreaField label="Message" optional maxLength={500} rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
          {send.isError && <FormAlert>{errorMessage(send.error)}</FormAlert>}
          {send.isSuccess && (
            <p role="status" className="text-success">
              Sent to {send.data.sent} {send.data.sent === 1 ? "member" : "members"}.
            </p>
          )}
          <Button type="submit" className="self-start" disabled={!title.trim() || send.isPending}>
            {send.isPending ? "Sending…" : "Send to all members"}
          </Button>
        </form>
      )}
    </div>
  )
}
