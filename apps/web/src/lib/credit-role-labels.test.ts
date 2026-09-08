import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import { CREDIT_ROLE_CODES, HERO_ROLES, creditRoleLabels } from "./credit-role-labels";

/** Echoes the key back — same fake-translator convention as `game-type-labels.test.ts`. */
const t = (key: string) => key;

describe("creditRoleLabels", () => {
  it("maps every known role to its ItemDetail.credits.roles.<CODE> key", () => {
    const labels = creditRoleLabels(t);

    for (const code of CREDIT_ROLE_CODES) {
      expect(labels[code]).toBe(`credits.roles.${code}`);
    }
  });

  it("covers exactly the vocabulary the Credits section can render — cast, screenplay, authorship", () => {
    // `docs/schema.md`, "Supported roles by domain" + the `ACTOR` entries
    // merged in from `item_cast` (feature 89), minus the roles the hero
    // already shows.
    expect([...CREDIT_ROLE_CODES].sort()).toEqual(
      ["ACTOR", "AUTHOR", "SOURCE_AUTHOR", "WRITER"].sort(),
    );
  });

  // Per the user's FE-65 decision: director/creator live in the hero `dl`,
  // so they never reach this section and carrying copy for them would be
  // dead vocabulary. The two lists must stay disjoint — a code in both would
  // mean the page filters out something the section still claims to label.
  it("has no label for the roles the hero owns (DIRECTOR/CREATOR)", () => {
    const labels = creditRoleLabels(t);

    expect([...HERO_ROLES].sort()).toEqual(["CREATOR", "DIRECTOR"]);
    for (const role of HERO_ROLES) {
      expect(labels[role]).toBeUndefined();
      expect(CREDIT_ROLE_CODES).not.toContain(role);
    }
  });

  it("gives SOURCE_AUTHOR and WRITER two different keys, never one shared label", () => {
    const labels = creditRoleLabels(t);

    expect(labels.SOURCE_AUTHOR).not.toBe(labels.WRITER);
  });

  it("has no entry for unknown vocabulary, so callers fall back to the raw role", () => {
    const labels = creditRoleLabels(t);

    expect(labels.COMPOSER).toBeUndefined();
    // Case-sensitive, like `gameTypeLabel`: the backend sends upper-case codes.
    expect(labels.writer).toBeUndefined();
  });

  // FE-65 acceptance: "no hardcoded strings — next-intl message keys in
  // es.json and en.json". Read straight from the message files so a code
  // added to `CREDIT_ROLE_CODES` without its copy (or added to only one
  // locale) fails here instead of silently rendering the key path.
  it.each(["en", "es"] as const)("has %s copy for every role code", (locale) => {
    const roles: Record<string, string> = (locale === "en" ? en : es).ItemDetail.credits.roles;

    for (const code of CREDIT_ROLE_CODES) {
      expect(roles[code], `missing ${locale} copy for ${code}`).toBeTruthy();
    }
    expect(Object.keys(roles).sort()).toEqual([...CREDIT_ROLE_CODES].sort());
  });

  it.each(["en", "es"] as const)(
    "%s: SOURCE_AUTHOR and WRITER read as two different things (source work vs. screenplay)",
    (locale) => {
      const roles = (locale === "en" ? en : es).ItemDetail.credits.roles;

      expect(roles.SOURCE_AUTHOR).not.toBe(roles.WRITER);
      expect(roles.SOURCE_AUTHOR).not.toBe(roles.AUTHOR);
    },
  );

  // Pinned copy, per the user's FE-65 decision. `WRITER` is plain
  // "Guion"/"Screenplay", not "guion de la adaptación": TMDB emits
  // `Screenplay`/`Writer` on original (non-adapted) films too, where the
  // longer wording would simply be false. The whole "source work vs.
  // screenplay" distinction rests on `SOURCE_AUTHOR`'s label instead.
  it("spells WRITER as plain screenplay and SOURCE_AUTHOR as authorship of the original work", () => {
    expect(en.ItemDetail.credits.roles.WRITER).toBe("Screenplay");
    expect(es.ItemDetail.credits.roles.WRITER).toBe("Guion");
    expect(en.ItemDetail.credits.roles.SOURCE_AUTHOR).toBe("Author of the original work");
    expect(es.ItemDetail.credits.roles.SOURCE_AUTHOR).toBe("Autoría de la obra original");
  });
});
