"use client";

import { ChevronDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Link } from "@/i18n/navigation";

type NavMenuLink = {
  href: string;
  label: string;
};

/**
 * Grouped dropdown for a handful of primary-nav destinations behind one
 * trigger (FE-55 "navbar decluttering": "Explore" groups Trending/Genres,
 * "Activity" groups Feed/For you). `SiteHeader` stays a Server Component
 * (it needs `getCurrentUser()` directly in render, see its own doc comment)
 * — this is the thin Client Component boundary that lets these two menus
 * open/close without turning the whole header into a Client Component.
 *
 * Styled to read as a plain nav link (text + chevron, no button chrome) so
 * it sits visually alongside the standalone `Search`/`Library` links rather
 * than looking like a distinct control.
 */
export function NavMenu({ label, links }: { label: string; links: NavMenuLink[] }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        type="button"
        className="inline-flex items-center gap-1 rounded-md outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {label}
        <ChevronDown aria-hidden="true" className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {links.map((link) => (
          <DropdownMenuItem key={link.href} asChild>
            <Link href={link.href}>{link.label}</Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
