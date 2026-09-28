import { useState } from "react"
import { Link, Route, Routes, useMatch } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, ListChecks, Loader2, Menu, MoreHorizontal, Square } from "lucide-react"
import { toast } from "sonner"

import { NewSourceDialog, SettingsDialog } from "@/components/dialogs"
import { Home } from "@/components/home"
import { LeadsPage } from "@/components/leads"
import { Sidebar } from "@/components/sidebar"
import { SourcePage } from "@/components/source-page"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api } from "@/lib/api"
import { useRunner } from "@/lib/runner"

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  const [adding, setAdding] = useState(false)
  const [settings, setSettings] = useState(false)

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        collapsed={collapsed}
        onCollapse={() => setCollapsed(true)}
        onNew={() => setAdding(true)}
        onSettings={() => setSettings(true)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <TopBar collapsed={collapsed} onExpand={() => setCollapsed(false)} />
        {/* pages scroll themselves: the source page keeps its peek panel beside the list */}
        <div className="min-h-0 flex-1">
          <Routes>
            <Route path="/sources/:id" element={<SourcePage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="*" element={<Home onNew={() => setAdding(true)} />} />
          </Routes>
        </div>
      </main>
      <NewSourceDialog open={adding} onOpenChange={setAdding} />
      <SettingsDialog open={settings} onOpenChange={setSettings} />
    </div>
  )
}

function TopBar({ collapsed, onExpand }: { collapsed: boolean; onExpand: () => void }) {
  const id = useMatch("/sources/:id")?.params.id
  const sourceId = id === undefined ? null : Number(id)
  const atInstitution = useMatch("/leads") !== null
  const { data: source } = useQuery({
    queryKey: ["source", sourceId],
    queryFn: () => api.source(sourceId as number),
    enabled: sourceId !== null,
  })
  const { busy, status, stop } = useRunner()
  const qc = useQueryClient()
  const acceptAll = useMutation({
    mutationFn: (sid: number) => api.acceptAll(sid),
    onSuccess: (data) => {
      qc.setQueryData(["source", data.id], data)
      void qc.invalidateQueries({ queryKey: ["sources"] })
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <header className="flex h-11 shrink-0 items-center gap-2 px-3">
      {collapsed && (
        <Button variant="ghost" size="icon-sm" onClick={onExpand} aria-label="Open sidebar">
          <Menu />
        </Button>
      )}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm">
        {sourceId === null ? (
          <span className="px-1">{atInstitution ? "Impact leads" : "Sources"}</span>
        ) : (
          <>
            <Link
              to="/"
              className="rounded-sm px-1 py-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              Sources
            </Link>
            <span className="text-muted-foreground/50">/</span>
            <span className="truncate px-1">{source?.title}</span>
          </>
        )}
      </nav>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        {busy && (
          <>
            <span className="flex min-w-0 items-center gap-2 px-1 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 shrink-0 animate-spin" />
              <span className="truncate">{status}</span>
            </span>
            {busy.phase !== "argue" && (
              <Button variant="ghost" size="sm" onClick={stop}>
                <Square className="fill-current" />
                Stop
              </Button>
            )}
          </>
        )}
        {source && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Page actions">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem
                disabled={source.facts.length === 0}
                onSelect={() => acceptAll.mutate(source.id)}
              >
                <ListChecks />
                Accept all facts
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a href={api.csvUrl(source.id)} download>
                  <Download />
                  Export facts as CSV
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <p className="px-2 py-1.5 text-xs text-muted-foreground">
                {source.facts.length} facts · {source.chars.toLocaleString("en")} characters
              </p>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </header>
  )
}
