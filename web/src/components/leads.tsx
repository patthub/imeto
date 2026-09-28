import { useMemo, useState } from "react"
import { useNavigate } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Building2, Download, EyeOff, Loader2, Plus, Search, User } from "lucide-react"
import { toast } from "sonner"

import { EmptyNote, Tag, Toggle } from "@/components/blocks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api, type EntityKind, type LeadWork, type Org } from "@/lib/api"
import { cn } from "@/lib/utils"

type Picked = { id: string; name: string; kind: EntityKind }
type Tab = "partners" | "citing" | "reports"

// per-viewer conveniences: storage may be blocked, the page works without it
function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* not remembered — fine */
  }
}

const TYPE: Record<string, string> = {
  government: "Public body",
  nonprofit: "Non-profit",
  company: "Company",
  healthcare: "Healthcare",
  archive: "Archive / museum",
  other: "Other",
}
const PAGE = 100

/** Impact leads (SSH, OpenAlex) — the SSH-honest take on commercial "societal impact
 *  profiles": named organizations and documents to follow up. No normalized scores:
 *  for SSH they mislead. Leads, never evidence — a case still needs a quoted trail. */
export function LeadsPage() {
  const [picked, setPicked] = useState<Picked | null>(() => load("imeto.leads.entity", null))
  const [tab, setTab] = useState<Tab>("partners")
  const pick = (p: Picked) => {
    setPicked(p)
    save("imeto.leads.entity", p)
  }
  return (
    <div className="h-full overflow-y-auto px-4 md:px-12">
      <div className="mx-auto max-w-[1060px] pt-9 pb-28">
        <header>
          <h1 className="text-[32px] leading-tight font-bold tracking-[-0.015em]">
            {picked?.name ?? "Impact leads"}
          </h1>
          <p className="mt-1.5 max-w-[66ch] text-muted-foreground">
            Where to look for Criterion III cases in the social sciences and humanities: who
            outside academia works with you, who outside academia cites you, and your
            reports. Leads to follow — not evidence of impact.
          </p>
        </header>
        <Picker onPick={pick} />
        {picked ? (
          <>
            <nav className="mt-7 flex gap-1 border-b" aria-label="Lead lists">
              <TabBtn active={tab === "partners"} onClick={() => setTab("partners")}>Co-authors <span className="text-xs text-muted-foreground">· potential</span></TabBtn>
              <TabBtn active={tab === "citing"} onClick={() => setTab("citing")}>Cited by <span className="text-xs text-muted-foreground">· observed</span></TabBtn>
              <TabBtn active={tab === "reports"} onClick={() => setTab("reports")}>Reports</TabBtn>
            </nav>
            {tab === "partners" && <Partners entity={picked.id} />}
            {tab === "citing" && <Citing entity={picked.id} />}
            {tab === "reports" && <Reports entity={picked.id} />}
          </>
        ) : (
          <EmptyNote>Find your institution or a researcher to see their leads.</EmptyNote>
        )}
      </div>
    </div>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active}
      className={cn(
        "-mb-px border-b-2 px-2 pb-2 text-sm transition-colors",
        active ? "border-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  )
}

function Picker({ onPick }: { onPick: (p: Picked) => void }) {
  const [kind, setKind] = useState<EntityKind>("institution")
  const [q, setQ] = useState("")
  const [sent, setSent] = useState("")
  const { data, isFetching, error } = useQuery({
    queryKey: ["entities", kind, sent],
    queryFn: () => api.searchEntities(sent, kind),
    enabled: sent.length > 1,
  })
  const Icon = kind === "author" ? User : Building2
  return (
    <div className="mt-5 max-w-md">
      <div className="flex gap-1 text-sm">
        {(["institution", "author"] as const).map((k) => (
          <Button key={k} variant={kind === k ? "secondary" : "ghost"} size="xs" onClick={() => setKind(k)}>
            {k === "institution" ? "Institution" : "Researcher"}
          </Button>
        ))}
      </div>
      <form
        className="relative mt-2"
        onSubmit={(e) => {
          e.preventDefault()
          setSent(q.trim())
        }}
      >
        <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={kind === "author" ? "Researcher's name, then Enter" : "e.g. University of Warsaw, then Enter"}
          aria-label="Name"
          className="pl-8"
        />
      </form>
      {isFetching && <Loader2 className="mt-2 size-4 animate-spin text-muted-foreground" />}
      {error && <p className="mt-2 text-sm text-destructive">{error.message}</p>}
      {data && sent && (
        <ul className="mt-1">
          {data.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => {
                  onPick({ id: e.id, name: e.display_name, kind })
                  setSent("")
                  setQ("")
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted"
              >
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{e.display_name}</span>
                <span className="max-w-[45%] truncate text-xs text-muted-foreground">{e.detail}</span>
              </button>
            </li>
          ))}
          {data.length === 0 && <li className="px-2 py-1.5 text-sm text-muted-foreground">No match.</li>}
        </ul>
      )}
    </div>
  )
}

function Partners({ entity }: { entity: string }) {
  const q = useQuery({ queryKey: ["partners", entity], queryFn: () => api.partners(entity), staleTime: Infinity })
  return (
    <OrgList
      query={q}
      note="Potential impact: non-academic organizations that co-authored your SSH works — the research was made with, not just for, society. Impact may follow; it isn't shown yet."
      countLabel="co-authored"
      works={(org) => api.partnerWorks(entity, org)}
      worksKey={["partnerWorks", entity]}
      csvName={`${entity}-co-authors.csv`}
    />
  )
}

function Citing({ entity }: { entity: string }) {
  const q = useQuery({ queryKey: ["citing", entity], queryFn: () => api.citing(entity), staleTime: Infinity })
  return (
    <OrgList
      query={{ ...q, data: q.data?.orgs }}
      note={
        q.data
          ? `Observed use: non-academic organizations whose authors cite your ${q.data.cited_works.toLocaleString("en")} cited SSH works. Counts are approximate; open a row for the exact works, then "Build case" on one.`
          : "Scanning every cited work — can take a minute the first time today."
      }
      countLabel="citing"
      works={(org) => api.citingWorks(entity, org)}
      worksKey={["citingWorks", entity]}
      caseFor={(w, org) => api.buildCase(entity, w.id, org.name)}
      csvName={`${entity}-cited-by.csv`}
    />
  )
}

function Reports({ entity }: { entity: string }) {
  const { data, isPending, error } = useQuery({
    queryKey: ["reports", entity],
    queryFn: () => api.reports(entity),
    staleTime: Infinity,
  })
  if (isPending) return <Loading />
  if (error) return <EmptyNote>{error.message}</EmptyNote>
  return (
    <section className="mt-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-[70ch] text-[13px] text-muted-foreground">
          Your SSH works typed as reports: expert opinions, policy papers, project
          deliverables — often the first written trace of impact.
        </p>
        <CsvButton name={`${entity}-reports.csv`} rows={data.map((w) => ({ year: w.year, title: w.title, venue: w.venue, doi: w.doi }))} />
      </div>
      {data.length === 0 ? <EmptyNote>No reports found.</EmptyNote> : <WorkList works={data} />}
    </section>
  )
}

function OrgList({
  query,
  note,
  countLabel,
  works,
  worksKey,
  csvName,
  caseFor,
}: {
  query: { data?: Org[]; isPending: boolean; error: Error | null }
  note: string
  countLabel: string
  works: (org: string) => Promise<LeadWork[]>
  worksKey: string[]
  csvName: string
  caseFor?: (w: LeadWork, org: Org) => Promise<{ id: number }>
}) {
  const [text, setText] = useState("")
  const [type, setType] = useState<string | null>(null)
  const [hidden, setHidden] = useState<string[]>(() => load("imeto.leads.hidden", []))
  const [showHidden, setShowHidden] = useState(false)
  const [limit, setLimit] = useState(PAGE)
  const hide = (id: string) => {
    const next = hidden.includes(id) ? hidden.filter((h) => h !== id) : [...hidden, id]
    setHidden(next)
    save("imeto.leads.hidden", next)
  }
  const all = query.data ?? []
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase()
    return all.filter(
      (o) =>
        (showHidden || !hidden.includes(o.id)) &&
        (type === null || o.type === type) &&
        (!t || o.name.toLowerCase().includes(t) || (o.country ?? "").toLowerCase() === t),
    )
  }, [all, text, type, hidden, showHidden])
  const byType = useMemo(() => {
    const m: Record<string, number> = {}
    for (const o of all) if (!hidden.includes(o.id)) m[o.type] = (m[o.type] ?? 0) + 1
    return m
  }, [all, hidden])

  return (
    <section className="mt-4">
      <p className="max-w-[70ch] text-[13px] text-muted-foreground">{note}</p>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <EmptyNote>{query.error.message}</EmptyNote>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <div className="relative mr-1">
              <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  setLimit(PAGE)
                }}
                placeholder="Filter by name or country (PL)"
                aria-label="Filter organizations"
                className="h-7 w-60 pl-7 text-sm"
              />
            </div>
            <Chip active={type === null} onClick={() => setType(null)}>
              All {all.length - hidden.filter((h) => all.some((o) => o.id === h)).length}
            </Chip>
            {Object.entries(TYPE).map(([k, label]) =>
              byType[k] ? (
                <Chip key={k} active={type === k} onClick={() => setType(type === k ? null : k)}>
                  {label} {byType[k]}
                </Chip>
              ) : null,
            )}
            <span className="ml-auto flex items-center gap-1">
              {hidden.length > 0 && (
                <Button variant="ghost" size="xs" onClick={() => setShowHidden(!showHidden)}>
                  {showHidden ? "Hide hidden" : `Show hidden (${hidden.length})`}
                </Button>
              )}
              <CsvButton
                name={csvName}
                rows={rows.map((o) => ({ name: o.name, type: TYPE[o.type] ?? o.type, country: o.country, works: o.works_count, openalex: `https://openalex.org/${o.id}` }))}
              />
            </span>
          </div>
          {rows.length === 0 ? (
            <EmptyNote>Nothing matches.</EmptyNote>
          ) : (
            <ul className="mt-3 divide-y border-y">
              {rows.slice(0, limit).map((o) => (
                <li key={o.id} className={cn("group/org flex items-start gap-2 py-1.5", hidden.includes(o.id) && "opacity-50")}>
                  <div className="min-w-0 flex-1">
                    <Toggle
                      title={
                        <span className="flex flex-wrap items-center gap-2 text-left text-foreground">
                          <span className="font-medium">{o.name}</span>
                          <Tag>{TYPE[o.type] ?? o.type}</Tag>
                          {o.country && <span className="text-xs text-muted-foreground">{o.country}</span>}
                          <span className="text-xs text-muted-foreground tabular-nums">
                            {o.works_count} {countLabel}
                          </span>
                        </span>
                      }
                    >
                      <OrgWorks
                        load={() => works(o.id)}
                        queryKey={[...worksKey, o.id]}
                        caseFor={caseFor && ((w) => caseFor(w, o))}
                      />
                    </Toggle>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="mt-0.5 opacity-0 group-hover/org:opacity-100 focus-visible:opacity-100"
                    aria-label={hidden.includes(o.id) ? `Unhide ${o.name}` : `Hide ${o.name} — not a real non-academic partner`}
                    title={hidden.includes(o.id) ? "Unhide" : "Hide: not really outside academia"}
                    onClick={() => hide(o.id)}
                  >
                    <EyeOff />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {rows.length > limit && (
            <Button variant="ghost" size="sm" className="mt-2" onClick={() => setLimit(limit + PAGE)}>
              Show {Math.min(PAGE, rows.length - limit)} more of {rows.length - limit}
            </Button>
          )}
        </>
      )}
    </section>
  )
}

/** Mounted only when a row opens — the works are fetched on demand. */
function OrgWorks({
  load,
  queryKey,
  caseFor,
}: {
  load: () => Promise<LeadWork[]>
  queryKey: string[]
  caseFor?: (w: LeadWork) => Promise<{ id: number }>
}) {
  const { data, isPending, error } = useQuery({ queryKey, queryFn: load, staleTime: Infinity })
  if (isPending) return <Loader2 className="my-2 size-4 animate-spin text-muted-foreground" />
  if (error) return <p className="py-2 text-sm text-destructive">{error.message}</p>
  if (data.length === 0) return <p className="py-2 text-sm text-muted-foreground">No works listed.</p>
  return <WorkList works={data} caseFor={caseFor} />
}

/** A lead becomes a source with one click — then it goes through extraction and the
 *  verbatim gate like anything else. With `caseFor` (citing documents) the click
 *  instead builds a case: OUR cited work becomes the source and this document is
 *  pinned as its first corroboration candidate. */
function WorkList({
  works,
  caseFor,
}: {
  works: LeadWork[]
  caseFor?: (w: LeadWork) => Promise<{ id: number }>
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: (w: LeadWork) => {
      if (caseFor) return caseFor(w)
      const form = new FormData()
      form.set("mode", "DOI")
      form.set("doi", w.doi ?? "")
      form.set("work_type", w.type === "report" ? "report" : "article")
      form.set("full_text", "true")
      return api.addSource(form)
    },
    onSuccess: ({ id }) => {
      void qc.invalidateQueries({ queryKey: ["sources"] })
      navigate(`/sources/${id}`)
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <ul className="space-y-0.5 pb-1">
      {works.map((w) => (
        <li key={w.id} className="group/work flex items-start gap-3 rounded-sm px-1 py-1 hover:bg-muted/50">
          <span className="w-10 shrink-0 pt-px text-xs text-muted-foreground tabular-nums">{w.year}</span>
          <span className="min-w-0 flex-1 text-sm">
            {w.doi ? (
              <a href={w.doi} target="_blank" rel="noreferrer" className="hover:underline">
                {w.title}
              </a>
            ) : (
              w.title
            )}
            {w.venue && <span className="block truncate text-xs text-muted-foreground">{w.venue}</span>}
          </span>
          {(w.doi || caseFor) && (
            <Button
              variant="ghost"
              size="xs"
              className="shrink-0 opacity-0 group-hover/work:opacity-100 focus-visible:opacity-100"
              disabled={add.isPending}
              onClick={() => add.mutate(w)}
            >
              {add.isPending && add.variables === w ? <Loader2 className="animate-spin" /> : <Plus />}
              {caseFor ? "Build case" : "Add as source"}
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-2.5 text-xs leading-6 tabular-nums transition-colors",
        active ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  )
}

function CsvButton({ name, rows }: { name: string; rows: Record<string, unknown>[] }) {
  const download = () => {
    const cols = Object.keys(rows[0] ?? {})
    const cell = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`
    const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n")
    const a = document.createElement("a")
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }))
    a.download = name
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <Button variant="ghost" size="xs" disabled={rows.length === 0} onClick={download}>
      <Download />
      CSV
    </Button>
  )
}

function Loading() {
  return (
    <div className="mt-4 space-y-2">
      <Skeleton className="h-7 w-2/3" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}
