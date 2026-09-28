// Notion's building blocks, the few this app needs: tags, status pills, toggles, keys.

import type { ReactNode } from "react"
import { ChevronRight } from "lucide-react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

const TAG = {
  gray: "bg-tag-gray text-tag-gray-foreground",
  green: "bg-tag-green text-tag-green-foreground",
  red: "bg-tag-red text-tag-red-foreground",
  yellow: "bg-tag-yellow text-tag-yellow-foreground",
  blue: "bg-tag-blue text-tag-blue-foreground",
} as const

export type TagColor = keyof typeof TAG

export function Tag({
  color = "gray",
  className,
  children,
}: {
  color?: TagColor
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[3px] px-1.5 text-xs leading-5 whitespace-nowrap",
        TAG[color],
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Notion's status property: a rounded pill with a dot. */
export function Pill({ color, children }: { color: TagColor; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full py-px pr-2 pl-[7px] text-[12.5px] leading-5 whitespace-nowrap",
        TAG[color],
      )}
    >
      <span className="size-1.5 rounded-full bg-current opacity-75" />
      {children}
    </span>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-[4px] border border-b-2 px-1 font-mono text-[10.5px] leading-4 font-medium text-muted-foreground">
      {children}
    </kbd>
  )
}

export function Toggle({
  title,
  defaultOpen = false,
  children,
}: {
  title: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger className="group/toggle -ml-1 flex items-center gap-1 rounded-sm px-1 py-0.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
        <ChevronRight className="size-4 transition-transform group-data-[state=open]/toggle:rotate-90" />
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-1.5 pl-6">{children}</CollapsibleContent>
    </Collapsible>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="px-2 py-8 text-sm leading-relaxed text-muted-foreground">{children}</p>
}
