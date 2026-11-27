/** Matching typed text against names in lists that are already on the screen. */

/** Lower case without accents, so "wanjiru" finds "Wanjirũ". */
export const fold = (text: string) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase()

/** Whether every word typed appears in one of the texts. An empty search matches everything. */
export function matchesSearch(term: string, ...texts: (string | null | undefined)[]) {
  const words = fold(term).split(/\s+/).filter(Boolean)
  if (words.length === 0) return true
  const haystack = fold(texts.filter(Boolean).join(" "))
  return words.every((word) => haystack.includes(word))
}

/** An entry as searched: its title (team or players) and every player's name. */
export const entryText = (entry: { title: string; players?: { display_name: string }[] } | null | undefined) =>
  entry ? [entry.title, ...(entry.players ?? []).map((player) => player.display_name)].join(" ") : ""
