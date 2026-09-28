import { useEffect, useRef, useState } from "react"
import { useParams } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Check, CornerDownRight, Download, Loader2, Play, Search } from "lucide-react"
import { toast } from "sonner"

import { EmptyNote, Kbd, Tag, Toggle, type TagColor } from "@/components/blocks"
import { FACT_GRID, FactPeek, FactRow, useClaimPatch } from "@/components/facts"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { api, SPHERES, type Argument, type Fact, type Phase, type Sphere, type SourceDetail } from "@/lib/api"
import { useRunner } from "@/lib/runner"
import { cn } from "@/lib/utils"

type Tab = "facts" | "assessment"
type Filter = "review" | "accepted" | "rejected" | "impact" | "all"

const FILTERS: { key: Filter; label: string; test: (f: Fact) => boolean }[] = [
  { key: "review", label: "To review", test: (f) => f.status === "candidate" },
  { key: "accepted", label: "Accepted", test: (f) => f.status === "accepted" },
  { key: "rejected", label: "Rejected", test: (f) => f.status === "rejected" },
  { key: "impact", label: "With impact", test: (f) => f.impact.length > 0 },
  { key: "all", label: "All", test: () => true },
]
const testOf = (key: Filter) => FILTERS.find((f) => f.key === key)!.test

const STEPS: { phase: Phase; label: string; hint: string; done: (s: SourceDetail) => boolean }[] = [
  { phase: "extract", label: "Extract facts", hint: "Keeps only what it can quote word for word", done: (s) => s.facts.length > 0 },
  { phase: "suggest", label: "Propose queries", hint: "A search query per accepted fact", done: (s) => s.facts.some((f) => f.query) },
  { phase: "corroborate", label: "Corroborate", hint: "Pinned leads and citing works first, then the web", done: (s) => s.facts.some((f) => f.impact.length > 0) },
  { phase: "argue", label: "Assess", hint: "Criterion III: for, against, gaps", done: (s) => s.arguments.length > 0 },
]

const SIDES: { side: Argument["side"]; label: string; color: TagColor }[] = [
  { side: "for", label: "For", color: "green" },
  { side: "against", label: "Against", color: "red" },
  { side: "gap", label: "Gaps", color: "yellow" },
]

export function SourcePage() {
  const sourceId = Number(useParams().id)
  // keyed by id: filters, selection and the open peek start fresh on every source
  return <SourceLoader key={sourceId} sourceId={sourceId} />
}

function SourceLoader({ sourceId }: { sourceId: number }) {
  const { data: source, isPending, error } = useQuery({
    queryKey: ["source", sourceId],
    queryFn: () => api.source(sourceId),
  })
  if (isPending)
    return (
      <div className="mx-auto max-w-[1060px] space-y-4 px-4 pt-12 md:px-12">
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  if (error) return <EmptyNote>{error.message}</EmptyNote>
  return <Workspace source={source} />
}

function Workspace({ source }: { source: SourceDetail }) {
  const [tab, setTab] = useState<Tab>("facts")
  const [filter, setFilter] = useState<Filter>(() =>
    source.facts.some((f) => f.status === "candidate") ? "review" : "all",
  )
  const [query, setQuery] = useState("")
  const [sel, setSel] = useState(0)
  const [peekOpen, setPeekOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const patch = useClaimPatch(source.id)

  const q = query.trim().toLowerCase()
  const rows = source.facts
    .map((fact, i) => ({ fact, n: i + 1 }))
    .filter(({ fact }) => testOf(filter)(fact))
    .filter(
      ({ fact }) =>
        !q || [fact.statement, fact.query, ...fact.grounds.map((g) => g.quote)].some((t) => t.toLowerCase().includes(q)),
    )
  // clamped on every render: when a decided fact leaves the filter, the next one
  // slides under the cursor (and into the peek) without extra bookkeeping
  const index = rows.length ? Math.min(sel, rows.length - 1) : -1
  const current = index >= 0 ? rows[index] : null

  const move = (delta: number) => {
    if (rows.length) setSel(Math.max(0, Math.min(index + delta, rows.length - 1)))
  }
  const decide = (fact: Fact, accepted: boolean, advance: boolean) => {
    patch.mutate({ id: fact.id, body: { accepted } })
    const stays = testOf(filter)({ ...fact, status: accepted ? "accepted" : "rejected" })
    if (advance && stays) move(1)
  }
  const openFact = (id: number) => {
    setTab("facts")
    setFilter("all")
    setQuery("")
    setSel(source.facts.findIndex((f) => f.id === id))
    setPeekOpen(true)
  }

  // triage from the keyboard; re-subscribed each render so it sees current rows
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest("[role=dialog], [role=menu], [role=listbox]")) return
      const typing = el.matches("input, textarea, [contenteditable=true]")
      if (e.key === "Escape") {
        if (typing) el.blur()
        else setPeekOpen(false)
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey || tab !== "facts") return
      if (e.key === "Enter" && el.closest("button, a")) return
      const keys: Record<string, () => void> = {
        j: () => move(1),
        ArrowDown: () => move(1),
        k: () => move(-1),
        ArrowUp: () => move(-1),
        Enter: () => current && setPeekOpen(true),
        o: () => current && setPeekOpen(true),
        a: () => current && decide(current.fact, true, true),
        r: () => current && decide(current.fact, false, true),
        "/": () => searchRef.current?.focus(),
      }
      const run = keys[e.key]
      if (run) {
        e.preventDefault()
        run()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  useEffect(() => {
    document.querySelector('[data-selected="true"]')?.scrollIntoView({ block: "nearest" })
  }, [index, filter])

  const peeked = peekOpen && tab === "facts" ? current : null

  return (
    <div className="flex h-full">
      <div className="@container min-w-0 flex-1 overflow-y-auto px-4 md:px-12">
        <div className="mx-auto max-w-[1060px] pt-9 pb-28">
          <Header source={source} />
          <Pipeline source={source} />
          <Activity sourceId={source.id} />

          <div role="tablist" className="mt-6 flex gap-5 border-b">
            <TabButton active={tab === "facts"} onClick={() => setTab("facts")} count={source.facts.length}>
              Facts
            </TabButton>
            <TabButton
              active={tab === "assessment"}
              onClick={() => setTab("assessment")}
              count={source.arguments.length}
            >
              Assessment
            </TabButton>
          </div>

          {tab === "facts" ? (
            <>
              <Toolbar
                source={source}
                filter={filter}
                onFilter={(f) => {
                  setFilter(f)
                  setSel(0)
                }}
                query={query}
                onQuery={(v) => {
                  setQuery(v)
                  setSel(0)
                }}
                searchRef={searchRef}
              />
              {source.facts.length > 0 && (
                <div role="row" className={cn(FACT_GRID, "h-8 border-y text-[12.5px] text-muted-foreground")}>
                  <span />
                  <span>Fact</span>
                  <span className="hidden @3xl:block">Quotes</span>
                  <span className="hidden @3xl:block">Search query</span>
                  <span className="hidden @md:block">Impact</span>
                  <span>Status</span>
                </div>
              )}
              <div role="rowgroup">
                {rows.map(({ fact }, i) => (
                  <FactRow
                    key={fact.id}
                    fact={fact}
                    selected={i === index}
                    onOpen={() => {
                      setSel(i)
                      setPeekOpen(true)
                    }}
                    onToggle={(accepted) => decide(fact, accepted, false)}
                  />
                ))}
              </div>
              {rows.length === 0 && <EmptyRows source={source} filter={filter} searching={!!q} />}
              {rows.length > 0 && (
                <p className="mt-3.5 flex flex-wrap gap-x-3.5 gap-y-1.5 text-[12.5px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Kbd>J</Kbd>
                    <Kbd>K</Kbd> move
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Kbd>↵</Kbd> open
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Kbd>A</Kbd> accept
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Kbd>R</Kbd> reject
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Kbd>/</Kbd> filter
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Kbd>Esc</Kbd> close
                  </span>
                </p>
              )}
            </>
          ) : (
            <Assessment source={source} onOpenFact={openFact} />
          )}
        </div>
      </div>

      {peeked && (
        <FactPeek
          key={peeked.fact.id}
          fact={peeked.fact}
          n={peeked.n}
          total={source.facts.length}
          onClose={() => setPeekOpen(false)}
          onStep={move}
          onDecide={(accepted) => decide(peeked.fact, accepted, true)}
          onQuery={(value) => patch.mutate({ id: peeked.fact.id, body: { query: value } })}
        />
      )}
    </div>
  )
}

function Header({ source }: { source: SourceDetail }) {
  const id = source.identifier
  const name = id.startsWith("http") ? id : id.split("/").pop()
  return (
    <header>
      <h1 className="text-[30px] leading-[1.2] font-bold tracking-[-0.015em] text-balance break-words">
        {source.title}
      </h1>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px] text-muted-foreground">
        {source.type && <span>{humanize(source.type)}</span>}
        {source.language && <Dot>{source.language}</Dot>}
        <Dot>
          {source.doi ? (
            <a
              href={`https://doi.org/${source.doi}`}
              target="_blank"
              rel="noreferrer"
              className="underline decoration-border underline-offset-2 hover:text-foreground hover:decoration-foreground"
            >
              doi:{source.doi}
            </a>
          ) : (
            <span className="break-all">{name}</span>
          )}
        </Dot>
        <Dot>{source.chars.toLocaleString("en")} characters</Dot>
      </div>
      {source.doi && <SignalsRow source={source} />}
      {source.head && (
        <div className="mt-2">
          <Toggle title="Source text">
            <p className="max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
              {source.head}
              {source.chars > source.head.length && "…"}
            </p>
          </Toggle>
        </div>
      )}
    </header>
  )
}

/** OpenAlex metrics as quiet tags. Context for reach, never a fact or evidence. */
function SignalsRow({ source }: { source: SourceDetail }) {
  const qc = useQueryClient()
  const refresh = useMutation({
    mutationFn: () => api.refreshSignals(source.id),
    onSuccess: ({ signals }) =>
      qc.setQueryData<SourceDetail>(["source", source.id], (old) => old && { ...old, signals }),
    onError: (e) => toast.error(e.message),
  })
  const s = source.signals
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="mr-1 text-xs text-muted-foreground">Signals</span>
        </TooltipTrigger>
        <TooltipContent>From OpenAlex: context for reach and the search — not evidence of impact. A pinned lead is checked first during corroboration.</TooltipContent>
      </Tooltip>
      {s ? (
        <>
          {s.cited_by != null && <Tag>{s.cited_by} citing works</Tag>}
          {s.field && <Tag>{s.field}</Tag>}
          {s.reach && s.reach.countries.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Tag color="blue">
                    Cited from {s.reach.countries.length} {s.reach.countries.length === 1 ? "country" : "countries"}
                  </Tag>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                Reach — countries of the citing works:{" "}
                {s.reach.countries.slice(0, 12).map((c) => `${c.name} ${c.works}`).join(", ")}
                {s.reach.countries.length > 12 && "…"}
              </TooltipContent>
            </Tooltip>
          )}
          {s.reach && s.reach.fields.length > 1 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Tag color="blue">Cited in {s.reach.fields.length} fields</Tag>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                {s.reach.fields.map((f) => `${f.name} ${f.works}`).join(", ")}
              </TooltipContent>
            </Tooltip>
          )}
          {(s.pinned ?? []).map((p) => (
            <a key={p.url} href={p.url} target="_blank" rel="noreferrer" title={p.snippet}>
              <Tag color="green">Lead: {p.title.slice(0, 50)}</Tag>
            </a>
          ))}
          {!s.reach && (
            <Button variant="ghost" size="xs" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
              {refresh.isPending && <Loader2 className="animate-spin" />}
              Fetch reach
            </Button>
          )}
        </>
      ) : (
        <Button variant="ghost" size="xs" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          {refresh.isPending && <Loader2 className="animate-spin" />}
          Fetch from OpenAlex
        </Button>
      )}
    </div>
  )
}

function Dot({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-muted-foreground/50">·</span>
      {children}
    </span>
  )
}

function Pipeline({ source }: { source: SourceDetail }) {
  const { busy, run } = useRunner()
  // re-extracting replaces the current facts (and the human's ticks) — ask once
  const [confirming, setConfirming] = useState(false)
  const hasAccepted = source.facts.some((f) => f.status === "accepted")
  const nextIdx = STEPS.findIndex((s) => !s.done(source))
  const next = STEPS[nextIdx === -1 ? STEPS.length - 1 : nextIdx]

  const start = (phase: Phase) => {
    if (phase === "extract" && source.facts.length > 0 && !confirming) {
      setConfirming(true)
      setTimeout(() => setConfirming(false), 4000)
      return
    }
    setConfirming(false)
    run(source.id, phase)
  }

  return (
    <nav aria-label="Pipeline" className="mt-5 flex flex-wrap items-center gap-x-0.5 gap-y-1.5 border-y py-2">
      {STEPS.map((step, i) => {
        const done = step.done(source)
        const running = busy?.sourceId === source.id && busy.phase === step.phase
        const blocked = step.phase !== "extract" && !hasAccepted
        const disabled = busy !== null || blocked
        return (
          <div key={step.phase} className="flex items-center">
            {i > 0 && <ArrowRight className="mx-0.5 size-3.5 text-muted-foreground/40" />}
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={disabled ? 0 : -1}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => start(step.phase)}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors hover:bg-muted disabled:pointer-events-none",
                      !done && !running && "text-muted-foreground",
                      i === nextIdx && "bg-muted text-foreground",
                      confirming && step.phase === "extract" && "bg-tag-red text-tag-red-foreground",
                    )}
                  >
                    <span
                      className={cn(
                        "grid size-[18px] place-items-center rounded-full border text-[10.5px] tabular-nums",
                        done && !running && "border-foreground bg-foreground text-background",
                        i === nextIdx && "border-foreground",
                      )}
                    >
                      {running ? (
                        <Loader2 className="size-3 animate-spin" />
                      ) : done ? (
                        <Check className="size-2.5" strokeWidth={3.5} />
                      ) : (
                        i + 1
                      )}
                    </span>
                    {step.phase === "extract" && confirming
                      ? `Replace ${source.facts.length} facts?`
                      : step.label}
                  </button>
                </span>
              </TooltipTrigger>
              <TooltipContent>{blocked ? "Accept at least one fact first" : step.hint}</TooltipContent>
            </Tooltip>
          </div>
        )
      })}
      <Button
        size="sm"
        className="ml-auto"
        disabled={busy !== null || (next.phase !== "extract" && !hasAccepted)}
        onClick={() => start(next.phase)}
      >
        {busy?.sourceId === source.id ? <Loader2 className="animate-spin" /> : <Play className="size-3" />}
        {nextIdx === -1 ? "Re-assess" : next.label}
      </Button>
    </nav>
  )
}

function Activity({ sourceId }: { sourceId: number }) {
  const { log } = useRunner()
  if (!log || log.sourceId !== sourceId || log.lines.length === 0) return null
  return (
    <div className="mt-3">
      <Toggle title={`Activity · ${log.lines.length}`} defaultOpen>
        <ul className="max-h-40 space-y-1 overflow-y-auto text-sm text-muted-foreground">
          {log.lines.map((line, i) => (
            <li key={i} className="break-words">
              {line}
            </li>
          ))}
        </ul>
      </Toggle>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  count,
  children,
}: {
  active: boolean
  onClick: () => void
  count: number
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "-mb-px inline-flex gap-1.5 border-b-2 border-transparent px-0.5 pt-2 pb-2.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
        active && "border-foreground font-medium text-foreground",
      )}
    >
      {children}
      <span className="font-normal text-muted-foreground tabular-nums">{count}</span>
    </button>
  )
}

function Toolbar({
  source,
  filter,
  onFilter,
  query,
  onQuery,
  searchRef,
}: {
  source: SourceDetail
  filter: Filter
  onFilter: (f: Filter) => void
  query: string
  onQuery: (v: string) => void
  searchRef: React.RefObject<HTMLInputElement | null>
}) {
  const qc = useQueryClient()
  const acceptAll = useMutation({
    mutationFn: () => api.acceptAll(source.id),
    onSuccess: (data) => {
      qc.setQueryData(["source", source.id], data)
      void qc.invalidateQueries({ queryKey: ["sources"] })
    },
    onError: (e) => toast.error(e.message),
  })
  const toReview = source.facts.filter((f) => f.status === "candidate").length

  return (
    <div className="flex flex-wrap items-center justify-between gap-2.5 py-3">
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const on = filter === f.key
          return (
            <button
              key={f.key}
              type="button"
              aria-pressed={on}
              onClick={() => onFilter(f.key)}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[13px] text-foreground/80 transition-colors hover:bg-muted",
                on && "border-foreground bg-foreground text-background hover:bg-foreground",
              )}
            >
              {f.label}
              <span className={cn("tabular-nums", on ? "text-background/65" : "text-muted-foreground")}>
                {source.facts.filter(f.test).length}
              </span>
            </button>
          )
        })}
      </div>
      <div className="flex items-center gap-1">
        {toReview > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            disabled={acceptAll.isPending}
            onClick={() => acceptAll.mutate()}
          >
            Accept all {toReview}
          </Button>
        )}
        <label className="flex h-[30px] items-center gap-1.5 rounded-md border px-2 text-muted-foreground focus-within:border-ring">
          <Search className="size-3.5" />
          <input
            ref={searchRef}
            id="fact-filter"
            type="search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Filter facts and quotes"
            aria-label="Filter facts and quotes"
            className="w-40 bg-transparent text-[13.5px] text-foreground outline-none placeholder:text-muted-foreground/70"
          />
        </label>
        <Button variant="ghost" size="icon-sm" className="text-muted-foreground" asChild>
          <a href={api.csvUrl(source.id)} download aria-label="Export facts as CSV" title="Export facts as CSV">
            <Download />
          </a>
        </Button>
      </div>
    </div>
  )
}

function EmptyRows({ source, filter, searching }: { source: SourceDetail; filter: Filter; searching: boolean }) {
  if (source.facts.length === 0)
    return (
      <EmptyNote>
        No facts yet. <span className="text-foreground">Extract facts</span> reads the source and
        keeps only statements it can quote word for word.
      </EmptyNote>
    )
  if (searching) return <EmptyNote>No facts match the filter.</EmptyNote>
  if (filter === "review") {
    const accepted = source.facts.filter((f) => f.status === "accepted").length
    const rejected = source.facts.filter((f) => f.status === "rejected").length
    return (
      <EmptyNote>
        Nothing left to review — {accepted} accepted, {rejected} rejected.
      </EmptyNote>
    )
  }
  return <EmptyNote>No facts here.</EmptyNote>
}

function Assessment({ source, onOpenFact }: { source: SourceDetail; onOpenFact: (id: number) => void }) {
  if (source.arguments.length === 0)
    return (
      <EmptyNote>
        No arguments yet. Accept the facts you trust, then run{" "}
        <span className="text-foreground">Assess</span> — it argues for, against and names the
        gaps under Criterion III.
      </EmptyNote>
    )
  return (
    <div className="pt-2">
      {SIDES.map(({ side, label, color }) => {
        const items = source.arguments.filter((a) => a.side === side)
        if (items.length === 0) return null
        return (
          <section key={side} className="mt-5">
            <h2 className="mb-1 flex items-center gap-2 text-sm">
              <Tag color={color}>{label}</Tag>
              <span className="text-muted-foreground tabular-nums">{items.length}</span>
            </h2>
            {items.map((a) => (
              <ArgumentRow key={a.id} argument={a} source={source} onOpenFact={onOpenFact} />
            ))}
          </section>
        )
      })}
    </div>
  )
}

function ArgumentRow({
  argument,
  source,
  onOpenFact,
}: {
  argument: Argument
  source: SourceDetail
  onOpenFact: (id: number) => void
}) {
  const qc = useQueryClient()
  const decide = useMutation({
    mutationFn: (accepted: boolean) => api.patchArgument(argument.id, { accepted }),
    onMutate: (accepted) =>
      qc.setQueryData<SourceDetail>(["source", source.id], (s) =>
        s && {
          ...s,
          arguments: s.arguments.map((a) =>
            a.id === argument.id ? { ...a, status: accepted ? "accepted" : "rejected" } : a,
          ),
        },
      ),
    onError: (e) => {
      toast.error(e.message)
      void qc.invalidateQueries({ queryKey: ["source", source.id] })
    },
  })
  const sphere = useMutation({
    mutationFn: (value: string) => api.patchArgument(argument.id, { sphere: value }),
    onMutate: (value) =>
      qc.setQueryData<SourceDetail>(["source", source.id], (s) =>
        s && {
          ...s,
          arguments: s.arguments.map((a) =>
            a.id === argument.id ? { ...a, sphere: (value || null) as Sphere | null } : a,
          ),
        },
      ),
    onError: (e) => {
      toast.error(e.message)
      void qc.invalidateQueries({ queryKey: ["source", source.id] })
    },
  })
  // the API names an argument's facts by statement; map them back to rows to open
  const facts = argument.facts
    .map((statement) => {
      const i = source.facts.findIndex((f) => f.statement === statement)
      return i === -1 ? null : { id: source.facts[i].id, n: i + 1, statement }
    })
    .filter((f) => f !== null)

  return (
    <div className="grid grid-cols-[22px_minmax(0,1fr)] gap-x-3.5 border-b px-2 py-2.5">
      <Checkbox
        checked={argument.status === "accepted"}
        onCheckedChange={(v) => decide.mutate(v === true)}
        className="mt-[3px]"
        aria-label="Accept argument"
      />
      <div className="min-w-0">
        <p
          className={cn(
            "leading-normal",
            argument.status === "rejected" && "text-muted-foreground line-through decoration-muted-foreground/40",
          )}
        >
          {argument.statement}
        </p>
        {/* native select: the model proposes a sphere, the human corrects it */}
        <select
          value={argument.sphere ?? ""}
          onChange={(e) => sphere.mutate(e.target.value)}
          aria-label="Sphere of impact"
          className={cn(
            "mt-1 -ml-1 rounded-sm bg-transparent px-1 py-0.5 text-[12.5px] transition-colors hover:bg-muted",
            argument.sphere ? "text-foreground/80" : "text-muted-foreground",
          )}
        >
          <option value="">No sphere</option>
          {Object.entries(SPHERES).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        {facts.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {facts.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => onOpenFact(f.id)}
                className="inline-flex max-w-full items-center gap-1.5 rounded-[4px] bg-muted px-2 py-px text-left text-[12.5px] text-foreground/80 transition-colors hover:bg-accent hover:text-foreground"
              >
                <CornerDownRight className="size-3 shrink-0 text-muted-foreground" />
                <span className="font-mono text-[11.5px] text-muted-foreground">#{f.n}</span>
                <span className="truncate">{f.statement}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-[13px] text-muted-foreground">Rests on no fact — a gap in the evidence.</p>
        )}
      </div>
    </div>
  )
}

/** "JournalArticle" → "Journal article" */
function humanize(s: string) {
  const words = s.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
