import { Link } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, FileText, Plus } from "lucide-react"

import { Pill } from "@/components/blocks"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, type SourceItem } from "@/lib/api"
import { nextStep, STAGE, stageOf } from "@/lib/progress"
import { cn } from "@/lib/utils"

const ROW =
  "grid grid-cols-[minmax(250px,1fr)_150px_150px_70px_190px] items-center gap-x-4 px-2"

/** The dashboard: what is in the library and where a human is needed next. */
export function Home({ onNew }: { onNew: () => void }) {
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources })

  if (sources === undefined)
    return (
      <div className="mx-auto max-w-[1060px] space-y-4 px-4 pt-12 md:px-12">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (sources.length === 0) return <Welcome onNew={onNew} />

  const sum = (key: keyof SourceItem) => sources.reduce((n, s) => n + Number(s[key]), 0)
  const review = sum("candidate")

  return (
    <div className="h-full overflow-y-auto px-4 md:px-12">
      <div className="mx-auto max-w-[1060px] pt-9 pb-28">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] leading-tight font-bold tracking-[-0.015em]">Sources</h1>
            <p className="mt-1.5 max-w-[60ch] text-muted-foreground">
              Every fact here quotes its source word for word. Start where something is
              waiting for you.
            </p>
          </div>
          <Button onClick={onNew}>
            <Plus />
            New source
          </Button>
        </header>

        <dl className="my-7 flex flex-wrap gap-x-10 gap-y-3 border-y py-3.5">
          <Stat label="Sources" value={sources.length} />
          <Stat label="Facts" value={sum("facts")} />
          <Stat label="Waiting for review" value={review} attention={review > 0} />
          <Stat label="Accepted" value={sum("accepted")} />
          <Stat label="Confirmed impact" value={sum("impact")} />
          <Stat label="Arguments" value={sum("arguments")} />
        </dl>

        <div className="overflow-x-auto">
          <div role="table" aria-label="Sources" className="min-w-[780px]">
            <div role="row" className={cn(ROW, "h-9 border-b text-[12.5px] text-muted-foreground")}>
              <span>Name</span>
              <span>Stage</span>
              <span>Facts accepted</span>
              <span>Impact</span>
              <span>Next step</span>
            </div>
            {sources.map((s) => (
              <SourceRow key={s.id} source={s} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function SourceRow({ source: s }: { source: SourceItem }) {
  const stage = STAGE[stageOf(s)]
  const next = nextStep(s)
  return (
    <Link
      role="row"
      to={`/sources/${s.id}`}
      className={cn(ROW, "min-h-[54px] border-b py-2 transition-colors hover:bg-muted/50")}
    >
      <span className="flex min-w-0 items-start gap-2.5">
        <FileText className="mt-[3px] size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0">
          <span className="block truncate font-medium">{s.title}</span>
          <span className="block truncate text-xs text-muted-foreground">{s.sub}</span>
        </span>
      </span>
      <span>
        <Pill color={stage.color}>{stage.label}</Pill>
      </span>
      <span className="flex items-center gap-2.5 text-[13.5px] tabular-nums">
        <span className="h-1 w-[72px] overflow-hidden rounded-full bg-border">
          <span
            className="block h-full bg-foreground/70"
            style={{ width: `${s.facts ? (100 * s.accepted) / s.facts : 0}%` }}
          />
        </span>
        {s.accepted}/{s.facts}
      </span>
      <span className={cn("tabular-nums", !s.impact && "text-muted-foreground/50")}>
        {s.impact || "—"}
      </span>
      <span
        className={cn(
          "inline-flex items-center gap-1.5 text-[13.5px] text-foreground/80",
          next.attention && "font-medium text-attention",
          next.done && "text-muted-foreground",
        )}
      >
        {next.label}
        {!next.done && <ArrowRight className="size-3.5" />}
      </span>
    </Link>
  )
}

function Stat({ label, value, attention }: { label: string; value: number; attention?: boolean }) {
  return (
    <div>
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-px text-2xl font-semibold tracking-[-0.01em] tabular-nums",
          attention && "text-attention",
        )}
      >
        {value.toLocaleString("en")}
      </dd>
    </div>
  )
}

function Welcome({ onNew }: { onNew: () => void }) {
  return (
    <div className="bg-dots flex min-h-full flex-col items-center justify-center px-6 py-16 text-center">
      <h1 className="max-w-2xl text-4xl leading-[1.1] font-bold tracking-[-0.02em] md:text-6xl">
        Facts you can trace back to the page.
      </h1>
      <p className="mt-5 max-w-md text-lg leading-relaxed text-muted-foreground">
        Bring in a report, a DOI or a link. Every fact IMeTo keeps quotes its source word
        for word — and you decide which ones stand.
      </p>
      <Button size="lg" className="mt-7 px-4" onClick={onNew}>
        New source
        <ArrowRight />
      </Button>
    </div>
  )
}
