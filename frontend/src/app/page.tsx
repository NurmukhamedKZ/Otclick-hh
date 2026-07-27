import Link from "next/link";
import { Btn, Card, StatusDot, Tag } from "@/components/otclick/ui";
import { IArrow, ICheck, ILogo } from "@/components/otclick/icons";
import {
  CountUp,
  Lift,
  Reveal,
  StaggerGroup,
  StaggerItem,
} from "@/components/otclick/landing/motion";
import { HeroMock } from "@/components/otclick/landing/hero-mock";
import { RecruiterChat } from "@/components/otclick/landing/recruiter-chat";

const VACANCIES = [
  { c: "var(--yellow)", t: "Senior Frontend", s: "от 250 000 ₽ · Удалёнка" },
  { c: "var(--coral)", t: "Backend Python", s: "Гибрид · Москва" },
  { c: "var(--sage)", t: "Product Manager", s: "от 280 000 ₽ · Удалёнка" },
  { c: "var(--ink)", t: "DevOps", s: "от 320 000 ₽ · Удалёнка" },
  { c: "var(--yellow)", t: "Маркетолог", s: "от 3 лет · Москва" },
  { c: "var(--coral)", t: "ML-инженер", s: "от 350 000 ₽ · Удалёнка" },
];

const PAINS = [
  { t: "200 откликов — и тишина", s: "Жмёшь «откликнуться» сотни раз, а в ответ — пустой инбокс." },
  { t: "Письма под копирку", s: "На уникальное сопроводительное под каждую вакансию нет сил." },
  { t: "Тесты и формы на каждом шагу", s: "Анкеты, опросники, тестовые — час на один отклик." },
  { t: "Рекрутёр написал — ты проспал", s: "Ответил через день — место уже занято." },
];

const STEPS = [
  { n: "01", t: "Подключи hh.ru", s: "Вход за 30 секунд через защищённую сессию. Пароль не храним." },
  { n: "02", t: "Скажи, кого ищем", s: "Резюме, зарплата, фильтры по ключам и региону — один раз." },
  { n: "03", t: "Живи свою жизнь", s: "Откликаемся, пишем письма, отвечаем рекрутёрам. Ты — на собес." },
];

const SAFETY = [
  { t: "Человеческий ритм", s: "Паузы между откликами, уникальные письма. Поведение неотличимо от ручного." },
  { t: "Ты подтверждаешь каждый шаг", s: "Отклики, ответы рекрутёрам, формы — ничего не уходит без твоего «ок»." },
  { t: "Аккаунт под защитой", s: "Доступы шифруются и видны только серверу. Никаких «1000 откликов» — это бан." },
];

const PLANS = [
  {
    name: "Бесплатно",
    price: "0 ₸",
    period: "30 откликов, без карты",
    sub: "Ручной режим: нажал «прогнать пачку» — сработало и встало.",
    cta: "Начать бесплатно",
    feats: [
      "30 откликов всего, не в день",
      "AI-сопроводительные под каждую вакансию",
      "Капчу решаете сами в интерфейсе",
      "Без карты и без ограничения по времени",
    ],
  },
  {
    name: "Спринт",
    price: "1 000 ₸",
    period: "7 дней",
    sub: "Закрыть поиск за один спринт. Низкий коммит.",
    cta: "Начать спринт",
    feats: [
      "До 100 откликов в день",
      "Работает сам, без нажатий",
      "Агент отвечает рекрутёрам и ведёт до оффера",
      "Формы, тесты, созвоны — в задачах",
    ],
  },
  {
    name: "Месяц",
    price: "3 000 ₸",
    period: "в месяц",
    sub: "Полный автопилот. Агент-ответчик уже включён.",
    cta: "Оформить",
    popular: true,
    feats: [
      "До 100 откликов в день",
      "Всё из «Спринта»",
      "Приоритетная обработка чатов",
      "Авто-продление · отмена в 1 клик",
    ],
  },
];

export default function Home() {
  return (
    <main
      style={{
        minHeight: "100vh",
        width: "100%",
        maxWidth: 1400,
        margin: "0 auto",
        padding: "20px clamp(16px, 4vw, 32px) 60px",
        position: "relative",
        zIndex: 1,
      }}
    >
      <Nav />

      {/* ============ HERO ============ */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
          gap: 48,
          alignItems: "center",
          padding: "56px 0 36px",
        }}
      >
        <div>
          <Reveal y={18}>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                background: "var(--ink)",
                color: "#F5F1E6",
                padding: "8px 16px",
                borderRadius: 999,
                fontSize: 13,
                marginBottom: 26,
              }}
            >
              <StatusDot tone="ok" />
              Доводим до оффера на hh.ru и hh.kz
            </div>
          </Reveal>

          <Reveal y={22} delay={0.05}>
            <h1
              style={{
                fontSize: "clamp(40px, 9vw, 72px)",
                lineHeight: 0.98,
                margin: 0,
                fontWeight: 700,
                letterSpacing: -3,
              }}
            >
              Поиск работы<br />
              на автопилоте.<br />
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                ты — на собеседовании
              </span>
            </h1>
          </Reveal>

          <Reveal y={18} delay={0.12}>
            <p
              style={{
                fontSize: 19,
                color: "var(--muted)",
                margin: "26px 0 0",
                maxWidth: 520,
                lineHeight: 1.55,
              }}
            >
              Откликаемся, пишем сопроводительные нейросетью, отвечаем рекрутёрам и
              ведём задачи до оффера. Твоё дело — прийти и получить работу.
            </p>
          </Reveal>

          <Reveal y={16} delay={0.18}>
            <div style={{ marginTop: 32, display: "flex", gap: 12, flexWrap: "wrap" }}>
              <Link href="/auth">
                <Btn kind="primary" size="lg" icon={<IArrow size={16} />}>
                  Попробовать бесплатно
                </Btn>
              </Link>
              <a href="#how">
                <Btn kind="ghost" size="lg">
                  Как это работает
                </Btn>
              </a>
            </div>
          </Reveal>

          <Reveal y={14} delay={0.24}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 12, marginTop: 30 }}>
              <div style={{ display: "flex" }}>
                {["#F5CB3D", "#E96B58", "#C7D4B6", "#1A1B1F"].map((c, i) => (
                  <div
                    key={i}
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 999,
                      background: c,
                      border: "2px solid var(--bg)",
                      marginLeft: i ? -10 : 0,
                    }}
                  />
                ))}
              </div>
              <div style={{ textAlign: "left", fontSize: 13 }}>
                <div style={{ fontWeight: 700 }}>★★★★★ 4.9</div>
                <div style={{ color: "var(--muted)" }}>
                  <CountUp to={1000} suffix="+" /> офферов получено
                </div>
              </div>
            </div>
          </Reveal>
        </div>

        <HeroMock />
      </section>

      {/* ============ VACANCY MARQUEE ============ */}
      <div
        className="oc-marquee"
        style={{
          overflow: "hidden",
          marginBottom: 110,
          maskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)",
          WebkitMaskImage: "linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)",
        }}
      >
        <div className="oc-marquee-track">
          {[...VACANCIES, ...VACANCIES].map((v, i) => (
            <div
              key={i}
              style={{
                flex: "0 0 auto",
                display: "flex",
                alignItems: "center",
                gap: 12,
                background: "var(--surface)",
                borderRadius: 16,
                padding: "12px 18px",
                minWidth: 240,
              }}
            >
              <div style={{ width: 36, height: 36, borderRadius: 999, background: v.c, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 700 }}>{v.t}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>{v.s}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ============ PAIN (the problem) ============ */}
      <Card tone="dark" style={{ padding: "clamp(32px, 6vw, 56px) clamp(20px, 5vw, 48px)", marginBottom: 110, overflow: "hidden" }}>
        <Reveal>
          <div style={{ textAlign: "center", maxWidth: 640, margin: "0 auto 44px" }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: "var(--yellow)",
                textTransform: "uppercase",
                letterSpacing: 1.5,
                marginBottom: 14,
              }}
            >
              Знакомо?
            </div>
            <h2 style={{ fontSize: "clamp(30px, 7vw, 48px)", fontWeight: 700, letterSpacing: -1.8, margin: 0, color: "#F5F1E6" }}>
              Поиск работы превратился{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                в работу
              </span>
            </h2>
          </div>
        </Reveal>

        <StaggerGroup
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))",
            gap: 16,
            maxWidth: 820,
            margin: "0 auto",
          }}
        >
          {PAINS.map((p) => (
            <StaggerItem key={p.t}>
              <div
                style={{
                  background: "#ffffff0a",
                  border: "1px solid #ffffff14",
                  borderRadius: 18,
                  padding: 22,
                  height: "100%",
                }}
              >
                <div style={{ fontSize: 19, fontWeight: 700, color: "#F5F1E6", marginBottom: 6 }}>
                  {p.t}
                </div>
                <div style={{ fontSize: 14, color: "#ffffff80", lineHeight: 1.5 }}>{p.s}</div>
              </div>
            </StaggerItem>
          ))}
        </StaggerGroup>

        <Reveal delay={0.1}>
          <p
            style={{
              textAlign: "center",
              fontSize: 18,
              color: "#F5F1E6",
              margin: "40px auto 0",
              maxWidth: 560,
              lineHeight: 1.5,
            }}
          >
            Otclick забирает рутину. Тебе остаётся живое общение{" "}
            <span style={{ color: "var(--yellow)" }}>— и оффер.</span>
          </p>
        </Reveal>
      </Card>

      {/* ============ PLAN — 3 steps ============ */}
      <section id="how" style={{ marginBottom: 110, scrollMarginTop: 24 }}>
        <Reveal>
          <div style={{ textAlign: "center", marginBottom: 56 }}>
            <Eyebrow>✦ Просто как раз-два-три</Eyebrow>
            <h2 style={{ fontSize: "clamp(32px, 7vw, 52px)", fontWeight: 700, letterSpacing: -2, margin: 0 }}>
              Три шага до{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                автопилота
              </span>
            </h2>
          </div>
        </Reveal>

        <StaggerGroup style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 18 }}>
          {STEPS.map((s) => (
            <StaggerItem key={s.n}>
              <Lift style={{ height: "100%" }}>
                <Card tone="light" style={{ padding: 28, minHeight: 200, height: "100%" }}>
                  <div
                    className="serif"
                    style={{ fontSize: 44, color: "var(--coral)", lineHeight: 1, marginBottom: 16 }}
                  >
                    {s.n}
                  </div>
                  <div style={{ fontSize: 21, fontWeight: 700, marginBottom: 8 }}>{s.t}</div>
                  <div style={{ fontSize: 14.5, color: "var(--muted)", lineHeight: 1.55 }}>{s.s}</div>
                </Card>
              </Lift>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      {/* ============ KILLER — recruiter agent ============ */}
      <section style={{ marginBottom: 110 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
            gap: 56,
            alignItems: "center",
          }}
        >
          <Reveal>
            <div>
              <Tag tone="coral" style={{ marginBottom: 18 }}>
                ★ наш дифференциатор
              </Tag>
              <h2 style={{ fontSize: "clamp(30px, 7vw, 46px)", fontWeight: 700, letterSpacing: -1.6, margin: 0, lineHeight: 1.05 }}>
                Агент отвечает рекрутёрам и{" "}
                <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                  доводит до оффера
                </span>
              </h2>
              <p
                style={{
                  fontSize: 17,
                  color: "var(--muted)",
                  marginTop: 18,
                  maxWidth: 460,
                  lineHeight: 1.6,
                }}
              >
                AI читает сообщения HR, готовит ответ в твоём тоне, ты подтверждаешь
                одним кликом. Тесты, формы, созвоны — всё собирается в задачи.
                Остальные сервисы бросают тебя на «отклик отправлен». Мы — ведём дальше.
              </p>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  marginTop: 22,
                  background: "var(--yellow)",
                  padding: "9px 16px",
                  borderRadius: 999,
                  fontSize: 13,
                  fontWeight: 700,
                }}
              >
                Killer feature · ни у кого из конкурентов нет
              </div>
            </div>
          </Reveal>

          <Reveal delay={0.1} y={30}>
            <RecruiterChat />
          </Reveal>
        </div>
      </section>

      {/* ============ BENTO — proof of features ============ */}
      <section style={{ marginBottom: 110 }}>
        <Reveal>
          <div style={{ textAlign: "center", marginBottom: 56 }}>
            <Eyebrow>⚡ Всё в одном месте</Eyebrow>
            <h2 style={{ fontSize: "clamp(32px, 7vw, 52px)", fontWeight: 700, letterSpacing: -2, margin: 0 }}>
              Всё для{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                результата
              </span>
            </h2>
            <p style={{ color: "var(--muted)", fontSize: 18, margin: "16px auto 0", maxWidth: 560 }}>
              Находим вакансии, пишем письма, отвечаем рекрутёрам — пока ты занят жизнью.
            </p>
          </div>
        </Reveal>

        <StaggerGroup style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 18 }}>
          <StaggerItem>
            <BentoCard title="AI-сопроводительные" sub="Под каждую вакансию hh, не шаблон. Анализ требований и подбор опыта." visual={<BentoLetter />} />
          </StaggerItem>
          <StaggerItem>
            <BentoCard title="Умная ИИ-фильтрация" sub="Подбираем вакансии под резюме, опыт и зарплатные ожидания." visual={<BentoFilter />} />
          </StaggerItem>
          <StaggerItem>
            <BentoCard title="Статистика откликов" sub="Каждый отклик, форма и тест — в реальном времени. Видно, где зависло." visual={<BentoStats />} />
          </StaggerItem>
          <StaggerItem>
            <BentoCard title="Чёрный список" sub="Авто-блок работодателей по «уже откликались» и ручной чёрный список." visual={<BentoBlacklist />} />
          </StaggerItem>
          <StaggerItem>
            <BentoCard title="Чаты с рекрутёрами" sub="AI читает сообщения HR и готовит ответы — ты подтверждаешь одним кликом." visual={<BentoChat />} />
          </StaggerItem>
          <StaggerItem>
            <BentoCTA />
          </StaggerItem>
        </StaggerGroup>
      </section>

      {/* ============ SAFETY (fear removal) ============ */}
      <section id="security" style={{ marginBottom: 110, textAlign: "center", scrollMarginTop: 24 }}>
        <Reveal>
          <Eyebrow>◆ Спокойно за аккаунт</Eyebrow>
          <h2 style={{ fontSize: "clamp(32px, 7vw, 52px)", fontWeight: 700, letterSpacing: -2, margin: 0 }}>
            Работаем как{" "}
            <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
              живой человек
            </span>
          </h2>
          <p style={{ color: "var(--muted)", fontSize: 18, margin: "16px auto 0", maxWidth: 560 }}>
            После закрытия публичного API hh массовый спам = бан. Мы — про точность и
            безопасность, а не про «1000 откликов в день».
          </p>
        </Reveal>

        <StaggerGroup
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            gap: 18,
            marginTop: 56,
            textAlign: "left",
          }}
        >
          {SAFETY.map((s) => (
            <StaggerItem key={s.t}>
              <Lift style={{ height: "100%" }}>
                <Card tone="light" style={{ padding: 28, minHeight: 200, height: "100%" }}>
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: 14,
                      background: "var(--yellow)",
                      display: "grid",
                      placeItems: "center",
                      marginBottom: 18,
                    }}
                  >
                    <ICheck size={22} />
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{s.t}</div>
                  <div style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.55 }}>{s.s}</div>
                </Card>
              </Lift>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      {/* ============ PRICING ============ */}
      <section id="pricing" style={{ marginBottom: 110, scrollMarginTop: 24 }}>
        <Reveal>
          <div style={{ textAlign: "center", marginBottom: 56 }}>
            <Eyebrow>₸ Простые тарифы</Eyebrow>
            <h2 style={{ fontSize: "clamp(32px, 7vw, 52px)", fontWeight: 700, letterSpacing: -2, margin: 0 }}>
              Плати за{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                офферы
              </span>
              , не за спам
            </h2>
            <p style={{ color: "var(--muted)", fontSize: 18, margin: "16px auto 0", maxWidth: 560 }}>
              Агент-ответчик включён в каждый платный тариф. 3 дня бесплатно или
              первые 3 письма без карты.
            </p>
          </div>
        </Reveal>

        <StaggerGroup
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
            gap: 18,
            alignItems: "stretch",
          }}
        >
          {PLANS.map((p) => (
            <StaggerItem key={p.name} style={{ height: "100%" }}>
              <PlanCard plan={p} />
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      {/* ============ FINAL CTA — success vs failure ============ */}
      <Reveal>
        <Card tone="dark" style={{ padding: "clamp(28px, 6vw, 64px)", textAlign: "center", overflow: "hidden" }}>
          <h2
            style={{
              fontSize: "clamp(32px, 7vw, 52px)",
              fontWeight: 700,
              letterSpacing: -2,
              margin: 0,
              lineHeight: 1.05,
              color: "#F5F1E6",
            }}
          >
            Перестань откликаться{" "}
            <span className="serif" style={{ fontWeight: 400, color: "var(--yellow)" }}>
              в пустоту
            </span>
          </h2>

          <div
            style={{
              display: "flex",
              gap: 14,
              justifyContent: "center",
              flexWrap: "wrap",
              margin: "32px 0",
            }}
          >
            <Contrast bad label="Сейчас" text="Недели откликов, тесты, тишина, выгорание" />
            <Contrast label="С Otclick" text="Ты приходишь только на собеседование" />
          </div>

          <div style={{ marginTop: 8 }}>
            <Link href="/auth">
              <Btn kind="yellow" size="lg" icon={<IArrow size={16} />}>
                Начать бесплатно
              </Btn>
            </Link>
          </div>
          <p style={{ color: "#ffffff80", fontSize: 15, marginTop: 18 }}>
            7 дней триала · без карты · отмена в 1 клик
          </p>
        </Card>
      </Reveal>

      <footer
        style={{
          marginTop: 32,
          paddingTop: 24,
          borderTop: "1px solid var(--line)",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 13,
          color: "var(--muted)",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <span>© {new Date().getFullYear()} otclick · hh.ru / hh.kz</span>
        <span>hello@otclick.ru</span>
      </footer>
    </main>
  );
}

/* ============ shared bits ============ */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 13,
        fontWeight: 700,
        color: "var(--coral)",
        textTransform: "uppercase",
        letterSpacing: 1.5,
        marginBottom: 14,
      }}
    >
      {children}
    </div>
  );
}

function Contrast({ label, text, bad }: { label: string; text: string; bad?: boolean }) {
  return (
    <div
      style={{
        flex: "1 1 240px",
        maxWidth: 320,
        background: bad ? "#ffffff08" : "var(--yellow)",
        border: bad ? "1px solid #ffffff1a" : "none",
        borderRadius: 18,
        padding: 22,
        textAlign: "left",
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 1,
          color: bad ? "#ffffff60" : "#00000060",
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          lineHeight: 1.4,
          color: bad ? "#ffffffb0" : "var(--ink)",
        }}
      >
        {text}
      </div>
    </div>
  );
}

/* ============ PRICING CARD ============ */
function PlanCard({
  plan,
}: {
  plan: {
    name: string;
    price: string;
    period: string;
    sub: string;
    cta: string;
    feats: string[];
    popular?: boolean;
  };
}) {
  const dark = plan.popular;
  return (
    <Lift style={{ height: "100%" }}>
      <Card
        tone={dark ? "dark" : "light"}
        style={{
          padding: 30,
          minHeight: 440,
          height: "100%",
          display: "flex",
          flexDirection: "column",
          border: dark ? "none" : "1px solid var(--line-2)",
          boxShadow: dark ? "0 30px 60px -24px rgba(26,27,31,0.4)" : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: dark ? "#F5F1E6" : "var(--ink)",
            }}
          >
            {plan.name}
          </span>
          {plan.popular && <Tag tone="yellow">★ популярный</Tag>}
        </div>

        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span
            style={{
              fontSize: 40,
              fontWeight: 800,
              letterSpacing: -1.5,
              color: dark ? "#F5F1E6" : "var(--ink)",
            }}
          >
            {plan.price}
          </span>
          <span style={{ fontSize: 14, color: dark ? "#ffffff80" : "var(--muted)" }}>
            {plan.period}
          </span>
        </div>

        <p
          style={{
            fontSize: 14,
            lineHeight: 1.5,
            margin: "12px 0 22px",
            color: dark ? "#ffffff99" : "var(--muted)",
          }}
        >
          {plan.sub}
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1 }}>
          {plan.feats.map((f) => (
            <div key={f} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 999,
                  background: dark ? "var(--yellow)" : "var(--sage-soft)",
                  color: dark ? "var(--ink)" : "var(--ok)",
                  display: "grid",
                  placeItems: "center",
                  flexShrink: 0,
                  marginTop: 1,
                }}
              >
                <ICheck size={13} />
              </span>
              <span
                style={{
                  fontSize: 14,
                  lineHeight: 1.4,
                  color: dark ? "#F5F1E6" : "var(--ink)",
                }}
              >
                {f}
              </span>
            </div>
          ))}
        </div>

        <Link href="/auth" style={{ marginTop: 26 }}>
          <Btn
            kind={dark ? "yellow" : "primary"}
            size="lg"
            icon={<IArrow size={16} />}
            style={{ width: "100%", justifyContent: "center" }}
          >
            {plan.cta}
          </Btn>
        </Link>
      </Card>
    </Lift>
  );
}

/* ============ NAV ============ */
function Nav() {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px clamp(16px, 4vw, 22px)",
        background: "var(--surface)",
        borderRadius: 22,
        marginBottom: 24,
        position: "sticky",
        top: 16,
        zIndex: 20,
        boxShadow: "0 8px 24px -16px rgba(26,27,31,0.3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <ILogo size={32} />
        <span style={{ fontSize: 17, fontWeight: 700 }}>otclick</span>
      </div>
      <nav className="oc-landing-links" style={{ display: "flex", gap: 28, fontSize: 14 }}>
        <a href="#how" style={{ color: "var(--ink)", textDecoration: "none" }}>Как это работает</a>
        <a href="#security" style={{ color: "var(--ink)", textDecoration: "none" }}>Безопасность</a>
        <a href="#pricing" style={{ color: "var(--ink)", textDecoration: "none" }}>Тарифы</a>
      </nav>
      <Link href="/auth">
        <Btn kind="primary">Войти</Btn>
      </Link>
    </header>
  );
}

/* ============ BENTO ============ */
function BentoCard({
  title,
  sub,
  visual,
}: {
  title: string;
  sub: string;
  visual: React.ReactNode;
}) {
  return (
    <Lift style={{ height: "100%" }}>
      <Card tone="light" style={{ padding: 0, overflow: "hidden", minHeight: 380, height: "100%" }}>
        <div
          style={{
            height: 220,
            background: "var(--bg-deep)",
            position: "relative",
            overflow: "hidden",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
        >
          {visual}
        </div>
        <div style={{ padding: 24 }}>
          <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{title}</div>
          <div style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.55 }}>{sub}</div>
        </div>
      </Card>
    </Lift>
  );
}

function BentoLetter() {
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: 14,
        padding: 16,
        width: "100%",
        boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
      }}
    >
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>Совет №1</div>
      <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 10 }}>
        Сильные достижения{" "}
        <span style={{ background: "var(--yellow-soft)", padding: "0 4px" }}>в опыте работы</span>{" "}
        стоят в конце — поднимем наверх
      </div>
      <div
        style={{
          display: "inline-block",
          background: "var(--sage-soft)",
          color: "var(--ok)",
          padding: "5px 10px",
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        Прирост приглашений +17%
      </div>
    </div>
  );
}

function BentoFilter() {
  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 20,
          right: 30,
          background: "var(--surface)",
          borderRadius: 12,
          padding: 14,
          boxShadow: "0 6px 18px rgba(0,0,0,0.05)",
        }}
      >
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ width: 28, height: 28, borderRadius: 999, background: "var(--coral)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ height: 8, background: "var(--bg-deep)", borderRadius: 4, marginBottom: 5 }} />
            <div style={{ height: 6, background: "var(--bg-deep)", borderRadius: 4, width: "60%" }} />
          </div>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          right: 0,
          bottom: 20,
          left: 30,
          background: "var(--surface)",
          borderRadius: 12,
          padding: 14,
          boxShadow: "0 6px 18px rgba(0,0,0,0.05)",
        }}
      >
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ width: 28, height: 28, borderRadius: 999, background: "var(--yellow)", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 14 }}>T</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, fontWeight: 700 }}>ML-инженер · Тинькофф</div>
            <div style={{ fontSize: 10, color: "var(--muted)" }}>Удалёнка · от 350 000 ₽</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function BentoStats() {
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: 14,
        padding: 18,
        width: "100%",
        boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
        position: "relative",
      }}
    >
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Отправлено сегодня</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{ fontSize: 32, fontWeight: 800, letterSpacing: -1 }}>
          <CountUp to={28} />
        </span>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>/ 30</span>
      </div>
      <div
        style={{
          marginTop: 10,
          display: "inline-block",
          background: "var(--sage-soft)",
          color: "var(--ok)",
          padding: "5px 10px",
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        ✓ В безопасном лимите hh
      </div>
      <div
        style={{
          position: "absolute",
          top: -10,
          right: -10,
          background: "var(--ink)",
          color: "#F5F1E6",
          padding: "10px 14px",
          borderRadius: 12,
          fontSize: 12,
          lineHeight: 1.3,
          maxWidth: 140,
        }}
      >
        <div style={{ color: "var(--muted-2)", fontSize: 10 }}>Скорость отклика</div>
        <div style={{ fontWeight: 700, fontSize: 14 }}>34 сек.</div>
      </div>
    </div>
  );
}

function BentoBlacklist() {
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: 999,
        padding: "12px 18px",
        boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {["var(--coral)", "var(--yellow)", "var(--sage)", "var(--ink)", "var(--coral-soft)"].map((c, i) => (
        <div
          key={i}
          style={{
            width: 38,
            height: 38,
            borderRadius: 999,
            background: c,
            border: "2px solid var(--surface)",
            marginLeft: i ? -14 : 0,
          }}
        />
      ))}
      <div style={{ marginLeft: 12, fontSize: 12, fontWeight: 700 }}>
        +127
        <div style={{ fontSize: 10, fontWeight: 400, color: "var(--muted)" }}>в чс</div>
      </div>
    </div>
  );
}

function BentoChat() {
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          background: "var(--surface)",
          borderRadius: 14,
          padding: 12,
          boxShadow: "0 6px 18px rgba(0,0,0,0.05)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div style={{ width: 32, height: 32, borderRadius: 999, background: "var(--coral)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 800, fontSize: 12 }}>OZ</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 700 }}>Product · Озон</div>
          <Tag tone="ok" style={{ marginTop: 2 }}>Приглашение</Tag>
        </div>
        <div style={{ background: "var(--coral)", color: "#fff", width: 22, height: 22, borderRadius: 999, display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>4</div>
      </div>
      <div
        style={{
          background: "var(--surface)",
          borderRadius: 14,
          padding: 12,
          boxShadow: "0 6px 18px rgba(0,0,0,0.05)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div style={{ width: 32, height: 32, borderRadius: 999, background: "var(--yellow)", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 12 }}>Т</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 700 }}>Senior dev · Тинькофф</div>
          <div style={{ fontSize: 10, color: "var(--muted)" }}>Скиньте удобное время…</div>
        </div>
        <div style={{ background: "var(--ink)", color: "#fff", width: 22, height: 22, borderRadius: 999, display: "grid", placeItems: "center", fontSize: 11, fontWeight: 700 }}>1</div>
      </div>
    </div>
  );
}

function BentoCTA() {
  return (
    <Card
      tone="dark"
      style={{ padding: 28, minHeight: 380, height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", position: "relative", overflow: "hidden" }}
    >
      <div>
        <Tag tone="yellow" dot>Без карты</Tag>
        <div
          style={{
            fontSize: 32,
            fontWeight: 700,
            letterSpacing: -1,
            lineHeight: 1.05,
            marginTop: 16,
            color: "#F5F1E6",
          }}
        >
          Бесплатный <span className="serif" style={{ fontWeight: 400, color: "var(--yellow)" }}>пробный период</span> на 7 дней
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          right: -30,
          bottom: 110,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          alignItems: "flex-end",
          pointerEvents: "none",
        }}
      >
        {["Приглашение", "Приглашение", "Приглашение"].map((t, i) => (
          <div
            key={i}
            style={{
              background: "var(--yellow)",
              color: "var(--ink)",
              padding: "8px 14px",
              borderRadius: 10,
              fontSize: 14,
              fontWeight: 700,
              transform: `rotate(${-4 + i * 2}deg)`,
              opacity: 0.5 + i * 0.2,
            }}
          >
            {t}
          </div>
        ))}
      </div>

      <Link href="/auth" style={{ position: "relative", zIndex: 1 }}>
        <Btn kind="yellow" size="lg" icon={<IArrow size={16} />} style={{ width: "100%", justifyContent: "center" }}>
          Начать сейчас
        </Btn>
      </Link>
    </Card>
  );
}
