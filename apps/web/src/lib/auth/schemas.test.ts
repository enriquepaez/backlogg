import { describe, expect, it } from "vitest";

import { loginSchema, registerSchema } from "./schemas";

describe("registerSchema", () => {
  it("accepts a valid payload, trimming the optional display name", () => {
    const result = registerSchema.safeParse({
      username: "valid_user-1",
      email: "user@example.com",
      password: "longenough1",
      displayName: "  Jane  ",
    });

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.displayName).toBe("Jane");
    }
  });

  it("accepts an empty display name (treated as 'not provided' by the form)", () => {
    const result = registerSchema.safeParse({
      username: "valid_user-1",
      email: "user@example.com",
      password: "longenough1",
      displayName: "",
    });
    expect(result.success).toBe(true);
  });

  it.each([
    ["ab", "too short"],
    ["a".repeat(51), "too long"],
    ["invalid username", "spaces not allowed"],
    ["invalid!", "symbols not allowed"],
  ])("rejects username %p (%s)", (username) => {
    const result = registerSchema.safeParse({
      username,
      email: "user@example.com",
      password: "longenough1",
    });
    expect(result.success).toBe(false);
  });

  it("rejects a malformed email", () => {
    const result = registerSchema.safeParse({
      username: "valid_user",
      email: "not-an-email",
      password: "longenough1",
    });
    expect(result.success).toBe(false);
  });

  it("rejects a password under 8 characters", () => {
    const result = registerSchema.safeParse({
      username: "valid_user",
      email: "user@example.com",
      password: "short1",
    });
    expect(result.success).toBe(false);
  });
});

describe("loginSchema", () => {
  it("accepts non-empty credentials", () => {
    expect(loginSchema.safeParse({ username: "someuser", password: "x" }).success).toBe(true);
  });

  it("rejects empty username or password", () => {
    expect(loginSchema.safeParse({ username: "", password: "x" }).success).toBe(false);
    expect(loginSchema.safeParse({ username: "someuser", password: "" }).success).toBe(false);
  });
});
