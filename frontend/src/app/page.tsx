import Link from "next/link";
import { Btn, Card, StatusDot } from "@/components/otclick/ui";
import { IArrow, ICheck, ILogo } from "@/components/otclick/icons";
import {
  Lift,
  Reveal,
  StaggerGroup,
  StaggerItem,
} from "@/components/otclick/landing/motion";
import { HeroMock } from "@/components/otclick/landing/hero-mock";

const STEPS = [
  {
    n: "01",
    t: "Подключить hh.ru",
    s: "Подключение выполняется через защищённую web-сессию. После этого приложение может читать вакансии и работать с вашим аккаунтом.",
  },
  {
    n: "02",
    t: "Добавить источники поиска",
    s: "Сохраняйте поисковые URL и запускайте сбор вакансий вручную. Уже найденные позиции остаются в общей очереди.",
  },
  {
    n: "03",
    t: "Проверить оценку",
    s: "Сначала применяется жёсткий фильтр, затем AI оценивает полное описание вакансии по профилю кандидата и объясняет результат.",
  },
  {
    n: "04",
    t: "Принять решение",
    s: "Выберите, отклоните или отложите вакансию. Для выбранной позиции можно подготовить и отдельно подтвердить сопроводительное письмо.",
  },
];

const CAPABILITIES = [
  {
    t: "Единая очередь вакансий",
    s: "Новые позиции накапливаются в PostgreSQL и не теряются между запусками поиска.",
  },
  {
    t: "Hard-фильтр до AI",
    s: "Очевидные несоответствия отсекаются до обращения к модели, с сохранением конкретной причины решения.",
  },
  {
    t: "AI-скоринг 0–100",
    s: "Модель анализирует полное описание вакансии, профиль кандидата и подтверждённые факты, а не только заголовок.",
  },
  {
    t: "Ручной review",
    s: "Для каждой вакансии доступны решения: выбрать, отклонить или отложить. История решения сохраняется.",
  },
  {
    t: "Индивидуальные письма",
    s: "Сопроводительное готовится отдельно под выбранную вакансию. После редактирования требуется новое подтверждение текста.",
  },
  {
    t: "Контролируемая очередь отправки",
    s: "Очередь поддерживает паузу, продолжение и остановку после текущего элемента. Реальная отправка включается отдельно.",
  },
];

const SAFETY = [
  {
    t: "Решение остаётся за пользователем",
    s: "Низкий score или ошибка модели не превращаются в автоматическое разрешение на действие.",
  },
  {
    t: "Отправка выключена по умолчанию",
    s: "Поиск, оценка и подготовка письма можно проверять независимо от реальной отправки откликов.",
  },
  {
    t: "Сессия хранится на сервере",
    s: "Работа с hh.ru выполняется серверной частью приложения; чувствительные данные не выводятся в интерфейс как открытые значения.",
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

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
          gap: 48,
          alignItems: "center",
          padding: "56px 0 72px",
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
              Self-hosted · один пользователь
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
              Поиск вакансий<br />
              под контролем.<br />
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                от поиска до решения
              </span>
            </h1>
          </Reveal>

          <Reveal y={18} delay={0.12}>
            <p
              style={{
                fontSize: 19,
                color: "var(--muted)",
                margin: "26px 0 0",
                maxWidth: 560,
                lineHeight: 1.55,
              }}
            >
              Otclick собирает вакансии с hh.ru, оценивает их по вашему профилю,
              помогает разобрать причины score и готовит индивидуальные сопроводительные.
              Решение и отправка остаются контролируемыми этапами.
            </p>
          </Reveal>

          <Reveal y={16} delay={0.18}>
            <div style={{ marginTop: 32, display: "flex", gap: 12, flexWrap: "wrap" }}>
              <Link href="/auth">
                <Btn kind="primary" size="lg" icon={<IArrow size={16} />}>
                  Войти
                </Btn>
              </Link>
              <a href="#how">
                <Btn kind="ghost" size="lg">
                  Как работает
                </Btn>
              </a>
            </div>
          </Reveal>
        </div>

        <HeroMock />
      </section>

      <section id="how" style={{ marginBottom: 96, scrollMarginTop: 24 }}>
        <Reveal>
          <div style={{ textAlign: "center", marginBottom: 48 }}>
            <Eyebrow>Рабочий процесс</Eyebrow>
            <h2
              style={{
                fontSize: "clamp(32px, 7vw, 52px)",
                fontWeight: 700,
                letterSpacing: -2,
                margin: 0,
              }}
            >
              От источника поиска до{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                подтверждённого решения
              </span>
            </h2>
          </div>
        </Reveal>

        <StaggerGroup
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 230px), 1fr))",
            gap: 18,
          }}
        >
          {STEPS.map((step) => (
            <StaggerItem key={step.n}>
              <Lift style={{ height: "100%" }}>
                <Card tone="light" style={{ padding: 28, minHeight: 230, height: "100%" }}>
                  <div
                    className="serif"
                    style={{ fontSize: 44, color: "var(--coral)", lineHeight: 1, marginBottom: 16 }}
                  >
                    {step.n}
                  </div>
                  <div style={{ fontSize: 21, fontWeight: 700, marginBottom: 8 }}>{step.t}</div>
                  <div style={{ fontSize: 14.5, color: "var(--muted)", lineHeight: 1.55 }}>
                    {step.s}
                  </div>
                </Card>
              </Lift>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      <section id="capabilities" style={{ marginBottom: 96, scrollMarginTop: 24 }}>
        <Reveal>
          <div style={{ textAlign: "center", marginBottom: 48 }}>
            <Eyebrow>Возможности</Eyebrow>
            <h2
              style={{
                fontSize: "clamp(32px, 7vw, 52px)",
                fontWeight: 700,
                letterSpacing: -2,
                margin: 0,
              }}
            >
              Основные функции{" "}
              <span className="serif" style={{ fontWeight: 400, color: "var(--coral)" }}>
                без лишних обещаний
              </span>
            </h2>
          </div>
        </Reveal>

        <StaggerGroup
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
            gap: 18,
          }}
        >
          {CAPABILITIES.map((item) => (
            <StaggerItem key={item.t}>
              <Card tone="light" style={{ padding: 26, minHeight: 190, height: "100%" }}>
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 12,
                    background: "var(--yellow)",
                    display: "grid",
                    placeItems: "center",
                    marginBottom: 18,
                  }}
                >
                  <ICheck size={18} />
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{item.t}</div>
                <div style={{ fontSize: 14.5, color: "var(--muted)", lineHeight: 1.55 }}>
                  {item.s}
                </div>
              </Card>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      <section id="security" style={{ marginBottom: 72, scrollMarginTop: 24 }}>
        <Card
          tone="dark"
          style={{
            padding: "clamp(30px, 6vw, 56px) clamp(20px, 5vw, 48px)",
            overflow: "hidden",
          }}
        >
          <Reveal>
            <div style={{ textAlign: "center", maxWidth: 700, margin: "0 auto 42px" }}>
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
                Контроль и безопасность
              </div>
              <h2
                style={{
                  fontSize: "clamp(30px, 7vw, 48px)",
                  fontWeight: 700,
                  letterSpacing: -1.8,
                  margin: 0,
                  color: "#F5F1E6",
                }}
              >
                Автоматизация не должна отменять проверку результата
              </h2>
            </div>
          </Reveal>

          <StaggerGroup
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
              gap: 16,
              maxWidth: 980,
              margin: "0 auto",
            }}
          >
            {SAFETY.map((item) => (
              <StaggerItem key={item.t}>
                <div
                  style={{
                    background: "#ffffff0a",
                    border: "1px solid #ffffff14",
                    borderRadius: 18,
                    padding: 22,
                    height: "100%",
                  }}
                >
                  <div style={{ fontSize: 19, fontWeight: 700, color: "#F5F1E6", marginBottom: 8 }}>
                    {item.t}
                  </div>
                  <div style={{ fontSize: 14, color: "#ffffff80", lineHeight: 1.55 }}>{item.s}</div>
                </div>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </Card>
      </section>

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
        <span>© {new Date().getFullYear()} Otclick</span>
        <span>Self-hosted vacancy workflow</span>
      </footer>
    </main>
  );
}

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
        <a href="#how" style={{ color: "var(--ink)", textDecoration: "none" }}>
          Как работает
        </a>
        <a href="#capabilities" style={{ color: "var(--ink)", textDecoration: "none" }}>
          Возможности
        </a>
        <a href="#security" style={{ color: "var(--ink)", textDecoration: "none" }}>
          Безопасность
        </a>
      </nav>
      <Link href="/auth">
        <Btn kind="primary">Войти</Btn>
      </Link>
    </header>
  );
}
