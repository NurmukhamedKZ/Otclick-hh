import { describe, expect, it } from "vitest";
import { deterministicFields } from "../lib/deterministic-fill";

const FACTS = {
  full_name: "Иван Петров",
  email: "ivan@example.com",
  phone: "+7 777 111 22 33",
  city: "Алматы",
};

const els = [
  { ref: "f1", selector: "#email", field_type: "text", label: "Ваш e-mail" },
  { ref: "f2", selector: "#name", field_type: "text", label: "Фамилия и имя" },
  { ref: "f3", selector: "#why", field_type: "textarea", label: "Почему вы?" },
  { ref: "f4", selector: "#cv", field_type: "file", label: "Резюме" },
];

describe("deterministicFields", () => {
  it("fills email and name, leaves open questions to the LLM", () => {
    const out = deterministicFields(els, FACTS);
    const byRef = Object.fromEntries(out.map((f) => [f.ref, f]));
    expect(byRef.f1.value).toBe("ivan@example.com");
    expect(byRef.f2.value).toBe("Иван Петров");
    expect(byRef.f3).toBeUndefined();
    expect(byRef.f1.source).toBe("profile");
  });

  it("attaches the resume file only when one is available", () => {
    expect(deterministicFields(els, FACTS).find((f) => f.ref === "f4")).toBeUndefined();
    const withCv = deterministicFields(els, FACTS, { url: "http://x/cv", filename: "cv.pdf" });
    expect(withCv.find((f) => f.ref === "f4")?.filename).toBe("cv.pdf");
  });

  it("returns nothing without facts", () => {
    expect(deterministicFields(els, {})).toEqual([]);
  });

  it("does not treat 'Ваш город' as a name field", () => {
    const out = deterministicFields(
      [{ ref: "c", selector: "#c", field_type: "text", label: "Ваш город" }],
      FACTS,
    );
    expect(out[0].value).toBe("Алматы");
  });
});
