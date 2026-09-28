// Mirrors imeto/ui/app.py views. The backend is the source of truth; nothing is
// computed here that the store already knows.

export type Ground = {
  quote: string
  start: number
  end: number
  before: string
  after: string
}
export type Impact = { quote: string; url: string; channel: "citation" | "search" }
export type FactStatus = "candidate" | "accepted" | "rejected"
export type Fact = {
  id: number
  kind: string
  statement: string
  status: FactStatus
  trail: "unknown" | "internal" | "candidate"
  query: string
  grounds: Ground[]
  impact: Impact[]
}
export type Argument = {
  id: number
  side: "for" | "against" | "gap"
  statement: string
  status: FactStatus
  sphere: Sphere | null
  facts: string[]
}
/** Criterion III's spheres of the non-academic environment. */
export const SPHERES = {
  economy: "Economy",
  public_administration: "Public administration",
  health: "Health",
  culture: "Culture & heritage",
  environment: "Environment",
  security: "Security & defence",
  other: "Other",
} as const
export type Sphere = keyof typeof SPHERES
/** OpenAlex context of a work: raw, not normalized (misleading for SSH). */
type Count = { code: string; name: string; works: number }
export type Signals = {
  cited_by?: number | null
  topic?: string | null
  field?: string | null
  reach?: { citing: number; countries: Count[]; fields: Count[] }
  pinned?: { title: string; url: string; snippet: string }[]
}
export type EntityKind = "institution" | "author"
export type Entity = { id: string; display_name: string; detail: string; works_count: number }
export type LeadWork = {
  id: string
  title: string
  year: number | null
  doi: string | null
  type: string | null
  venue: string | null
}
export type Org = {
  id: string
  name: string
  type: string
  country: string | null
  works_count: number
}
export type SourceDetail = {
  id: number
  title: string
  identifier: string
  type: string | null
  language: string | null
  doi: string | null
  chars: number
  head: string
  signals: Signals | null
  facts: Fact[]
  arguments: Argument[]
}
export type SourceItem = {
  id: number
  title: string
  sub: string
  facts: number
  candidate: number
  accepted: number
  queries: number
  impact: number
  arguments: number
}
export type Config = { base_url: string; model: string; work_types: string[] }
export type ModelSettings = { base_url: string; model: string }
export type Phase = "extract" | "suggest" | "corroborate" | "argue"
export type RunEvent = { status?: string; log?: string; error?: string }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

const send = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
})

export const api = {
  config: () => fetch("/api/config").then((r) => json<Config>(r)),
  sources: () => fetch("/api/sources").then((r) => json<SourceItem[]>(r)),
  source: (id: number) => fetch(`/api/sources/${id}`).then((r) => json<SourceDetail>(r)),
  addSource: (form: FormData) =>
    fetch("/api/sources", { method: "POST", body: form }).then((r) =>
      json<{ id: number }>(r),
    ),
  acceptAll: (id: number) =>
    fetch(`/api/sources/${id}/accept-all`, { method: "POST" }).then((r) =>
      json<SourceDetail>(r),
    ),
  patchClaim: (id: number, body: { accepted?: boolean; query?: string }) =>
    fetch(`/api/claims/${id}`, send("PATCH", body)).then((r) => json(r)),
  patchArgument: (id: number, body: { accepted?: boolean; sphere?: string }) =>
    fetch(`/api/arguments/${id}`, send("PATCH", body)).then((r) => json(r)),
  buildCase: (entity: string, citing: string, via: string) =>
    fetch(`/api/leads/${entity}/case/${citing}?via=${encodeURIComponent(via)}`, {
      method: "POST",
    }).then((r) => json<{ id: number }>(r)),
  refreshSignals: (id: number) =>
    fetch(`/api/sources/${id}/signals`, { method: "POST" }).then((r) =>
      json<{ signals: Signals | null }>(r),
    ),
  searchEntities: (q: string, kind: EntityKind) =>
    fetch(`/api/leads/search?q=${encodeURIComponent(q)}&kind=${kind}`).then((r) => json<Entity[]>(r)),
  partners: (e: string) => fetch(`/api/leads/${e}/partners`).then((r) => json<Org[]>(r)),
  partnerWorks: (e: string, org: string) =>
    fetch(`/api/leads/${e}/partners/${org}`).then((r) => json<LeadWork[]>(r)),
  reports: (e: string) => fetch(`/api/leads/${e}/reports`).then((r) => json<LeadWork[]>(r)),
  citing: (e: string) =>
    fetch(`/api/leads/${e}/citing`).then((r) => json<{ cited_works: number; orgs: Org[] }>(r)),
  citingWorks: (e: string, org: string) =>
    fetch(`/api/leads/${e}/citing/${org}`).then((r) => json<LeadWork[]>(r)),
  stop: () => fetch("/api/stop", { method: "POST" }),
  csvUrl: (id: number) => `/api/sources/${id}/facts.csv`,
}

/** Runs a phase and feeds its NDJSON progress events to `onEvent` as they arrive. */
export async function runPhase(
  sourceId: number,
  phase: Phase,
  model: ModelSettings,
  onEvent: (e: RunEvent) => void,
): Promise<void> {
  const res = await fetch(`/api/sources/${sourceId}/run/${phase}`, send("POST", model))
  if (!res.ok || !res.body) {
    await json(res)
    return
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    const lines = buf.split("\n")
    buf = lines.pop() ?? ""
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line) as RunEvent)
  }
}
