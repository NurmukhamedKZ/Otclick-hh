import { describe, expect, it } from "vitest";
import { buildFillPayload, mergeFrameFields, withLabels } from "../lib/api";

describe("buildFillPayload", () => {
  it("trims page text and keeps frames", () => {
    const payload = buildFillPayload({
      url: "https://docs.google.com/forms/x",
      pageText: "a".repeat(50_000),
      frames: [{ frame_id: 0, snapshot: [{ ref: "f1" }] }],
    });
    expect(payload.page_text.length).toBe(40_000);
    expect(payload.frames[0].frame_id).toBe(0);
  });
});

describe("mergeFrameFields", () => {
  it("returns only the fields of the requested frame", () => {
    const merged = mergeFrameFields(
      {
        frames: [
          { frame_id: 0, fields: [{ ref: "a" }] },
          { frame_id: 7, fields: [{ ref: "b" }] },
        ],
      } as never,
      7,
    );
    expect(merged.map((f) => f.ref)).toEqual(["b"]);
  });

  it("returns an empty list for an unknown frame", () => {
    expect(mergeFrameFields({ frames: [] }, 3)).toEqual([]);
  });
});

describe("withLabels", () => {
  it("joins snapshot labels onto the backend's fields", () => {
    const marks = withLabels(
      [{ ref: "f1", selector: "#a", source: "ai", value: "x", field_type: "text" }] as never,
      [{ ref: "f1", label: "Имя" }],
    );
    expect(marks[0]).toMatchObject({ selector: "#a", label: "Имя", source: "ai" });
  });

  it("falls back to an empty label for an unknown ref", () => {
    const marks = withLabels(
      [{ ref: "zzz", selector: "#a", source: "ai", value: "x" }] as never,
      [{ ref: "f1", label: "Имя" }],
    );
    expect(marks[0].label).toBe("");
  });
});
