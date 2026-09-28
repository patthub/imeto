import { createContext, useContext, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { api, runPhase, type ModelSettings, type Phase } from "@/lib/api"

type Log = { sourceId: number; lines: string[] }
type Runner = {
  busy: { sourceId: number; phase: Phase } | null
  status: string
  log: Log | null
  model: ModelSettings
  setModel: (m: ModelSettings) => void
  run: (sourceId: number, phase: Phase) => void
  stop: () => void
}

const RunnerContext = createContext<Runner | null>(null)
const MODEL_KEY = "imeto.model"

function readModel(): Partial<ModelSettings> {
  try {
    return JSON.parse(localStorage.getItem(MODEL_KEY) ?? "{}") as Partial<ModelSettings>
  } catch {
    return {}
  }
}

/** One long operation at a time (the backend has one stop flag): its status line,
 *  its activity log, and the model it runs on. */
export function RunnerProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config })
  const [stored, setStored] = useState(readModel)
  const [busy, setBusy] = useState<Runner["busy"]>(null)
  const [status, setStatus] = useState("")
  const [log, setLog] = useState<Log | null>(null)

  const model = {
    base_url: stored.base_url || config?.base_url || "",
    model: stored.model || config?.model || "",
  }

  const setModel = (m: ModelSettings) => {
    setStored(m)
    try {
      localStorage.setItem(MODEL_KEY, JSON.stringify(m))
    } catch {
      // storage blocked: the setting still holds for this session
    }
  }

  const run = (sourceId: number, phase: Phase) => {
    if (busy) return
    const refresh = () => qc.invalidateQueries({ queryKey: ["source", sourceId] })
    let last = ""
    setBusy({ sourceId, phase })
    setStatus("Starting")
    setLog({ sourceId, lines: [] })
    runPhase(sourceId, phase, model, (e) => {
      if (e.status) setStatus(e.status)
      const line = e.log
      if (line) {
        last = line
        setLog((l) => ({ sourceId, lines: [...(l?.lines ?? []), line] }))
        void refresh() // a confirmation lands on its fact as soon as it is found
      }
      if (e.error) {
        last = ""
        toast.error(e.error)
      }
    })
      .then(() => last && toast(last))
      .catch((err: unknown) => toast.error(err instanceof Error ? err.message : String(err)))
      .finally(() => {
        setBusy(null)
        setStatus("")
        void refresh()
        void qc.invalidateQueries({ queryKey: ["sources"] }) // dashboard + sidebar counts
      })
  }

  const stop = () => {
    setStatus("Stopping after the current step")
    void api.stop()
  }

  return (
    <RunnerContext value={{ busy, status, log, model, setModel, run, stop }}>
      {children}
    </RunnerContext>
  )
}

export function useRunner(): Runner {
  const ctx = useContext(RunnerContext)
  if (!ctx) throw new Error("useRunner outside RunnerProvider")
  return ctx
}
