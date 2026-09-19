"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const ITEMS = [
  { href: "/vacancies", label: "Вакансии", exact: true },
  { href: "/vacancies/sources", label: "Источники" },
  { href: "/vacancies/run", label: "Запуск" },
  { href: "/vacancies/stats", label: "Статистика" },
  { href: "/vacancies/profile", label: "Профиль" },
  { href: "/vacancies/rules", label: "Правила", exact: true },
  { href: "/vacancies/rules/manage", label: "Управление" },
  { href: "/vacancies/bulk", label: "Пакет" },
  { href: "/vacancies/send", label: "Отправка" },
];

export default function VacanciesLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <nav
        aria-label="Раздел вакансий"
        style={{ display: "flex", gap: 6, marginBottom: 12, overflowX: "auto" }}
      >
        {ITEMS.map((item) => {
          const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className="oc-seg__item"
              aria-current={active ? "page" : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </>
  );
}
