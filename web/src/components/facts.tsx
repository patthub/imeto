import { useLayoutEffect, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Check, ChevronDown, ChevronUp, Globe, Quote, Search, X } from "lucide-react"
import { toast } from "sonner"

import { Kbd, Pill, Tag, type TagColor } from "@/components/blocks"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { api, type Fact, type FactStatus, type Impact, type SourceDetail } from "@/lib/api"
import { cn } from "@/lib/utils"

export const FACT_STATUS: Record<FactStatus, { label: string; color: TagColor }> = {
  candidate: { label: "To review", color: "yellow" },
  accepted: { label: "Accepted", color: "green" },
  rejected: { label: "Rejected", color: "red" },
}

const TRAIL: Record<Fact["trail"], string> = {
  unknown: "Not assessed",
  internal: "Likely internal to science",
  candidate: "Worth searching",
}

// columns drop out as the table narrows (the peek panel takes room): impact below
// @md, quotes and query below @3xl
export const FACT_GRID =
  "grid grid-cols-[22px_minmax(0,1fr)_96px] items-center gap-x-3.5 px-2 @md:grid-cols-[22px_minmax(0,1fr)_52px_104px] @3xl:grid-cols-[22px_minmax(0,1fr)_48px_minmax(0,0.65fr)_48px_104px]"

type ClaimPatch = { accepted?: boolean; query?: string }

/** Optimistic gate/query edits; dashboard and sidebar counts refresh once settled. */
export function useClaimPatch(sourceId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ClaimPatch }) => api.patchClaim(id, body),
    onMutate: ({ id, body }) =>
      qc.setQueryData<SourceDetail>(["source", sourceId], (s) =>
        s && {
          ...s,
          facts: s.facts.map((f) =>
            f.id !== id
              ? f
              : {
                  ...f,
                  ...(body.accepted !== undefined && {
                    status: body.accepted ? ("accepted" as const) : ("rejected" as const),
                  }),
                  ...(body.query !== undefined && { query: body.query.trim() }),
                },
          ),
        },
      ),
    onError: (e) => {
      toast.error(e.message)
      void qc.invalidateQueries({ queryKey: ["source", sourceId] })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  })
}

export function FactRow({
  fact,
  selected,
  onOpen,
  onToggle,
}: {
  fact: Fact
  selected: boolean
  onOpen: () => void
  onToggle: (accepted: boolean) => void
}) {
  const rejected = fact.status === "rejected"
  const cited = fact.impact.some((e) => e.channel === "citation")
  const ImpactIcon = cited ? BookOpen : Globe
  return (
    <div
      role="row"
      data-selected={selected}
      onClick={onOpen}
      className={cn(
        FACT_GRID,
        "min-h-11 cursor-pointer border-b py-2.5 transition-colors hover:bg-muted/50",
        selected && "bg-selection shadow-[inset_2px_0_0_var(--selection-line)] hover:bg-selection",
      )}
    >
      <Checkbox
        checked={fact.status === "accepted"}
        onClick={(e) => e.stopPropagation()}
        onCheckedChange={(v) => onToggle(v === true)}
        aria-label={fact.status === "accepted" ? "Reject fact" : "Accept fact"}
      />
      <div className="flex min-w-0 items-baseline gap-2">
        <span
          className={cn(
            "line-clamp-2 leading-[1.45]",
            rejected && "text-muted-foreground line-through decoration-muted-foreground/40",
          )}
        >
          {fact.statement}
        </span>
        {fact.kind !== "direct" && <Tag>{fact.kind}</Tag>}
      </div>
      <span
        className="hidden items-center gap-1.5 text-[13px] text-muted-foreground tabular-nums @3xl:inline-flex"
        title="Verbatim quotes"
      >
        <Quote className="size-3" />
        {fact.grounds.length}
      </span>
      <span className="hidden min-w-0 items-start gap-1.5 text-[13.5px] @3xl:flex">
        {fact.query ? (
          <>
            <Search className="mt-[4px] size-3 shrink-0 text-muted-foreground" />
            <span className="line-clamp-2 leading-[1.45]" title={fact.query}>
              {fact.query}
            </span>
          </>
        ) : (
          <span className="text-muted-foreground/50">
            {fact.trail === "internal" ? "internal" : "—"}
          </span>
        )}
      </span>
      <span className="hidden items-center gap-1.5 text-[13px] tabular-nums @md:inline-flex">
        {fact.impact.length ? (
          <>
            <ImpactIcon className="size-3.5 text-muted-foreground" />
            {fact.impact.length}
          </>
        ) : (
          <span className="text-muted-foreground/50">—</span>
        )}
      </span>
      <span>
        <Pill color={FACT_STATUS[fact.status].color}>{FACT_STATUS[fact.status].label}</Pill>
      </span>
    </div>
  )
}

/** Notion's side peek: the whole fact, its grounds in context, query and evidence. */
export function FactPeek({
  fact,
  n,
  total,
  onClose,
  onStep,
  onDecide,
  onQuery,
}: {
  fact: Fact
  n: number
  total: number
  onClose: () => void
  onStep: (delta: number) => void
  onDecide: (accepted: boolean) => void
  onQuery: (query: string) => void
}) {
  return (
    <aside
      aria-label={`Fact ${n}`}
      className="fixed inset-y-0 right-0 z-30 w-[min(430px,100vw)] overflow-y-auto bg-background shadow-2xl min-[1280px]:static min-[1280px]:z-auto min-[1280px]:w-[430px] min-[1280px]:shrink-0 min-[1280px]:border-l min-[1280px]:shadow-none"
    >
      <div className="sticky top-0 z-10 flex h-11 items-center justify-between bg-background pr-2.5 pl-5 text-[13px] text-muted-foreground">
        <span className="tabular-nums">
          Fact {n} of {total}
        </span>
        <div className="flex">
          <Button variant="ghost" size="icon-sm" onClick={() => onStep(-1)} aria-label="Previous fact">
            <ChevronUp />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => onStep(1)} aria-label="Next fact">
            <ChevronDown />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close">
            <X />
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-3.5 px-7 pt-1.5 pb-16">
        <div className="flex gap-1.5">
          <DecideButton
            active={fact.status === "accepted"}
            activeClass="bg-tag-green text-tag-green-foreground"
            onClick={() => onDecide(true)}
          >
            <Check className="size-3.5" />
            Accept <Kbd>A</Kbd>
          </DecideButton>
          <DecideButton
            active={fact.status === "rejected"}
            activeClass="bg-tag-red text-tag-red-foreground"
            onClick={() => onDecide(false)}
          >
            <X className="size-3.5" />
            Reject <Kbd>R</Kbd>
          </DecideButton>
        </div>

        <p className="mt-1 text-[19px] leading-[1.45] font-medium text-pretty">{fact.statement}</p>

        <dl className="grid grid-cols-[84px_minmax(0,1fr)] items-center gap-y-1.5 text-[13.5px]">
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <Pill color={FACT_STATUS[fact.status].color}>{FACT_STATUS[fact.status].label}</Pill>
          </dd>
          <dt className="text-muted-foreground">Kind</dt>
          <dd>
            <Tag color={fact.kind === "direct" ? "gray" : "yellow"}>{fact.kind}</Tag>
          </dd>
          <dt className="text-muted-foreground">Trail</dt>
          <dd>{TRAIL[fact.trail]}</dd>
        </dl>

        <PeekHeading count={fact.grounds.length}>Verbatim grounds</PeekHeading>
        {fact.grounds.map((g) => (
          <figure key={`${g.start}-${g.end}`}>
            <blockquote className="border-l-[3px] border-foreground/75 pl-3.5 text-[14.5px] leading-relaxed">
              <span className="text-muted-foreground">{g.before}</span>{" "}
              <mark className="rounded-[2px] bg-highlight px-px text-foreground">{g.quote}</mark>{" "}
              <span className="text-muted-foreground">{g.after}</span>
            </blockquote>
            <figcaption className="mt-1 pl-[17px] font-mono text-[11.5px] text-muted-foreground/70">
              chars {g.start.toLocaleString("en")}–{g.end.toLocaleString("en")}
            </figcaption>
          </figure>
        ))}

        <PeekHeading>Search query</PeekHeading>
        <QueryField value={fact.query} onSave={onQuery} />

        <PeekHeading count={fact.impact.length}>Impact</PeekHeading>
        {fact.impact.length ? (
          fact.impact.map((ev, i) => <ImpactCallout key={i} ev={ev} />)
        ) : (
          <p className="text-[13.5px] text-muted-foreground">
            {fact.trail === "internal"
              ? "Not corroborated — the model expects no trace outside science."
              : "Not corroborated yet."}
          </p>
        )}
      </div>
    </aside>
  )
}

function DecideButton({
  active,
  activeClass,
  onClick,
  children,
}: {
  active: boolean
  activeClass: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-[34px] flex-1 items-center justify-center gap-1.5 rounded-md border text-sm transition-colors hover:bg-muted",
        active && cn("border-transparent hover:bg-current/0", activeClass),
      )}
    >
      {children}
    </button>
  )
}

function PeekHeading({ count, children }: { count?: number; children: React.ReactNode }) {
  return (
    <h3 className="-mb-1 mt-3 flex gap-1.5 text-[12.5px] font-medium text-muted-foreground">
      {children}
      {count !== undefined && <span className="font-normal tabular-nums">{count}</span>}
    </h3>
  )
}

/** Saves on blur / Enter. While focused it shows the draft, so a refetch arriving
 *  mid-run (corroboration refreshes the page) cannot wipe what the human types. */
function QueryField({ value, onSave }: { value: string; onSave: (q: string) => void }) {
  const [draft, setDraft] = useState(value)
  const [editing, setEditing] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const shown = editing ? draft : value
  // grow to fit the whole query (CSS field-sizing isn't in Safari/Firefox yet)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${el.scrollHeight}px`
  }, [shown])
  return (
    <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-muted-foreground focus-within:border-ring">
      <Search className="mt-[5px] size-3.5 shrink-0" />
      {/* grows with the query: a search query is read whole before it is sent */}
      <textarea
        ref={ref}
        rows={1}
        value={shown}
        onFocus={() => {
          setDraft(value)
          setEditing(true)
        }}
        onChange={(e) => setDraft(e.target.value.replace(/\n/g, " "))}
        onBlur={() => {
          setEditing(false)
          if (draft.trim() !== value) onSave(draft)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            e.currentTarget.blur()
          }
        }}
        placeholder="Empty — searches by the fact itself"
        aria-label="Search query"
        className="min-h-6 min-w-0 flex-1 resize-none overflow-hidden bg-transparent text-[15px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/60"
      />
    </label>
  )
}

function ImpactCallout({ ev }: { ev: Impact }) {
  const cited = ev.channel === "citation"
  const Icon = cited ? BookOpen : Globe
  let host = ev.url
  try {
    host = new URL(ev.url).hostname.replace(/^www\./, "")
  } catch {
    // not a URL — show the identifier as is
  }
  return (
    <div className="flex gap-2.5 rounded-md bg-muted px-3.5 py-3 text-sm">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">
          {cited ? "A work citing this study" : "Found by web search"}
        </p>
        <p className="mt-0.5 mb-1 leading-relaxed">{ev.quote}</p>
        <a
          href={ev.url}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-xs text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"
        >
          {host}
        </a>
      </div>
    </div>
  )
}
