import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import { RELATED_WORK_DIRECTIONS, relatedWorkDirectionLabels } from "./related-work-labels";

/**
 * Echoes the key back, appending the interpolation values — same
 * fake-translator convention as `credit-role-labels.test.ts`, extended to
 * show *what* was interpolated, since both of these messages name the item
 * on the page.
 */
const t = (key: string, values?: Record<string, string>) =>
  values ? `${key}:${JSON.stringify(values)}` : key;

describe("relatedWorkDirectionLabels", () => {
  it("maps each direction to its ItemDetail.relatedWorks.directions.<CODE> key", () => {
    const labels = relatedWorkDirectionLabels(t, "Better Call Saul");

    for (const direction of RELATED_WORK_DIRECTIONS) {
      expect(labels[direction]).toContain(`relatedWorks.directions.${direction}`);
    }
  });

  it("covers exactly the two directions the endpoint can return, no more", () => {
    // `AdaptationDirection` in `packages/api-client/src/schema.d.ts`: two
    // values, because `item_relations` stores no mirror edge and the backend
    // resolves the side for you (`docs/api.md`).
    expect([...RELATED_WORK_DIRECTIONS].sort()).toEqual(["DERIVED", "SOURCE"]);
  });

  it("interpolates the title of the item on the page into both directions", () => {
    const labels = relatedWorkDirectionLabels(t, "Better Call Saul");

    expect(labels.SOURCE).toContain('{"title":"Better Call Saul"}');
    expect(labels.DERIVED).toContain('{"title":"Better Call Saul"}');
  });

  it("gives the two directions two different keys, never one shared label", () => {
    const labels = relatedWorkDirectionLabels(t, "Dune");

    expect(labels.SOURCE).not.toBe(labels.DERIVED);
  });

  // FE-66 acceptance: "sin strings hardcodeados: claves next-intl en es.json
  // y en.json". Read straight from the message files, so a direction added
  // to `RELATED_WORK_DIRECTIONS` without its copy — or added to only one
  // locale — fails here instead of silently rendering the key path.
  it.each(["en", "es"] as const)("has %s copy for every direction", (locale) => {
    const directions: Record<string, string> = (locale === "en" ? en : es).ItemDetail
      .relatedWorks.directions;

    for (const direction of RELATED_WORK_DIRECTIONS) {
      expect(directions[direction], `missing ${locale} copy for ${direction}`).toBeTruthy();
    }
    expect(Object.keys(directions).sort()).toEqual([...RELATED_WORK_DIRECTIONS].sort());
  });

  it.each(["en", "es"] as const)(
    "%s: both directions interpolate {title} and read as two different statements",
    (locale) => {
      const messages = (locale === "en" ? en : es).ItemDetail.relatedWorks;

      expect(messages.directions.SOURCE).not.toBe(messages.directions.DERIVED);
      expect(messages.directions.SOURCE).toContain("{title}");
      expect(messages.directions.DERIVED).toContain("{title}");
    },
  );

  // Pinned copy, per the user's FE-66 decision: the section is titled
  // neutrally ("Obras relacionadas" / "Related works"), **not**
  // "Adaptaciones"/"Adaptations". 16 of the 18 edges in the catalog are
  // `SERIES`→`SERIES` (a prequel and a spin-off under *Better Call Saul*,
  // neither of them an adaptation), so a heading promising adaptations would
  // be wrong about most of what it lists.
  it("titles the section neutrally, never as 'adaptations'", () => {
    expect(en.ItemDetail.relatedWorks.heading).toBe("Related works");
    expect(es.ItemDetail.relatedWorks.heading).toBe("Obras relacionadas");
    expect(en.ItemDetail.relatedWorks.heading.toLowerCase()).not.toContain("adaptation");
    expect(es.ItemDetail.relatedWorks.heading.toLowerCase()).not.toContain("adaptaci");
  });

  it("spells SOURCE as 'the page's item comes from this one' and DERIVED as the opposite", () => {
    expect(en.ItemDetail.relatedWorks.directions.SOURCE).toBe("{title} is based on this work");
    expect(en.ItemDetail.relatedWorks.directions.DERIVED).toBe("Derived from {title}");
    expect(es.ItemDetail.relatedWorks.directions.SOURCE).toBe("{title} se basa en esta obra");
    expect(es.ItemDetail.relatedWorks.directions.DERIVED).toBe("Obra derivada de {title}");
  });
});
