import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "Otclick — ассистент для поиска вакансий на hh.ru",
  description:
    "Self-hosted инструмент для сбора и оценки вакансий hh.ru, ручного review и подготовки индивидуальных сопроводительных писем.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Otclick — ассистент для поиска вакансий на hh.ru",
    description:
      "Сбор вакансий, фильтрация, AI-скоринг, review и подготовка сопроводительных в одном рабочем процессе.",
    type: "website",
    locale: "ru_RU",
  },
  twitter: {
    card: "summary_large_image",
    title: "Otclick — ассистент для поиска вакансий на hh.ru",
    description:
      "Сбор вакансий, фильтрация, AI-скоринг, review и подготовка сопроводительных в одном рабочем процессе.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className="antialiased">
      <body>{children}</body>
    </html>
  );
}
