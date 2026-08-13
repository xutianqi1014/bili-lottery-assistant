import { describe, expect, it } from "vitest";

import { escapeHtml } from "./formatters";

describe("escapeHtml", () => {
  it("escapes user-visible text before inserting it into the console", () => {
    expect(escapeHtml(`<script>alert('x')</script>`)).toBe(
      "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;"
    );
  });
});

