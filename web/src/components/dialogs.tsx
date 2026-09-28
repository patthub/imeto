import { useState } from "react"
import { useNavigate } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Monitor, Moon, Sun, Upload } from "lucide-react"
import { useTheme } from "next-themes"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api } from "@/lib/api"
import { useRunner } from "@/lib/runner"
import { cn } from "@/lib/utils"

type Mode = "File" | "DOI" | "URL"
type OpenProps = { open: boolean; onOpenChange: (open: boolean) => void }

export function NewSourceDialog({ open, onOpenChange }: OpenProps) {
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config })
  const [mode, setMode] = useState<Mode>("File")
  const [file, setFile] = useState<File | null>(null)
  const [doi, setDoi] = useState("")
  const [url, setUrl] = useState("")
  const [workType, setWorkType] = useState("report")
  const [fullText, setFullText] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const add = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.set("mode", mode)
      form.set("work_type", workType)
      form.set("doi", doi)
      form.set("url", url)
      form.set("full_text", String(fullText))
      if (mode === "File" && file) form.set("file", file)
      return api.addSource(form)
    },
    onSuccess: ({ id }) => {
      void qc.invalidateQueries({ queryKey: ["sources"] })
      onOpenChange(false)
      setFile(null)
      setDoi("")
      setUrl("")
      navigate(`/sources/${id}`)
    },
    onError: (e) => toast.error(e.message),
  })

  const ready = mode === "File" ? file !== null : mode === "DOI" ? doi.trim() : url.trim()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New source</DialogTitle>
          <DialogDescription>
            Nothing is extracted yet — you look at the source first.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate()
          }}
        >
          <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
            <TabsList>
              <TabsTrigger value="File">File</TabsTrigger>
              <TabsTrigger value="DOI">DOI</TabsTrigger>
              <TabsTrigger value="URL">URL</TabsTrigger>
            </TabsList>
            <TabsContent value="File" className="pt-2">
              <FileDrop file={file} onFile={setFile} />
            </TabsContent>
            <TabsContent value="DOI" className="space-y-3 pt-2">
              <Input
                placeholder="10.1234/…"
                value={doi}
                onChange={(e) => setDoi(e.target.value)}
              />
              <Label className="font-normal">
                <Checkbox checked={fullText} onCheckedChange={(v) => setFullText(v === true)} />
                Fetch the open-access full text when there is one
              </Label>
            </TabsContent>
            <TabsContent value="URL" className="pt-2">
              <Input
                type="url"
                placeholder="https://…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </TabsContent>
          </Tabs>

          {mode !== "DOI" && (
            <div className="space-y-2">
              <Label htmlFor="work-type">Work type</Label>
              <Select value={workType} onValueChange={setWorkType}>
                <SelectTrigger id="work-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(config?.work_types ?? ["report"]).map((w) => (
                    <SelectItem key={w} value={w}>
                      {w.charAt(0).toUpperCase() + w.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter>
            <Button type="submit" disabled={!ready || add.isPending}>
              {add.isPending && <Loader2 className="animate-spin" />}
              Add source
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function FileDrop({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const [over, setOver] = useState(false)
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        onFile(e.dataTransfer.files[0] ?? null)
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed px-4 py-8 text-center text-sm transition-colors hover:bg-muted/60",
        over && "border-foreground/40 bg-muted",
      )}
    >
      <Upload className="mb-1 size-5 text-muted-foreground" />
      {file ? (
        <span className="max-w-full truncate font-medium">{file.name}</span>
      ) : (
        <>
          <span>Drop a PDF or DOCX</span>
          <span className="text-xs text-muted-foreground">or click to choose one</span>
        </>
      )}
      <input
        type="file"
        accept=".pdf,.docx"
        className="sr-only"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
    </label>
  )
}

const THEMES = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const

export function SettingsDialog({ open, onOpenChange }: OpenProps) {
  const { model, setModel } = useRunner()
  const { theme, setTheme } = useTheme()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Any OpenAI-compatible server. Kept in this browser.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault()
            const form = new FormData(e.currentTarget)
            setModel({
              base_url: String(form.get("base_url") ?? "").trim(),
              model: String(form.get("model") ?? "").trim(),
            })
            onOpenChange(false)
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="base_url">Server</Label>
            <Input id="base_url" name="base_url" defaultValue={model.base_url} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model">Model</Label>
            <Input id="model" name="model" defaultValue={model.model} placeholder="id from /v1/models" />
          </div>
          <div className="space-y-2">
            <Label>Appearance</Label>
            <div className="grid grid-cols-3 gap-1 rounded-md bg-muted p-1">
              {THEMES.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTheme(value)}
                  className={cn(
                    "flex items-center justify-center gap-1.5 rounded-[4px] py-1 text-sm text-muted-foreground transition-colors hover:text-foreground",
                    theme === value && "bg-background text-foreground",
                  )}
                >
                  <Icon className="size-3.5" />
                  {label}
                </button>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
