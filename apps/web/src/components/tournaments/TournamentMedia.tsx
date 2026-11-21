import { useRef, useState, type ChangeEvent, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Download, FileText, ImagePlus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, apiOriginUrl, errorMessage } from "@/lib/api"
import { getAttachmentLink, type AttachmentLink } from "@/lib/profile"
import {
  addTournamentDocument,
  MAX_TOURNAMENT_DOCUMENTS,
  removeTournamentCover,
  removeTournamentDocument,
  tournamentKeys,
  uploadTournamentCover,
  type Tournament,
} from "@/lib/tournaments"

const IMAGE_TYPES = "image/jpeg,image/png,image/webp"
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const MAX_PDF_BYTES = 10 * 1024 * 1024

/** The tournament's cover picture, wide across the top of its page or card. Signed links expire after a
 * few minutes, so a failed load asks once for a new one and otherwise hides the picture. */
export function TournamentCover({ cover, className }: { cover: AttachmentLink | null; className?: string }) {
  const [retry, setRetry] = useState<{ after: string; url: string | null } | null>(null)
  if (!cover) return null
  const url = retry?.after === cover.url ? retry.url : cover.url
  if (!url) return null

  function onError() {
    if (!cover || retry?.after === cover.url) return setRetry({ after: cover!.url, url: null })
    getAttachmentLink(cover.id)
      .then((fresh) => setRetry({ after: cover.url, url: fresh.url }))
      .catch(() => setRetry({ after: cover.url, url: null }))
  }

  return <img src={apiOriginUrl(url)} alt="" onError={onError} className={className ?? "aspect-[16/7] w-full rounded-xl bg-surface-selected object-cover"} />
}

/** Download a document with a fresh link: the one in the tournament may have expired. */
async function download(file: AttachmentLink) {
  const fresh = await getAttachmentLink(file.id).catch(() => file)
  window.location.assign(apiOriginUrl(fresh.url))
}

/** Documents with further details (prospectus, rules, entry form) for everyone who sees the tournament. */
export function TournamentDocuments({ tournament: t }: { tournament: Tournament }) {
  if (t.documents.length === 0) return null
  return (
    <section aria-labelledby="documents-heading" className="flex flex-col gap-2">
      <h2 id="documents-heading" className="text-xl font-bold">
        Documents
      </h2>
      <ul className="flex flex-col gap-2">
        {t.documents.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              onClick={() => void download(d.file)}
              className="flex min-h-12 w-full items-center gap-3 rounded-xl border bg-card px-4 py-2 text-left font-semibold outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <FileText aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="min-w-0 flex-1 break-words">{d.title}</span>
              <Download aria-hidden className="size-5 text-muted-foreground" />
              <span className="sr-only">Download PDF</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function fileError(error: unknown, fallback: string) {
  return (error instanceof ApiError && (error.fieldErrors().file || error.fieldErrors().title)) || errorMessage(error, fallback)
}

/** For the host's competition staff: set the cover picture and add or remove documents. */
export function TournamentMediaManager({ tournament: t }: { tournament: Tournament }) {
  const queryClient = useQueryClient()
  const coverInput = useRef<HTMLInputElement>(null)
  const [tooBig, setTooBig] = useState("")
  const [title, setTitle] = useState("")
  const [pdf, setPdf] = useState<File | null>(null)
  const pdfInput = useRef<HTMLInputElement>(null)

  const settle = (fresh: Tournament) => {
    queryClient.setQueryData(tournamentKeys.detail(t.id), fresh)
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.all, refetchType: "active" })
  }
  const cover = useMutation({ mutationFn: (file: File) => uploadTournamentCover(t.id, file), onSuccess: settle })
  const uncover = useMutation({ mutationFn: () => removeTournamentCover(t.id), onSuccess: settle })
  const add = useMutation({
    mutationFn: ({ name, file }: { name: string; file: File }) => addTournamentDocument(t.id, name, file),
    onSuccess: (fresh) => {
      settle(fresh)
      setTitle("")
      setPdf(null)
      if (pdfInput.current) pdfInput.current.value = ""
    },
  })
  const remove = useMutation({ mutationFn: (documentId: string) => removeTournamentDocument(t.id, documentId), onSuccess: settle })

  function onCover(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    cover.reset()
    if (file.size > MAX_IMAGE_BYTES) return setTooBig("Choose an image under 5 MB.")
    setTooBig("")
    cover.mutate(file)
  }

  function onAdd(e: FormEvent) {
    e.preventDefault()
    if (!pdf || !title.trim()) return
    if (pdf.size > MAX_PDF_BYTES) return setTooBig("Choose a PDF under 10 MB.")
    setTooBig("")
    add.mutate({ name: title.trim(), file: pdf })
  }

  const coverFailed = cover.error ?? uncover.error
  const docFailed = add.error ?? remove.error
  const full = t.documents.length >= MAX_TOURNAMENT_DOCUMENTS

  return (
    <section aria-labelledby="media-heading" className="flex flex-col gap-4 rounded-xl border p-4">
      <h3 id="media-heading" className="text-lg font-bold">
        Cover picture and documents
      </h3>
      <div className="flex flex-col gap-2">
        <TournamentCover cover={t.cover} />
        <div className="flex flex-wrap gap-2">
          <input ref={coverInput} type="file" accept={IMAGE_TYPES} className="sr-only" tabIndex={-1} aria-hidden onChange={onCover} />
          <Button type="button" variant="outline" disabled={cover.isPending || uncover.isPending} onClick={() => coverInput.current?.click()}>
            <ImagePlus aria-hidden className="size-5" />
            {cover.isPending ? "Uploading…" : t.cover ? "Change cover picture" : "Add a cover picture"}
          </Button>
          {t.cover && (
            <Button type="button" variant="ghost" disabled={cover.isPending || uncover.isPending} onClick={() => uncover.mutate()}>
              Remove cover
            </Button>
          )}
        </div>
        <p className="text-sm text-muted-foreground">JPEG, PNG or WebP up to 5 MB. A wide picture works best. Location and camera details are removed.</p>
        {coverFailed && <FormAlert>{fileError(coverFailed, "We couldn't save the picture. Try again.")}</FormAlert>}
      </div>

      <div className="flex flex-col gap-2">
        <p className="font-semibold">Documents</p>
        {t.documents.length === 0 && <p className="text-sm text-muted-foreground">None yet. Add the prospectus, rules or an entry form as a PDF.</p>}
        <ul className="flex flex-col gap-2">
          {t.documents.map((d) => (
            <li key={d.id} className="flex items-center gap-2 rounded-lg border px-3 py-2">
              <FileText aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="min-w-0 flex-1 break-words">{d.title}</span>
              <Button type="button" variant="ghost" size="sm" disabled={remove.isPending} onClick={() => remove.mutate(d.id)} aria-label={`Remove ${d.title}`}>
                <Trash2 aria-hidden className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
        {!full && (
          <form onSubmit={onAdd} className="flex flex-col gap-2">
            <Field label="Document title" maxLength={120} placeholder="Prospectus" value={title} onChange={(e) => setTitle(e.target.value)} />
            <label className="flex flex-col gap-1 text-sm font-semibold">
              PDF, up to 10 MB
              <input ref={pdfInput} type="file" accept="application/pdf" onChange={(e) => setPdf(e.target.files?.[0] ?? null)} />
            </label>
            <Button type="submit" variant="outline" className="self-start" disabled={!pdf || !title.trim() || add.isPending}>
              {add.isPending ? "Uploading…" : "Add document"}
            </Button>
          </form>
        )}
        {full && <p className="text-sm text-muted-foreground">A tournament can have {MAX_TOURNAMENT_DOCUMENTS} documents. Remove one to add another.</p>}
        {tooBig && <FormAlert>{tooBig}</FormAlert>}
        {docFailed && <FormAlert>{fileError(docFailed, "We couldn't save the document. Try again.")}</FormAlert>}
      </div>
    </section>
  )
}
