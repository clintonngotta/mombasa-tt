import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react"
import { fits, readDraft, removeDraft, writeDraft } from "@/lib/drafts"
import { lastAccount } from "@/lib/offline"

type Field = { value: unknown; initial: unknown; set: (value: unknown) => void }

export type Draft = {
  /** False when nobody is signed in on this device: the form works as before, with nothing kept. */
  enabled: boolean
  /** When the draft on this device was saved, if there is one. */
  savedAt: number | null
  /** True while the form shows values that came from a kept draft. */
  restored: boolean
  failed: boolean
  save: () => void
  /** Remove the draft and put the form back as it was. */
  discard: () => void
  /** Remove the draft once the form was sent. */
  clear: () => void
  /** For useDraftState. */
  take: <T>(key: string, initial: T) => T
  fields: { current: Map<string, Field> }
}

const storage = () => {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/**
 * A form's draft on this device. `form` names the form and what it edits ("tournament:new",
 * `event:${id}`); pass null where a draft makes no sense. Fields join with useDraftState, the form
 * shows <DraftBar>, and calls `clear()` when it was sent.
 */
export function useDraft(form: string | null): Draft {
  const [userId] = useState(lastAccount)
  const name = userId && form ? form : null
  const [kept] = useState(() => {
    const store = storage()
    return store && userId && name ? readDraft(store, userId, name) : null
  })
  const [savedAt, setSavedAt] = useState<number | null>(kept?.at ?? null)
  const [restored, setRestored] = useState(kept !== null)
  const [failed, setFailed] = useState(false)
  const fields = useRef(new Map<string, Field>())
  const live = useRef(kept)

  // The form's name can settle after the first render (the active club loads): look again then.
  const read = useRef(name)
  useEffect(() => {
    if (read.current === name) return
    read.current = name
    const store = storage()
    const found = store && userId && name ? readDraft(store, userId, name) : null
    live.current = found
    if (found) {
      for (const [key, field] of fields.current) if (fits(found.values[key], field.initial)) field.set(found.values[key])
    }
    setSavedAt(found?.at ?? null)
    setRestored(found !== null)
    setFailed(false)
  }, [userId, name])

  const save = useCallback(() => {
    const store = storage()
    if (!store || !userId || !name) return setFailed(true)
    const values = Object.fromEntries([...fields.current].map(([key, field]) => [key, field.value]))
    const now = Date.now()
    const done = writeDraft(store, userId, name, values, now)
    setFailed(!done)
    if (done) {
      setSavedAt(now)
      setRestored(false)
    }
  }, [userId, name])

  const drop = useCallback(() => {
    const store = storage()
    if (store && userId && name) removeDraft(store, userId, name)
    live.current = null
    setSavedAt(null)
    setRestored(false)
    setFailed(false)
  }, [userId, name])

  const discard = useCallback(() => {
    drop()
    for (const field of fields.current.values()) field.set(field.initial)
  }, [drop])

  const take = useCallback(<T>(key: string, initial: T): T => {
    const value = live.current?.values[key]
    return fits(value, initial) ? (value as T) : initial
  }, [])

  return useMemo(
    () => ({ enabled: name !== null, savedAt, restored, failed, save, discard, clear: drop, take, fields }),
    [name, savedAt, restored, failed, save, discard, drop, take],
  )
}

/** useState for a form field that belongs to a draft. Only plain values: text, numbers, choices, lists of them. */
export function useDraftState<T>(draft: Draft, key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const [first] = useState(initial)
  const [value, setValue] = useState<T>(() => draft.take(key, first))
  const { fields } = draft
  useEffect(() => {
    fields.current.set(key, { value, initial: first, set: (next) => setValue(next as T) })
  }, [fields, key, value, first])
  useEffect(() => {
    const all = fields.current
    return () => void all.delete(key)
  }, [fields, key])
  return [value, setValue]
}
