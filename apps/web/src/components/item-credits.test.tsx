import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ItemCredits, type ItemCredit } from "./item-credits";

/**
 * What the page passes as `roleLabels` (`creditRoleLabels(t)` in
 * `@/lib/credit-role-labels`, resolved against `messages/en.json`'s
 * `ItemDetail.credits.roles`). Hardcoded here rather than imported so these
 * tests pin the *rendered* label, not just the lookup key.
 */
const roleLabels = {
  ACTOR: "Cast",
  WRITER: "Screenplay",
  AUTHOR: "Author",
  SOURCE_AUTHOR: "Author of the original work",
};

/** A crew credit as it arrives since backend feature 89: no character, no billing order. */
function crewCredit(person_name: string, role: string): ItemCredit {
  return {
    person_name,
    person_slug: person_name.toLowerCase().replaceAll(" ", "-"),
    profile_url: null,
    role,
    character_name: null,
    billing_order: null,
  };
}

const chalamet: ItemCredit = {
  person_name: "Timothée Chalamet",
  person_slug: "timothee-chalamet",
  profile_url: "https://image.tmdb.org/t/p/w185/tc.jpg",
  role: "cast",
  character_name: "Paul Atreides",
  billing_order: 0,
};

describe("ItemCredits", () => {
  it("renders the heading", () => {
    render(
      <ItemCredits credits={[]} heading="Cast & crew" emptyMessage="No cast" roleLabels={roleLabels} />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "Cast & crew" })).toBeInTheDocument();
  });

  // The page no longer mounts this component with an empty list (see
  // `page.test.tsx`), but the component keeps its own empty state: it is the
  // degraded path for malformed data (below), and a future caller may not
  // pre-check.
  it("renders the empty message when there are no credits", () => {
    render(
      <ItemCredits credits={[]} heading="Cast & crew" emptyMessage="No cast" roleLabels={roleLabels} />,
    );

    expect(screen.getByText("No cast")).toBeInTheDocument();
  });

  it("renders the empty message instead of crashing when credits is undefined (malformed/degraded data)", () => {
    // `ItemCreditsProps` types `credits` as always an array, but a real
    // backend response has been observed reaching this component with
    // `credits: undefined` (bugfix — see `progress/history.md`). The `as`
    // cast simulates that malformed input past the type system, the same
    // way it would arrive at runtime.
    render(
      <ItemCredits
        credits={undefined as unknown as ItemCredit[]}
        heading="Cast & crew"
        emptyMessage="No cast"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("No cast")).toBeInTheDocument();
  });

  it("renders each credit's person name and character name", () => {
    render(
      <ItemCredits
        credits={[chalamet]}
        heading="Cast & crew"
        emptyMessage="No cast"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Timothée Chalamet")).toBeInTheDocument();
    expect(screen.getByText("Paul Atreides")).toBeInTheDocument();
    expect(screen.queryByText("No cast")).not.toBeInTheDocument();
  });

  it("falls back to the role when there is no character name (e.g. a game's developer credit)", () => {
    render(
      <ItemCredits
        credits={[
          {
            person_name: "Supergiant Games",
            person_slug: "supergiant-games",
            profile_url: null,
            role: "developer",
            character_name: null,
            billing_order: 0,
          },
        ]}
        heading="Cast & crew"
        emptyMessage="No cast"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Supergiant Games")).toBeInTheDocument();
    expect(screen.getByText("developer")).toBeInTheDocument();
  });

  it("renders a book's AUTHOR credit the same way (no character name, shows the role label)", () => {
    render(
      <ItemCredits
        credits={[
          {
            person_name: "Frank Herbert",
            person_slug: "frank-herbert",
            profile_url: null,
            role: "AUTHOR",
            character_name: null,
            billing_order: null,
          },
        ]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Frank Herbert")).toBeInTheDocument();
    expect(screen.getByText("Author")).toBeInTheDocument();
    expect(screen.queryByText("AUTHOR")).not.toBeInTheDocument();
  });

  // FE-65: with backend feature 74 live, adapted movies/series carry both
  // `SOURCE_AUTHOR` (author of the source work — Stephen King on *It*) and
  // `WRITER` (screenwriter of the adaptation — Fukunaga on the same film).
  // Merging them under one label would destroy the exact distinction that
  // feature exists to create (`docs/schema.md`, "`SOURCE_AUTHOR` vs `WRITER`").
  // `WRITER` reads as plain "Screenplay" (user's decision): TMDB emits it on
  // original films too, so "screenplay of the adaptation" would be false
  // there. The distinction is carried by `SOURCE_AUTHOR`'s label.
  it("labels SOURCE_AUTHOR and WRITER with distinct translated labels, never merged under one", () => {
    render(
      <ItemCredits
        credits={[crewCredit("Stephen King", "SOURCE_AUTHOR"), crewCredit("Cary Fukunaga", "WRITER")]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Author of the original work")).toBeInTheDocument();
    expect(screen.getByText("Screenplay")).toBeInTheDocument();
    // Distinct: neither label is used for both people, and neither raw
    // backend code leaks into the page.
    expect(screen.getAllByText("Author of the original work")).toHaveLength(1);
    expect(screen.getAllByText("Screenplay")).toHaveLength(1);
    expect(screen.queryByText("SOURCE_AUTHOR")).not.toBeInTheDocument();
    expect(screen.queryByText("WRITER")).not.toBeInTheDocument();
    // The source author's label must not read as screenwriting.
    expect(screen.getByText("Stephen King").parentElement).toHaveTextContent(
      "Author of the original work",
    );
    expect(screen.getByText("Cary Fukunaga").parentElement).toHaveTextContent("Screenplay");
  });

  // The page filters `DIRECTOR`/`CREATOR` out before this component sees
  // them (they're in the hero `dl`), so there is no copy for them any more.
  // If one ever slipped through, it must degrade to the raw code rather than
  // vanish — same policy as any other unknown vocabulary.
  it("has no label for DIRECTOR/CREATOR and falls back to the raw code if one ever reaches it", () => {
    render(
      <ItemCredits
        credits={[crewCredit("Denis Villeneuve", "DIRECTOR"), crewCredit("Vince Gilligan", "CREATOR")]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.queryByText("Director")).not.toBeInTheDocument();
    expect(screen.queryByText("Creator")).not.toBeInTheDocument();
    expect(screen.getByText("DIRECTOR")).toBeInTheDocument();
    expect(screen.getByText("CREATOR")).toBeInTheDocument();
  });

  it("falls back to the raw role for vocabulary the label map doesn't know (a role the backend adds later)", () => {
    render(
      <ItemCredits
        credits={[crewCredit("Hans Zimmer", "COMPOSER")]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Hans Zimmer")).toBeInTheDocument();
    expect(screen.getByText("COMPOSER")).toBeInTheDocument();
  });

  it("still shows the character, not the role label, for a cast credit that has one", () => {
    render(
      <ItemCredits
        credits={[chalamet]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(screen.getByText("Paul Atreides")).toBeInTheDocument();
    expect(screen.queryByText("Cast")).not.toBeInTheDocument();
  });

  it("renders no list and no orphan content for an item with neither SOURCE_AUTHOR nor WRITER and no credits at all", () => {
    const { container } = render(
      <ItemCredits
        credits={[]}
        heading="Credits"
        emptyMessage="No credits"
        roleLabels={roleLabels}
      />,
    );

    expect(container.querySelector("ul")).toBeNull();
    expect(screen.getByText("No credits")).toBeInTheDocument();
    for (const label of Object.values(roleLabels)) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});
