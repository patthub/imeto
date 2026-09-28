// Where a source stands in the pipeline — one reading shared by the dashboard, the
// sidebar and the source page, so they never disagree.

import type { TagColor } from "@/components/blocks"
import type { SourceDetail, SourceItem } from "@/lib/api"

export type Counts = Pick<
  SourceItem,
  "facts" | "candidate" | "accepted" | "queries" | "impact" | "arguments"
>

export function countsOf(s: SourceDetail): Counts {
  return {
    facts: s.facts.length,
    candidate: s.facts.filter((f) => f.status === "candidate").length,
    accepted: s.facts.filter((f) => f.status === "accepted").length,
    queries: s.facts.filter((f) => f.query).length,
    impact: s.facts.filter((f) => f.impact.length > 0).length,
    arguments: s.arguments.length,
  }
}

export type Stage = "new" | "extracted" | "queries" | "corroborated" | "assessed"

export const STAGE: Record<Stage, { label: string; color: TagColor; dot: string }> = {
  new: { label: "Not started", color: "gray", dot: "bg-muted-foreground/40" },
  extracted: { label: "Facts extracted", color: "yellow", dot: "bg-attention" },
  queries: { label: "Queries ready", color: "blue", dot: "bg-selection-line" },
  corroborated: { label: "Corroborated", color: "blue", dot: "bg-selection-line" },
  assessed: { label: "Assessed", color: "green", dot: "bg-tag-green-foreground" },
}

export const stageOf = (c: Counts): Stage =>
  c.arguments
    ? "assessed"
    : c.impact
      ? "corroborated"
      : c.queries
        ? "queries"
        : c.facts
          ? "extracted"
          : "new"

/** What the operator should do next; `attention` = a human is the bottleneck. */
export function nextStep(c: Counts): { label: string; attention?: boolean; done?: boolean } {
  if (!c.facts) return { label: "Extract facts" }
  if (c.candidate) return { label: `Review ${c.candidate} fact${c.candidate > 1 ? "s" : ""}`, attention: true }
  if (!c.accepted) return { label: "Accept facts", attention: true }
  if (!c.queries) return { label: "Propose queries" }
  if (!c.impact) return { label: "Corroborate" }
  if (!c.arguments) return { label: "Assess" }
  return { label: "Complete", done: true }
}
