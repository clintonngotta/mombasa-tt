/**
 * Form drafts kept on this device, one per account and form. A draft holds what was typed and nothing
 * else: never passwords, codes or chosen files. It is removed when the form is sent, when the person
 * discards it, when they log out, and after KEEP_DAYS.
 */

const PREFIX = "coasttt.draft."
const KEEP_DAYS = 30
const DAY_MS = 86_400_000
/** One form's draft; long minutes fit many times over. */
export const MAX_DRAFT_BYTES = 200_000
/** Drafts one account keeps; the oldest goes first. */
export const MAX_DRAFTS = 40

export type KeptDraft = { at: number; values: Record<string, unknown> }
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">

const keyOf = (userId: string, form: string) => `${PREFIX}${userId}.${form}`

function keysOf(store: Store, userId: string) {
  const mine = `${PREFIX}${userId}.`
  const keys: string[] = []
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i)
    if (key?.startsWith(mine)) keys.push(key)
  }
  return keys
}

function parse(raw: string | null, now: number): KeptDraft | null {
  if (!raw) return null
  try {
    const kept = JSON.parse(raw) as Partial<KeptDraft> | null
    if (!kept || typeof kept.at !== "number" || typeof kept.values !== "object" || kept.values === null || Array.isArray(kept.values)) return null
    if (now - kept.at > KEEP_DAYS * DAY_MS) return null
    return { at: kept.at, values: kept.values }
  } catch {
    return null
  }
}

export function readDraft(store: Store, userId: string, form: string, now = Date.now()): KeptDraft | null {
  try {
    const key = keyOf(userId, form)
    const kept = parse(store.getItem(key), now)
    if (!kept) store.removeItem(key)
    return kept
  } catch {
    return null
  }
}

/** False when the draft is too long or the device has no room; nothing is kept then. */
export function writeDraft(store: Store, userId: string, form: string, values: Record<string, unknown>, now = Date.now()): boolean {
  try {
    const raw = JSON.stringify({ at: now, values } satisfies KeptDraft)
    if (raw.length > MAX_DRAFT_BYTES) return false
    const key = keyOf(userId, form)
    const others = keysOf(store, userId)
      .filter((other) => other !== key)
      .map((other) => ({ key: other, at: parse(store.getItem(other), now)?.at ?? 0 }))
      .sort((a, b) => a.at - b.at)
    for (const old of others.slice(0, Math.max(0, others.length - (MAX_DRAFTS - 1)))) store.removeItem(old.key)
    for (const old of others) if (old.at === 0) store.removeItem(old.key)
    store.setItem(key, raw)
    return true
  } catch {
    return false
  }
}

export function removeDraft(store: Store, userId: string, form: string) {
  try {
    store.removeItem(keyOf(userId, form))
  } catch {
    // No storage: there was nothing to remove.
  }
}

/** Logging out: nothing this account typed stays on the device. */
export function forgetDrafts(store: Store, userId: string) {
  try {
    for (const key of keysOf(store, userId)) store.removeItem(key)
  } catch {
    // No storage.
  }
}

const plain = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value)

/**
 * Whether a kept value can stand in for a field that starts as `initial`. A draft written by an older
 * version of a form, or edited by hand, must not put the wrong kind of value into the form.
 */
export function fits(kept: unknown, initial: unknown): boolean {
  if (kept === undefined) return false
  if (initial === null || initial === undefined) return kept === null || ["string", "number", "boolean"].includes(typeof kept)
  if (Array.isArray(initial)) return Array.isArray(kept) && (initial.length === 0 || kept.every((item) => fits(item, initial[0])))
  if (plain(initial)) return plain(kept) && Object.keys(initial).every((key) => !(key in kept) || kept[key] === null || fits(kept[key], initial[key]))
  return typeof kept === typeof initial
}
