import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "Otclick — поиск работы на hh.ru: отклики, ответы рекрутёрам, ведение задач",
  description:
    "Otclick откликается на вакансии hh.ru и hh.kz, отвечает рекрутёрам с подтверждением, генерирует сопроводительные письма нейросетью и ведёт ваши задачи до оффера.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Otclick — доводим до оффера на hh.ru и hh.kz",
    description:
      "Отклики, AI-ответы рекрутёрам, ведение задач и созвонов. Ты приходишь только на собеседование.",
    type: "website",
    locale: "ru_RU",
  },
  twitter: {
    card: "summary_large_image",
    title: "Otclick — доводим до оффера на hh.ru и hh.kz",
    description:
      "Отклики, AI-ответы рекрутёрам, ведение задач и созвонов. Ты приходишь только на собеседование.",
  },
};

const JSON_LD = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      name: "Otclick",
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      description:
        "AI-ассистент для поиска работы на hh.ru и hh.kz: отклики, ответы рекрутёрам, сопроводительные письма, ведение задач до оффера.",
      offers: { "@type": "Offer", price: "0", priceCurrency: "KZT", category: "free" },
      featureList: [
        "Авто-отклики на hh.ru и hh.kz",
        "AI-ответы рекрутёрам с подтверждением",
        "Генератор сопроводительных писем нейросетью",
        "Ведение задач от рекрутёра (формы, созвоны) до оффера",
      ],
    },
    {
      "@type": "FAQPage",
      mainEntity: [
        {
          "@type": "Question",
          name: "Как Otclick работает после закрытия публичного API hh.ru?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Используем headless-браузер с OTP-авторизацией и защищённой серверной сессией. Без публичного API соискателя — это законно для пользователя и устойчиво к анти-фроду hh.",
          },
        },
        {
          "@type": "Question",
          name: "Чем Otclick отличается от ботов «200 откликов в день»?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Мы не про массовый спам. Otclick откликается с персональными сопроводительными, отвечает рекрутёрам с вашим подтверждением и ведёт задачи до оффера — формы, созвоны, тесты.",
          },
        },
        {
          "@type": "Question",
          name: "Безопасно ли подключать аккаунт hh?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Токены и cookies шифруются Fernet, доступа из UI нет, ключи только у сервера. Скорость и паузы между откликами — человеческие.",
          },
        },
        {
          "@type": "Question",
          name: "Можно ли сгенерировать сопроводительное письмо бесплатно?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Да. Первые письма доступны без оплаты — вставляешь ссылку на вакансию hh и резюме, нейросеть пишет сопроводительное под конкретную вакансию.",
          },
        },
      ],
    },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className="antialiased">
      <body>
        {children}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
        />
      </body>
    </html>
  );
}
