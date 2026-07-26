"use client";

import { ButtonHTMLAttributes, CSSProperties, ReactNode, forwardRef } from "react";
import Link from "next/link";

// ============ Card ============
export type CardTone = "light" | "dark" | "cream";

const CARD_TONE: Record<CardTone, CSSProperties> = {
  light: { background: "var(--surface)", color: "var(--ink)" },
  dark: { background: "var(--ink)", color: "#F5F1E6" },
  cream: { background: "var(--bg-deep)", color: "var(--ink)" },
};

type CardProps = {
  tone?: CardTone;
  style?: CSSProperties;
  children: ReactNode;
  className?: string;
  /** makes the whole card a single click target */
  interactive?: { href: string } | { onClick: () => void };
} & React.HTMLAttributes<HTMLDivElement>;

export function Card({ tone = "light", style, children, className, interactive, ...rest }: CardProps) {
  const cls = ["oc-card", interactive && "oc-card--interactive", className].filter(Boolean).join(" ");
  const css = { ...CARD_TONE[tone], ...style };

  if (interactive && "href" in interactive) {
    return (
      <Link href={interactive.href} className={cls} style={css}>
        {children}
      </Link>
    );
  }
  if (interactive) {
    return (
      <button type="button" onClick={interactive.onClick} className={cls} style={css}>
        {children}
      </button>
    );
  }
  return (
    <div className={cls} style={css} {...rest}>
      {children}
    </div>
  );
}

// ============ Btn ============
export type BtnKind = "primary" | "yellow" | "coral" | "ghost" | "ghostDark" | "soft" | "white";
export type BtnSize = "sm" | "md" | "lg";

function btnClass(kind: BtnKind, size: BtnSize, className?: string) {
  return ["oc-btn", `oc-btn--${kind}`, `oc-btn--${size}`, className].filter(Boolean).join(" ");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  kind?: BtnKind;
  size?: BtnSize;
  icon?: ReactNode;
  loading?: boolean;
};

export const Btn = forwardRef<HTMLButtonElement, BtnProps>(function Btn(
  { kind = "ghost", size = "md", icon, loading, children, className, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={btnClass(kind, size, className)}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="oc-spinner" /> : icon}
      {children}
    </button>
  );
});

// ============ LinkBtn ============
// Replaces every <Link><Btn/></Link>: a <button> inside an <a> is invalid DOM,
// produces two tab stops, and breaks keyboard activation.
export function LinkBtn({
  href,
  kind = "ghost",
  size = "md",
  icon,
  children,
  external,
  className,
  style,
  label,
}: {
  href: string;
  kind?: BtnKind;
  size?: BtnSize;
  icon?: ReactNode;
  children: ReactNode;
  external?: boolean;
  className?: string;
  style?: CSSProperties;
  /** required when `children` is empty (icon-only), otherwise the link has no name */
  label?: string;
}) {
  const cls = btnClass(kind, size, className);
  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cls}
        style={style}
        aria-label={label}
      >
        {icon}
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} style={style} aria-label={label}>
      {icon}
      {children}
    </Link>
  );
}

// ============ IconBtn ============
// `label` is required: it is both the accessible name and the tooltip.
export function IconBtn({
  label,
  icon,
  onClick,
  href,
  size = "md",
  onDark,
  disabled,
  style,
}: {
  label: string;
  icon: ReactNode;
  onClick?: () => void;
  href?: string;
  size?: "md" | "lg";
  onDark?: boolean;
  disabled?: boolean;
  style?: CSSProperties;
}) {
  const cls = ["oc-icon-btn", `oc-icon-btn--${size}`, onDark && "oc-icon-btn--onDark"]
    .filter(Boolean)
    .join(" ");
  const inner = href ? (
    <Link href={href} aria-label={label} className={cls} style={style}>
      {icon}
    </Link>
  ) : (
    <button type="button" aria-label={label} onClick={onClick} disabled={disabled} className={cls} style={style}>
      {icon}
    </button>
  );
  return (
    <span className="oc-tip" data-tip={label}>
      {inner}
    </span>
  );
}

// ============ Tooltip / KeyHint ============
export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="oc-tip" data-tip={text}>
      {children}
    </span>
  );
}

export function KeyHint({ children }: { children: ReactNode }) {
  return <kbd className="oc-kbd">{children}</kbd>;
}

// ============ Tag ============
export type TagTone = "neutral" | "ok" | "warn" | "err" | "yellow" | "coral" | "dark";

const TAG: Record<TagTone, { bg: string; fg: string; dot: string }> = {
  neutral: { bg: "#F1ECE1", fg: "var(--ink)", dot: "var(--muted)" },
  ok: { bg: "#E2EEDB", fg: "#2F5C36", dot: "var(--ok)" },
  warn: { bg: "#FBEACB", fg: "#7A5418", dot: "var(--warn)" },
  err: { bg: "#F8D9D2", fg: "#7C2A1E", dot: "var(--err)" },
  yellow: { bg: "var(--yellow)", fg: "var(--ink)", dot: "var(--ink)" },
  coral: { bg: "var(--coral-soft)", fg: "#7C2A1E", dot: "var(--coral)" },
  dark: { bg: "var(--ink)", fg: "#F5F1E6", dot: "var(--yellow)" },
};

export function Tag({
  tone = "neutral",
  dot,
  children,
  style,
}: {
  tone?: TagTone;
  dot?: boolean;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const p = TAG[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: p.bg,
        color: p.fg,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {dot && (
        <span
          style={{ width: 6, height: 6, borderRadius: 999, background: p.dot, flexShrink: 0 }}
        />
      )}
      {children}
    </span>
  );
}

// ============ StatusDot ============
export type StatusTone = "ok" | "warn" | "err" | "muted";

export function StatusDot({
  tone = "ok",
  size = 8,
  glow = true,
}: {
  tone?: StatusTone;
  size?: number;
  glow?: boolean;
}) {
  const c =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "err"
          ? "var(--err)"
          : "var(--muted-2)";
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: 999,
        background: c,
        boxShadow: glow ? `0 0 0 3px ${c}22` : "none",
        flexShrink: 0,
      }}
    />
  );
}

// ============ Toggle ============
export function Toggle({
  on,
  onChange,
  disabled,
}: {
  on: boolean;
  onChange?: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => !disabled && onChange?.(!on)}
      disabled={disabled}
      style={{
        width: 40,
        height: 22,
        borderRadius: 999,
        border: "none",
        position: "relative",
        background: on ? "var(--ink)" : "var(--muted-2)",
        transition: "background var(--dur) var(--ease)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 3,
          left: on ? 21 : 3,
          width: 16,
          height: 16,
          borderRadius: 999,
          background: "#fff",
          transition: "left var(--dur) var(--ease)",
        }}
      />
    </button>
  );
}

// ============ Field (read-only-ish) ============
export function Field({
  label,
  value,
  mono,
  readonly,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  readonly?: boolean;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          fontSize: 11,
          color: "var(--muted)",
          textTransform: "uppercase",
          letterSpacing: 0.5,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          padding: "10px 14px",
          borderRadius: 12,
          background: readonly ? "var(--bg-deep)" : "transparent",
          border: readonly ? "none" : "1px solid var(--line)",
          fontFamily: mono ? "JetBrains Mono, monospace" : "inherit",
          fontSize: 14,
          color: readonly ? "var(--muted)" : "var(--ink)",
        }}
      >
        {value || "—"}
      </div>
    </div>
  );
}

// ============ TextInput / TextArea (editable) ============
export function TextInput({
  label,
  ...rest
}: { label?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      {label && (
        <div
          style={{
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            marginBottom: 4,
          }}
        >
          {label}
        </div>
      )}
      <input
        {...rest}
        className="oc-input"
        style={{
          width: "100%",
          padding: "10px 14px",
          borderRadius: 12,
          border: "1px solid var(--line)",
          background: "#fff",
          outline: "none",
          fontFamily: "inherit",
          fontSize: 14,
          color: "var(--ink)",
          ...rest.style,
        }}
      />
    </label>
  );
}

export function Select({
  label,
  children,
  ...rest
}: { label?: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      {label && (
        <div
          style={{
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            marginBottom: 4,
          }}
        >
          {label}
        </div>
      )}
      <select
        {...rest}
        className="oc-input"
        style={{
          width: "100%",
          padding: "10px 14px",
          borderRadius: 12,
          border: "1px solid var(--line)",
          background: "#fff",
          outline: "none",
          fontFamily: "inherit",
          fontSize: 14,
          color: "var(--ink)",
          ...rest.style,
        }}
      >
        {children}
      </select>
    </label>
  );
}

// ============ Skeleton ============
export function Skeleton({
  h = 14,
  w = "100%",
  radius = "var(--r-sm)",
  count = 1,
}: {
  h?: number;
  w?: number | string;
  radius?: string;
  count?: number;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="oc-skeleton" style={{ height: h, width: w, borderRadius: radius }} />
      ))}
    </div>
  );
}

// ============ EmptyState ============
export type EmptyAction = { label: string; href: string } | { label: string; onClick: () => void };

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: EmptyAction;
}) {
  return (
    <div className="oc-empty">
      <div className="oc-empty__icon">{icon}</div>
      <div className="oc-empty__title">{title}</div>
      {description && <div className="oc-empty__desc">{description}</div>}
      {action &&
        ("href" in action ? (
          <LinkBtn href={action.href} kind="primary" size="sm">
            {action.label}
          </LinkBtn>
        ) : (
          <Btn kind="primary" size="sm" onClick={action.onClick}>
            {action.label}
          </Btn>
        ))}
    </div>
  );
}

// ============ Banner ============
export function Banner({
  tone,
  title,
  description,
  action,
  onDismiss,
}: {
  tone: "ok" | "warn" | "err" | "info";
  title: string;
  description?: string;
  action?: EmptyAction;
  onDismiss?: () => void;
}) {
  const dotTone = tone === "info" ? "muted" : tone;
  return (
    <div className={`oc-banner oc-banner--${tone}`} role={tone === "err" ? "alert" : "status"}>
      <StatusDot tone={dotTone as StatusTone} size={10} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        {description && <div style={{ fontSize: 12, opacity: 0.85 }}>{description}</div>}
      </div>
      {action &&
        ("href" in action ? (
          <LinkBtn href={action.href} kind="primary" size="sm">
            {action.label}
          </LinkBtn>
        ) : (
          <Btn kind="primary" size="sm" onClick={action.onClick}>
            {action.label}
          </Btn>
        ))}
      {onDismiss && (
        <IconBtn label="скрыть" icon={<span style={{ fontSize: 16, lineHeight: 1 }}>×</span>} onClick={onDismiss} />
      )}
    </div>
  );
}

// ============ Breadcrumbs / PageHeader ============
export type Crumb = { label: string; href?: string };

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="oc-crumbs" aria-label="Хлебные крошки">
      {items.map((c, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={`${c.label}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            {i > 0 && <span aria-hidden="true">/</span>}
            {c.href && !isLast ? (
              <Link href={c.href}>{c.label}</Link>
            ) : (
              // aria-current belongs to the current page only, not to any crumb
              // that merely happens to lack an href
              <span aria-current={isLast ? "page" : undefined}>{c.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

export function PageHeader({
  title,
  subtitle,
  crumbs,
  actions,
}: {
  title: string;
  subtitle?: string;
  crumbs?: Crumb[];
  actions?: ReactNode;
}) {
  return (
    <header className="oc-page-header">
      <div style={{ minWidth: 0 }}>
        {crumbs && crumbs.length > 0 && <Breadcrumbs items={crumbs} />}
        <h1 className="oc-page-header__title">{title}</h1>
        {subtitle && <p className="oc-page-header__sub">{subtitle}</p>}
      </div>
      {actions && <div className="oc-page-header__actions">{actions}</div>}
    </header>
  );
}

// ============ SegmentedTabs ============
export function SegmentedTabs({
  items,
  value,
  onChange,
  label = "Фильтр",
}: {
  items: { id: string; label: string; count?: number }[];
  value: string;
  onChange: (id: string) => void;
  label?: string;
}) {
  return (
    <div className="oc-seg" role="tablist" aria-label={label}>
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          role="tab"
          aria-selected={value === it.id}
          className="oc-seg__item"
          onClick={() => onChange(it.id)}
        >
          {it.label}
          {it.count !== undefined && <span className="oc-seg__count">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ============ Pager ============
export function Pager({
  page,
  pages,
  onChange,
}: {
  page: number;
  pages: number;
  onChange: (next: number) => void;
}) {
  return (
    <div className="oc-pager">
      <button
        type="button"
        className="oc-pager__btn"
        onClick={() => onChange(Math.max(0, page - 1))}
        disabled={page === 0}
        aria-label="предыдущая страница"
      >
        ‹
      </button>
      {/* a span, not a button: it has no action, and a focusable no-op is a dead tab stop */}
      <span className="oc-pager__btn" aria-current="page">
        {page + 1}
      </span>
      <button
        type="button"
        className="oc-pager__btn"
        onClick={() => onChange(Math.min(pages - 1, page + 1))}
        disabled={page + 1 >= pages}
        aria-label="следующая страница"
      >
        ›
      </button>
    </div>
  );
}
