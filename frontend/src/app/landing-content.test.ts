import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
const layoutSource = readFileSync(new URL("./layout.tsx", import.meta.url), "utf8");
const heroSource = readFileSync(
  new URL("../components/otclick/landing/hero-mock.tsx", import.meta.url),
  "utf8",
);

const landingSource = `${pageSource}\n${layoutSource}\n${heroSource}`;

describe("public landing content", () => {
  it("does not expose pricing or SaaS sales copy", () => {
    const forbidden = [
      "₸",
      "KZT",
      "hh.kz",
      "Тарифы",
      "тариф",
      "Триал",
      "триал",
      "без карты",
      "PLANS",
      "PlanCard",
      "pricing",
      "популярный",
      "Killer feature",
      "ни у кого из конкурентов нет",
      "1000+",
      "Попробовать бесплатно",
      "Начать бесплатно",
    ];

    for (const value of forbidden) {
      expect(landingSource).not.toContain(value);
    }
  });

  it("keeps the landing focused on the actual workflow", () => {
    expect(pageSource).toContain("Войти");
    expect(pageSource).toContain("AI-скоринг 0–100");
    expect(pageSource).toContain("Контролируемая очередь отправки");
    expect(pageSource).toContain("Отправка выключена по умолчанию");
    expect(layoutSource).toContain("ассистент для поиска вакансий на hh.ru");
  });
});
