import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ItemCredits, type ItemCredit } from "./item-credits";

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
    render(<ItemCredits credits={[]} heading="Cast & crew" emptyMessage="No cast" />);

    expect(screen.getByRole("heading", { level: 2, name: "Cast & crew" })).toBeInTheDocument();
  });

  it("renders the empty message when there are no credits", () => {
    render(<ItemCredits credits={[]} heading="Cast & crew" emptyMessage="No cast" />);

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
      />,
    );

    expect(screen.getByText("No cast")).toBeInTheDocument();
  });

  it("renders each credit's person name and character name", () => {
    render(<ItemCredits credits={[chalamet]} heading="Cast & crew" emptyMessage="No cast" />);

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
      />,
    );

    expect(screen.getByText("Supergiant Games")).toBeInTheDocument();
    expect(screen.getByText("developer")).toBeInTheDocument();
  });

  it("renders a book's AUTHOR credit the same way (no character name, falls back to the role)", () => {
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
      />,
    );

    expect(screen.getByText("Frank Herbert")).toBeInTheDocument();
    expect(screen.getByText("AUTHOR")).toBeInTheDocument();
  });
});
