import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CatalogCard } from "./catalog-card";

describe("CatalogCard", () => {
  it("renders the poster image with the title as alt text", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl="https://image.tmdb.org/t/p/w500/dune.jpg"
        ratingExternal={7.8}
      />,
    );

    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("renders the rating rounded to one decimal", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl="https://image.tmdb.org/t/p/w500/dune.jpg"
        ratingExternal={7.756}
      />,
    );

    expect(screen.getByText("7.8")).toBeInTheDocument();
  });

  it("omits the rating badge when rating_external is null", () => {
    render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.queryByText(/\d\.\d/)).not.toBeInTheDocument();
  });

  it("falls back to a placeholder (no <img>, but still an accessible role=img) when poster_url is null", () => {
    const { container } = render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("shows the type badge when provided", () => {
    render(
      <CatalogCard
        title="Chernobyl"
        posterUrl={null}
        ratingExternal={null}
        typeLabel="Series"
      />,
    );

    expect(screen.getByText("Series")).toBeInTheDocument();
  });

  it("renders the title text visibly", () => {
    render(
      <CatalogCard title="Hades" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.getByText("Hades")).toBeInTheDocument();
  });
});
