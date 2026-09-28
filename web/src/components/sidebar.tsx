import type { ReactNode } from "react"
import { Link, useMatch } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { Building2, ChevronsLeft, Cpu, House, PlusCircle, Settings2, type LucideIcon } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { STAGE, stageOf } from "@/lib/progress"
import { useRunner } from "@/lib/runner"
import { cn } from "@/lib/utils"

const ITEM =
  "flex min-h-[28px] w-full items-center gap-2 px-3 py-1 text-left text-sm font-medium transition-colors hover:bg-sidebar-accent"

export function Sidebar({
  collapsed,
  onCollapse,
  onNew,
  onSettings,
}: {
  collapsed: boolean
  onCollapse: () => void
  onNew: () => void
  onSettings: () => void
}) {
  const { data: sources } = useQuery({ queryKey: ["sources"], queryFn: api.sources })
  const activeId = useMatch("/sources/:id")?.params.id
  const atHome = useMatch("/") !== null
  const atInstitution = useMatch("/leads") !== null
  const { model, busy } = useRunner()

  return (
    <aside
      className={cn(
        "group/sidebar h-full shrink-0 overflow-hidden bg-sidebar text-sidebar-foreground transition-[width] duration-300 ease-in-out",
        collapsed ? "w-0" : "w-60",
      )}
    >
      <div className="flex h-full w-60 flex-col">
        <div className="flex items-center gap-2 px-3 py-3">
          <span className="grid size-5 place-items-center rounded-[4px] bg-sidebar-primary text-[11px] font-bold text-sidebar-primary-foreground">
            I
          </span>
          <span className="truncate text-sm font-medium text-sidebar-accent-foreground">IMeTo</span>
          <button
            type="button"
            onClick={onCollapse}
            aria-label="Collapse sidebar"
            className="ml-auto grid size-6 place-items-center rounded-sm text-muted-foreground opacity-0 transition hover:bg-sidebar-accent group-hover/sidebar:opacity-100 focus-visible:opacity-100"
          >
            <ChevronsLeft className="size-4" />
          </button>
        </div>

        <Link to="/" className={cn(ITEM, atHome && "bg-sidebar-accent text-sidebar-accent-foreground")}>
          <Icon icon={House} />
          Sources
        </Link>
        <Link to="/leads" className={cn(ITEM, atInstitution && "bg-sidebar-accent text-sidebar-accent-foreground")}>
          <Icon icon={Building2} />
          Impact leads
        </Link>
        <button type="button" onClick={onNew} className={ITEM}>
          <Icon icon={PlusCircle} />
          New source
        </button>
        <button type="button" onClick={onSettings} className={ITEM}>
          <Icon icon={Settings2} />
          Settings
        </button>

        <p className="mt-5 px-3 pb-1 text-xs font-medium text-muted-foreground/80">Library</p>
        <div className="min-h-0 flex-1 overflow-y-auto pb-3">
          {sources === undefined ? (
            <div className="space-y-2 px-3 py-1">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-4 w-3/5" />
            </div>
          ) : (
            sources.map((s) => (
              <Link
                key={s.id}
                to={`/sources/${s.id}`}
                title={`${s.title} — ${s.sub}`}
                className={cn(ITEM, activeId === String(s.id) && "bg-sidebar-accent text-sidebar-accent-foreground")}
              >
                <span className="grid size-[18px] shrink-0 place-items-center">
                  <span
                    className={cn(
                      "size-[7px] rounded-full",
                      STAGE[stageOf(s)].dot,
                      busy?.sourceId === s.id && "animate-pulse bg-foreground",
                    )}
                  />
                </span>
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                <span className="text-xs font-normal text-muted-foreground tabular-nums">
                  {s.accepted}/{s.facts}
                </span>
              </Link>
            ))
          )}
        </div>

        <button
          type="button"
          onClick={onSettings}
          className="flex items-center gap-2 border-t border-sidebar-border px-3 py-2.5 text-left text-xs text-muted-foreground transition-colors hover:bg-sidebar-accent"
        >
          <Cpu className="size-3.5 shrink-0" />
          <span className="truncate">{model.model || "No model set"}</span>
        </button>
      </div>
    </aside>
  )
}

function Icon({ icon: I }: { icon: LucideIcon }): ReactNode {
  return <I className="size-[18px] shrink-0 text-muted-foreground" />
}
