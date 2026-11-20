import { createLucideIcon } from "lucide-react"

/** A table tennis bat and ball, drawn in Lucide's 24px stroke style so it sits with the other nav icons. */
export const BatIcon = createLucideIcon("table-tennis-bat", [
  ["circle", { cx: "9.5", cy: "9.5", r: "6.5", key: "blade" }],
  ["path", { d: "m14.2 14.2 2.3 2.3", key: "neck" }],
  ["path", { d: "m16.5 16.5 3.6 3.6a1.4 1.4 0 0 1-2 2l-3.6-3.6", key: "handle" }],
  ["circle", { cx: "19.5", cy: "5", r: "1.5", key: "ball" }],
])
