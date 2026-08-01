import { describe, expect, it } from "vitest";
import { collectEdits } from "../lib/edits";

const applied = [
  { ref: "f1", value: "Иван", label: "Имя" },
  { ref: "f2", value: "3 года", label: "Опыт" },
] as never;

describe("collectEdits", () => {
  it("returns only the fields the user changed", () => {
    const out = collectEdits(applied, [
      { ref: "f1", label: "Имя", value: "Иван" },
      { ref: "f2", label: "Опыт", value: "5 лет" },
    ]);
    expect(out).toEqual([{ question: "Опыт", answer: "5 лет" }]);
  });

  it("skips cleared fields and unlabelled ones", () => {
    const out = collectEdits(applied, [
      { ref: "f1", label: "Имя", value: "" },
      { ref: "f2", label: "", value: "что-то" },
    ]);
    expect(out).toEqual([]);
  });

  it("ignores fields that were never filled by us", () => {
    expect(collectEdits(applied, [{ ref: "f9", label: "Другое", value: "x" }])).toEqual([]);
  });

  it("ignores whitespace-only differences", () => {
    expect(collectEdits(applied, [{ ref: "f1", label: "Имя", value: "  Иван  " }])).toEqual([]);
  });
});
