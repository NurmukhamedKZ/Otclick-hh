# Frontend UI/UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the 7 authed pages of the Otclick frontend a real design system, discoverable labelled navigation with counters, page headings with breadcrumbs, a working ⌘K command palette, and shareable URL state on `/applications`.

**Architecture:** Design tokens and all interactive states live in `frontend/src/app/globals.css` as `.oc-*` classes. `frontend/src/components/otclick/ui.tsx` stays the single component module and emits those classes instead of inline style objects — existing props are preserved so call sites do not churn. Pure logic (URL state, nav counters, palette matching) is extracted into `frontend/src/lib/*.ts` modules and unit-tested with vitest; cosmetics are verified with `tsc` + `next build` + a browser checklist.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript 5, Tailwind v4 (imported, used only for its reset — no utility migration), `@tanstack/react-query`, `@supabase/ssr`, vitest (added by Task 3).

**Spec:** `docs/superpowers/specs/2026-07-26-frontend-ui-ux-overhaul-design.md`

## Global Constraints

- **Palette is frozen.** `--bg: #EFEAE0`, `--surface: #FFFFFF`, `--ink: #1A1B1F`, `--yellow: #F5CB3D`, `--coral: #E96B58`, plus the existing `--muted*`, `--line*`, `--sage*`, `--ok`, `--warn`, `--err`. Do not add, remove, or alter a color variable.
- **Fonts are frozen.** Manrope (body), Instrument Serif (`.serif`), JetBrains Mono (`.mono`).
- **Out of scope — do not edit:** `src/app/page.tsx` (landing), `src/app/auth/`, `src/app/onboarding/`, `src/components/otclick/landing/`, everything under `backend/`.
- **No dark mode.**
- **New runtime dependencies: none.** vitest is a `devDependency` and is the only package added by this plan.
- **UI copy is Russian**, lowercase-leaning, matching the existing tone (`автоотклик`, `отклики`, `фильтры`). Keep technical identifiers (`vacancy_id`, `hh`) as-is.
- **Every new transition must use `var(--dur)` / `var(--ease)`** so the existing `@media (prefers-reduced-motion: reduce)` block in `globals.css` keeps neutralizing it.
- **Every icon-only control needs an `aria-label`.**
- **Gate for every task:** `npx tsc --noEmit` clean, `npm run build` clean, and from Task 3 on, `npx vitest run` green. All commands run from `frontend/`.

---

### Task 1: Design tokens + interactive-state component base

**Files:**
- Modify: `frontend/src/app/globals.css` (append token block after `:root`, append component-class section before the responsive section at line 91)
- Modify: `frontend/src/components/otclick/ui.tsx` (rewrite `Btn`, `Card`; add `LinkBtn`, `IconBtn`, `Tooltip`, `KeyHint`)

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `Btn` — unchanged props (`kind?: BtnKind`, `size?: BtnSize`, `icon?: ReactNode`) plus new `loading?: boolean`
  - `LinkBtn({ href, kind?, size?, icon?, children, external?, ...})` — a `next/link` styled as a button
  - `IconBtn({ label, icon, onClick?, href?, tone?, size? })` — `label` is required and becomes both `aria-label` and the tooltip
  - `Card` — unchanged props plus `interactive?: { href: string } | { onClick: () => void }`
  - `Tooltip({ text, children })` and `KeyHint({ children })`
  - CSS classes `.oc-btn`, `.oc-btn--{primary|yellow|coral|ghost|ghostDark|soft|white}`, `.oc-btn--{sm|md|lg}`, `.oc-card`, `.oc-card--interactive`, `.oc-icon-btn`, `.oc-tip`, `.oc-kbd`, and the token variables below

- [ ] **Step 1: Add the token block to `globals.css`**

Insert immediately after the closing `}` of the existing `:root` block (currently ends line 26):

```css
:root {
  /* spacing */
  --s-1: 6px;
  --s-2: 10px;
  --s-3: 14px;
  --s-4: 18px;
  --s-5: 22px;
  --s-6: 28px;

  /* radii */
  --r-sm: 10px;
  --r-md: 16px;
  --r-lg: 22px;
  --r-pill: 999px;

  /* elevation */
  --sh-1: 0 1px 0 var(--line-2);
  --sh-2: 0 8px 24px -12px rgba(26, 27, 31, 0.28);

  /* motion */
  --dur: 140ms;
  --ease: cubic-bezier(.2, .8, .2, 1);

  /* focus */
  --focus-ring: 2px solid var(--ink);
  --focus-offset: 2px;

  /* layers */
  --z-drawer: 40;
  --z-nav: 50;
  --z-modal: 60;
  --z-toast: 70;
}

/* every interactive element gets one consistent, visible focus ring */
:where(a, button, input, select, textarea, [tabindex]):focus-visible {
  outline: var(--focus-ring);
  outline-offset: var(--focus-offset);
  border-radius: var(--r-sm);
}
```

- [ ] **Step 2: Add the component classes to `globals.css`**

Insert directly before the `/* ============ responsive (mobile) ============ */` comment (currently line 91):

```css
/* ============ components ============ */
.oc-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  border-radius: var(--r-pill);
  font-family: inherit;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  text-decoration: none;
  transition: transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease),
    background var(--dur) var(--ease), opacity var(--dur) var(--ease);
}
.oc-btn--sm { padding: 7px 12px; font-size: 13px; }
.oc-btn--md { padding: 10px 16px; font-size: 14px; }
.oc-btn--lg { padding: 14px 22px; font-size: 15px; }

.oc-btn--primary   { background: var(--ink);      color: #fff;        border: 1px solid var(--ink); }
.oc-btn--yellow    { background: var(--yellow);   color: var(--ink);  border: 1px solid var(--yellow); }
.oc-btn--coral     { background: var(--coral);    color: #fff;        border: 1px solid var(--coral); }
.oc-btn--ghost     { background: transparent;     color: var(--ink);  border: 1px solid var(--line); }
.oc-btn--ghostDark { background: transparent;     color: #F5F1E6;     border: 1px solid #ffffff22; }
.oc-btn--soft      { background: var(--bg-deep);  color: var(--ink);  border: 1px solid transparent; }
.oc-btn--white     { background: #fff;            color: var(--ink);  border: 1px solid var(--line); }

.oc-btn:hover:not([disabled]):not([aria-busy="true"]) {
  transform: translateY(-1px);
  box-shadow: var(--sh-2);
}
.oc-btn--ghost:hover:not([disabled]) { background: var(--line-2); }
.oc-btn--ghostDark:hover:not([disabled]) { background: #ffffff15; }

.oc-btn:active:not([disabled]) { transform: translateY(0); box-shadow: none; }

.oc-btn[disabled],
.oc-btn[aria-busy="true"] {
  opacity: .5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.oc-spinner {
  width: 1em;
  height: 1em;
  border-radius: var(--r-pill);
  border: 2px solid currentColor;
  border-top-color: transparent;
  animation: oc-spin .7s linear infinite;
  flex-shrink: 0;
}

.oc-card {
  border-radius: var(--r-lg);
  padding: var(--s-5);
  position: relative;
}
.oc-card--interactive {
  display: block;
  text-align: left;
  width: 100%;
  border: none;
  font: inherit;
  color: inherit;
  cursor: pointer;
  text-decoration: none;
  transition: transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.oc-card--interactive:hover { transform: translateY(-2px); box-shadow: var(--sh-2); }
.oc-card--interactive:active { transform: translateY(0); box-shadow: none; }

.oc-icon-btn {
  display: grid;
  place-items: center;
  border: none;
  background: transparent;
  color: inherit;
  border-radius: var(--r-sm);
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.oc-icon-btn--md { width: 34px; height: 34px; }
.oc-icon-btn--lg { width: 44px; height: 44px; }
.oc-icon-btn:hover:not([disabled]) { background: var(--line-2); }
.oc-icon-btn--onDark:hover:not([disabled]) { background: #ffffff22; }
.oc-icon-btn[disabled] { opacity: .5; cursor: not-allowed; }

/* CSS-only tooltip: no dependency, no JS, no portal */
.oc-tip { position: relative; display: inline-flex; }
.oc-tip::after {
  content: attr(data-tip);
  position: absolute;
  left: 50%;
  top: calc(100% + 8px);
  transform: translateX(-50%);
  background: var(--ink);
  color: #F5F1E6;
  padding: 5px 9px;
  border-radius: var(--r-sm);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur) var(--ease);
  z-index: var(--z-modal);
}
.oc-tip:hover::after,
.oc-tip:focus-within::after { opacity: 1; }

.oc-kbd {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--muted);
  background: var(--bg-deep);
  padding: 2px 6px;
  border-radius: 6px;
}
```

- [ ] **Step 3: Rewrite `Btn` and `Card` in `ui.tsx`, add the new primitives**

Replace the `// ============ Card ============` and `// ============ Btn ============` sections of `frontend/src/components/otclick/ui.tsx` (lines 5–90) with:

```tsx
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
}: {
  href: string;
  kind?: BtnKind;
  size?: BtnSize;
  icon?: ReactNode;
  children: ReactNode;
  external?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  const cls = btnClass(kind, size, className);
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls} style={style}>
        {icon}
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} style={style}>
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
```

Keep the rest of `ui.tsx` (`Tag`, `StatusDot`, `Toggle`, `Field`, `TextInput`, `Select`) untouched in this step — Task 2 handles them.

- [ ] **Step 4: Verify the build**

Run from `frontend/`:

```bash
npx tsc --noEmit && npm run build
```

Expected: both exit 0. If `tsc` reports `CSSProperties`/`ReactNode` unused-import errors, the existing import line at the top of `ui.tsx` already provides them — do not add a duplicate import.

- [ ] **Step 5: Verify in the browser**

```bash
npm run dev
```

Open `http://localhost:3000/dashboard` and confirm:
- buttons visually match the previous design (same colors, radii, padding)
- hovering a button lifts it 1px and adds a shadow
- pressing `Tab` moves focus and every stop shows a dark 2px ring
- nothing on the dashboard shifted position

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/globals.css frontend/src/components/otclick/ui.tsx
git commit -m "feat(ui): design tokens and interactive states for Btn/Card

Adds spacing/radii/shadow/motion/focus/z-index tokens and moves Btn and
Card onto .oc-* classes so hover, active, focus-visible and disabled
states are expressible at all. Adds LinkBtn (fixes button-inside-anchor),
IconBtn (aria-label required), CSS-only Tooltip and KeyHint.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Page structure primitives + headings on all 7 pages

**Files:**
- Modify: `frontend/src/components/otclick/ui.tsx` (add `Skeleton`, `EmptyState`, `Banner`, `Breadcrumbs`, `PageHeader`, `SegmentedTabs`, `Pager`; add states to `Toggle`, `TextInput`, `Select`)
- Modify: `frontend/src/app/globals.css` (append `.oc-skeleton`, `.oc-empty`, `.oc-banner`, `.oc-crumbs`, `.oc-seg`, `.oc-pager` classes)
- Modify: `frontend/src/app/(app)/dashboard/page.tsx`, `applications/page.tsx`, `chats/page.tsx`, `todo/page.tsx`, `notifications/page.tsx`, `account/page.tsx`, `billing/page.tsx` (add `PageHeader`)
- Modify: `frontend/src/app/(app)/account/page.tsx:251,261` (replace `<Link><Btn>` with `LinkBtn`)
- Delete: `frontend/src/components/otclick/topbar.tsx`

**Interfaces:**
- Consumes: `Btn`, `LinkBtn`, `IconBtn`, `KeyHint` from Task 1
- Produces:
  - `Skeleton({ h?, w?, radius?, count? })` — `h` defaults `14`, `w` defaults `"100%"`, `count` defaults `1`
  - `EmptyState({ icon, title, description?, action? })` where `action?: { label: string; href: string } | { label: string; onClick: () => void }`
  - `Banner({ tone, title, description?, action?, onDismiss? })` with `tone: "ok" | "warn" | "err" | "info"`
  - `Breadcrumbs({ items })` where `items: { label: string; href?: string }[]` — the last item renders as plain text with `aria-current="page"`
  - `PageHeader({ title, subtitle?, crumbs?, actions? })`
  - `SegmentedTabs({ items, value, onChange })` where `items: { id: string; label: string; count?: number }[]`
  - `Pager({ page, pages, onChange })` — `page` is 0-based

- [ ] **Step 1: Append the classes to `globals.css`**

Add to the `/* ============ components ============ */` section:

```css
.oc-skeleton {
  background: linear-gradient(90deg, var(--line-2) 25%, var(--bg-deep) 37%, var(--line-2) 63%);
  background-size: 400% 100%;
  animation: oc-shimmer 1.4s ease infinite;
  border-radius: var(--r-sm);
}
@keyframes oc-shimmer {
  from { background-position: 100% 50%; }
  to   { background-position: 0 50%; }
}

.oc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--s-2);
  padding: var(--s-6) var(--s-4);
  color: var(--muted);
}
.oc-empty__icon {
  width: 48px;
  height: 48px;
  border-radius: var(--r-md);
  display: grid;
  place-items: center;
  background: var(--bg-deep);
  color: var(--muted);
}
.oc-empty__title { font-size: 15px; font-weight: 700; color: var(--ink); }
.oc-empty__desc { font-size: 13px; max-width: 340px; }

.oc-banner {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  border-radius: var(--r-md);
  padding: var(--s-3) var(--s-4);
  margin-bottom: var(--s-4);
}
.oc-banner--ok   { background: var(--sage-soft);   color: var(--ink); }
.oc-banner--warn { background: var(--yellow-soft); color: var(--ink); }
.oc-banner--err  { background: var(--coral-soft);  color: #7C2A1E; }
.oc-banner--info { background: var(--bg-deep);     color: var(--ink); }

.oc-crumbs {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  font-size: 12px;
  color: var(--muted);
  margin-bottom: var(--s-1);
  flex-wrap: wrap;
}
.oc-crumbs a { color: var(--muted); text-decoration: none; }
.oc-crumbs a:hover { color: var(--ink); text-decoration: underline; }
.oc-crumbs [aria-current="page"] { color: var(--ink); font-weight: 600; }

.oc-seg { display: flex; gap: var(--s-1); flex-wrap: wrap; }
.oc-seg__item {
  border: none;
  font-family: inherit;
  background: var(--bg-deep);
  color: var(--ink);
  padding: 8px 14px;
  border-radius: var(--r-pill);
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.oc-seg__item:hover { background: var(--line-2); }
.oc-seg__item[aria-selected="true"] { background: var(--ink); color: #F5F1E6; }
.oc-seg__item[aria-selected="true"]:hover { background: var(--ink-soft); }
.oc-seg__count {
  font-family: 'JetBrains Mono', monospace;
  background: #fff;
  padding: 2px 7px;
  border-radius: var(--r-pill);
  font-size: 11px;
}
.oc-seg__item[aria-selected="true"] .oc-seg__count { background: #ffffff20; }

.oc-pager { display: inline-flex; align-items: center; gap: var(--s-1); }
.oc-pager__btn {
  padding: 6px 12px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--ink);
  border-radius: 8px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.oc-pager__btn:hover:not([disabled]) { background: var(--bg-deep); }
.oc-pager__btn[disabled] { opacity: .4; cursor: not-allowed; }
.oc-pager__btn[aria-current="page"] { background: var(--ink); color: #F5F1E6; border-color: var(--ink); }

.oc-page-header {
  display: flex;
  align-items: flex-end;
  gap: var(--s-4);
  padding: var(--s-1) 0 var(--s-4);
  flex-wrap: wrap;
}
.oc-page-header__title { font-size: 28px; font-weight: 700; letter-spacing: -.5px; }
.oc-page-header__sub { color: var(--muted); margin-top: 2px; font-size: 14px; }
.oc-page-header__actions { display: flex; align-items: center; gap: var(--s-2); margin-left: auto; }
```

- [ ] **Step 2: Add the components to `ui.tsx`**

Append to `frontend/src/components/otclick/ui.tsx`:

```tsx
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
      {items.map((c, i) => (
        <span key={`${c.label}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {i > 0 && <span aria-hidden="true">/</span>}
          {c.href && i < items.length - 1 ? (
            <Link href={c.href}>{c.label}</Link>
          ) : (
            <span aria-current="page">{c.label}</span>
          )}
        </span>
      ))}
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
      <button type="button" className="oc-pager__btn" aria-current="page">
        {page + 1}
      </button>
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
```

- [ ] **Step 3: Give `Toggle`, `TextInput`, `Select` their states**

In `ui.tsx`, add `role="switch"` and `aria-checked={on}` to the `Toggle` button element. Add `className="oc-input"` to the `<input>` in `TextInput` and the `<select>` in `Select`, and append to `globals.css`:

```css
.oc-input {
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.oc-input:focus { border-color: var(--ink); }
.oc-input:disabled { background: var(--bg-deep); color: var(--muted); cursor: not-allowed; }
.oc-input::placeholder { color: var(--muted-2); }
```

- [ ] **Step 4: Add `PageHeader` to all 7 pages**

Each page gets a header as its first rendered element. Exact values:

| File | title | subtitle | crumbs |
|---|---|---|---|
| `dashboard/page.tsx` | `Главная` | `обзор автоотклика и последних событий` | `[{ label: "Главная" }]` |
| `applications/page.tsx` | `Отклики` | `все попытки отклика и их результат` | `[{ label: "Главная", href: "/dashboard" }, { label: "Отклики" }]` |
| `chats/page.tsx` | `Чаты` | `переписка с работодателями` | `[{ label: "Главная", href: "/dashboard" }, { label: "Чаты" }]`, plus a third crumb with the selected employer's name when a chat is open — append `...(selected ? [{ label: selected.employer_name ?? "Диалог" }] : [])`, using whatever the page already calls its selected-chat state |
| `todo/page.tsx` | `Todo` | `что ждёт твоего решения` | `[{ label: "Главная", href: "/dashboard" }, { label: "Todo" }]` |
| `notifications/page.tsx` | `Уведомления` | `события воркера и ИИ-агента` | `[{ label: "Главная", href: "/dashboard" }, { label: "Уведомления" }]` |
| `account/page.tsx` | `Аккаунт` | `подключение hh и настройки` | `[{ label: "Главная", href: "/dashboard" }, { label: "Аккаунт" }]` |
| `billing/page.tsx` | `Подписка` | `план, оплата и история платежей` | `[{ label: "Главная", href: "/dashboard" }, { label: "Аккаунт", href: "/account" }, { label: "Подписка" }]` |

For `dashboard/page.tsx` this means inserting directly above `<HHBanner />`:

```tsx
import { PageHeader } from "@/components/otclick/ui";
// ...
<PageHeader title="Главная" subtitle="обзор автоотклика и последних событий" crumbs={[{ label: "Главная" }]} />
```

Apply the same shape to the other six, using the table's values.

- [ ] **Step 5: Fix the invalid nesting in `account/page.tsx` and delete the dead topbar**

At `frontend/src/app/(app)/account/page.tsx` lines 251 and 261, replace each `<Link href={…}><Btn …>…</Btn></Link>` with the equivalent `<LinkBtn href={…} kind={…} size="sm" icon={…}>…</LinkBtn>`, preserving the existing `href`, `kind`, and `icon` values. Import `LinkBtn` from `@/components/otclick/ui` and drop the now-unused `Link` import if nothing else in the file uses it.

Then:

```bash
git rm frontend/src/components/otclick/topbar.tsx
```

`topbar.tsx` is imported by nothing (verified: `grep -rn "Topbar" frontend/src` returns only its own definition). Its fake search input and unbound `⌘K` hint are superseded by `PageHeader` and Task 5's palette.

- [ ] **Step 6: Verify**

```bash
npx tsc --noEmit && npm run build
```

Expected: exit 0, and no error mentioning `topbar`.

Then `npm run dev` and check every one of the 7 routes: each shows an `<h1>` title, a subtitle, and a breadcrumb trail whose non-final items navigate.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src
git commit -m "feat(ui): page primitives and headings on all app pages

Adds Skeleton, EmptyState, Banner, Breadcrumbs, PageHeader,
SegmentedTabs and Pager, plus focus/disabled states for Toggle,
TextInput and Select. Every authed page now has a heading and a path
back, which none of them had. Fixes two button-inside-anchor nestings
in account/page.tsx and deletes the unreferenced topbar.tsx.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: vitest + labelled sidebar with badge counters

**Files:**
- Modify: `frontend/package.json` (add `vitest` devDependency and a `test` script)
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/lib/nav-counts.ts`
- Create: `frontend/src/lib/nav-counts.test.ts`
- Create: `frontend/src/hooks/useNavCounts.ts`
- Modify: `frontend/src/components/otclick/sidebar.tsx` (full rewrite)
- Modify: `frontend/src/app/globals.css` (sidebar classes + mobile tab-bar labels)
- Modify: `frontend/src/components/otclick/worker-bar.tsx` (remove the `Pro` button, lines 203–222)

**Interfaces:**
- Consumes: `IconBtn`, `Tooltip` from Task 1
- Produces:
  - `NavCounts = { chats: number; todo: number; notifications: number }`
  - `computeNavCounts(input: NavCountsInput): NavCounts`
  - `formatBadge(n: number): string | null` — `null` under 1, `"99+"` above 99
  - `useNavCounts(): NavCounts`
  - CSS classes `.oc-nav-item`, `.oc-nav-item__label`, `.oc-nav-badge`, `.oc-sidebar--collapsed`

- [ ] **Step 1: Install vitest and add the script**

```bash
cd frontend && npm i -D vitest
```

Then add to the `scripts` block of `frontend/package.json`:

```json
"test": "vitest run"
```

- [ ] **Step 2: Create `frontend/vitest.config.ts`**

```ts
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
```

`environment: "node"` is deliberate — these tests cover pure functions only. No jsdom, no testing-library, no DOM assertions on hover styling (which would test the CSS engine, not our code).

- [ ] **Step 3: Write the failing test**

Create `frontend/src/lib/nav-counts.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { computeNavCounts, formatBadge } from "./nav-counts";

describe("formatBadge", () => {
  it("hides a zero badge", () => {
    expect(formatBadge(0)).toBeNull();
  });

  it("hides a negative count", () => {
    expect(formatBadge(-3)).toBeNull();
  });

  it("shows a plain number up to 99", () => {
    expect(formatBadge(1)).toBe("1");
    expect(formatBadge(99)).toBe("99");
  });

  it("caps above 99", () => {
    expect(formatBadge(100)).toBe("99+");
    expect(formatBadge(4210)).toBe("99+");
  });
});

describe("computeNavCounts", () => {
  it("is all zeros for empty input", () => {
    expect(
      computeNavCounts({
        chats: [],
        formDrafts: [],
        recruiterDrafts: [],
        todos: [],
        unreadNotifications: 0,
      }),
    ).toEqual({ chats: 0, todo: 0, notifications: 0 });
  });

  it("sums unread across chats", () => {
    const r = computeNavCounts({
      chats: [{ unread: 2 }, { unread: 0 }, { unread: 5 }],
      formDrafts: [],
      recruiterDrafts: [],
      todos: [],
      unreadNotifications: 0,
    });
    expect(r.chats).toBe(7);
  });

  it("adds the three todo sources together", () => {
    const r = computeNavCounts({
      chats: [],
      formDrafts: [{}, {}],
      recruiterDrafts: [{}],
      todos: [{}, {}, {}],
      unreadNotifications: 0,
    });
    expect(r.todo).toBe(6);
  });

  it("passes the notification count through", () => {
    const r = computeNavCounts({
      chats: [],
      formDrafts: [],
      recruiterDrafts: [],
      todos: [],
      unreadNotifications: 12,
    });
    expect(r.notifications).toBe(12);
  });
});
```

- [ ] **Step 4: Run the test and confirm it fails**

```bash
npx vitest run
```

Expected: FAIL — `Failed to resolve import "./nav-counts"`.

- [ ] **Step 5: Write the implementation**

Create `frontend/src/lib/nav-counts.ts`:

```ts
export type NavCounts = { chats: number; todo: number; notifications: number };

export type NavCountsInput = {
  chats: { unread: number }[];
  formDrafts: unknown[];
  recruiterDrafts: unknown[];
  todos: unknown[];
  unreadNotifications: number;
};

export function computeNavCounts(input: NavCountsInput): NavCounts {
  return {
    chats: input.chats.reduce((sum, c) => sum + (c.unread ?? 0), 0),
    todo: input.formDrafts.length + input.recruiterDrafts.length + input.todos.length,
    notifications: input.unreadNotifications,
  };
}

/** Badge text, or null when the badge should not render at all. */
export function formatBadge(n: number): string | null {
  if (n < 1) return null;
  return n > 99 ? "99+" : String(n);
}
```

- [ ] **Step 6: Run the test and confirm it passes**

```bash
npx vitest run
```

Expected: PASS — 8 tests.

- [ ] **Step 7: Create the `useNavCounts` hook**

Create `frontend/src/hooks/useNavCounts.ts`:

```ts
"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { computeNavCounts, type NavCounts } from "@/lib/nav-counts";
import { useChats } from "@/hooks/useChats";
import { useFormDrafts } from "@/hooks/useFormDrafts";
import { useRecruiter } from "@/hooks/useRecruiter";

const EMPTY: NavCounts = { chats: 0, todo: 0, notifications: 0 };

export function useNavCounts(): NavCounts {
  const supabase = useMemo(() => createClient(), []);
  const { chats } = useChats(false);
  const { drafts: formDrafts } = useFormDrafts();
  const { drafts: recruiterDrafts, todos } = useRecruiter();
  const [unreadNotifications, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { count } = await supabase
        .from("notifications")
        .select("*", { count: "exact", head: true })
        .eq("read", false);
      if (!cancelled) setUnread(count ?? 0);
    }
    load();
    const channel = supabase
      .channel("nav-counts-notifications")
      .on("postgres_changes", { event: "*", schema: "public", table: "notifications" }, load)
      .subscribe();
    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return useMemo(() => {
    if (!chats && !formDrafts && !recruiterDrafts && !todos) return EMPTY;
    return computeNavCounts({
      chats: chats ?? [],
      formDrafts: formDrafts ?? [],
      recruiterDrafts: recruiterDrafts ?? [],
      todos: todos ?? [],
      unreadNotifications,
    });
  }, [chats, formDrafts, recruiterDrafts, todos, unreadNotifications]);
}
```

Before writing this, open `frontend/src/hooks/useChats.ts`, `useFormDrafts.ts`, and `useRecruiter.ts` and confirm the destructured property names (`chats`, `drafts`, `todos`) match what those hooks actually return. If a name differs, use the real one — do not rename the hook.

- [ ] **Step 8: Add the sidebar classes to `globals.css`**

```css
.oc-nav-item {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  height: 44px;
  padding: 0 var(--s-2);
  border-radius: var(--r-md);
  border: none;
  background: transparent;
  color: var(--ink);
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  width: 100%;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.oc-nav-item:hover { background: var(--line-2); }
.oc-nav-item[aria-current="page"] { background: var(--ink); color: #F5F1E6; }
.oc-nav-item__icon { display: grid; place-items: center; width: 24px; flex-shrink: 0; }
.oc-nav-item__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.oc-nav-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--r-pill);
  background: var(--coral);
  color: #fff;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.oc-nav-item[aria-current="page"] .oc-nav-badge { background: var(--yellow); color: var(--ink); }

.oc-sidebar--collapsed .oc-nav-item { justify-content: center; padding: 0; }
.oc-sidebar--collapsed .oc-nav-item__label { display: none; }
.oc-sidebar--collapsed .oc-nav-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 8px;
  height: 8px;
  padding: 0;
  font-size: 0;
}
.oc-sidebar--collapsed .oc-nav-item { position: relative; }
```

And inside the existing `@media (max-width: 720px)` block, replace the `.oc-sidebar-nav` rule's contents so tab-bar items show labels:

```css
  .oc-nav-item {
    flex-direction: column;
    gap: 2px;
    height: auto;
    padding: 6px 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .oc-nav-item__label { display: block; font-size: 11px; }
  .oc-nav-badge {
    position: absolute;
    top: 2px;
    right: 50%;
    margin-right: -18px;
    min-width: 8px;
    height: 8px;
    padding: 0;
    font-size: 0;
  }
  .oc-nav-item { position: relative; }
```

- [ ] **Step 9: Rewrite `sidebar.tsx`**

Replace `frontend/src/components/otclick/sidebar.tsx` entirely:

```tsx
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useNavCounts } from "@/hooks/useNavCounts";
import { formatBadge } from "@/lib/nav-counts";
import { IconBtn, LinkBtn } from "@/components/otclick/ui";
import {
  IHome, IList, IBell, IMail, IDoc, IUser, ISettings, ILogo, ILogout,
  ITelegram, IBolt, IChevRight,
} from "@/components/otclick/icons";

const STORAGE_KEY = "oc-sidebar-collapsed";

type Item = {
  id: string;
  href: string;
  icon: React.ReactNode;
  label: string;
  badge?: "chats" | "todo" | "notifications";
};

const NAV: Item[] = [
  { id: "dashboard", href: "/dashboard", icon: <IHome />, label: "Главная" },
  { id: "applications", href: "/applications", icon: <IList />, label: "Отклики" },
  { id: "chats", href: "/chats", icon: <IMail />, label: "Чаты", badge: "chats" },
  { id: "todo", href: "/todo", icon: <IDoc />, label: "Todo", badge: "todo" },
  { id: "notifications", href: "/notifications", icon: <IBell />, label: "Уведомления", badge: "notifications" },
  { id: "account", href: "/account", icon: <IUser />, label: "Аккаунт" },
];

export default function Sidebar({ email }: { email: string | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();
  const counts = useNavCounts();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/auth");
    router.refresh();
  }

  const initials = email ? email.split(/[@.]/)[0].slice(0, 2).toUpperCase() : "ME";

  return (
    <aside
      className={`oc-sidebar${collapsed ? " oc-sidebar--collapsed" : ""}`}
      style={{
        width: collapsed ? 76 : 216,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "stretch",
        padding: "20px 8px 24px",
        gap: 14,
        position: "sticky",
        top: 16,
        alignSelf: "flex-start",
        height: "calc(100vh - 32px)",
        transition: "width var(--dur) var(--ease)",
      }}
    >
      <div
        className="oc-sidebar-logo"
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 6px 8px" }}
      >
        <Link href="/dashboard" aria-label="otclick — на главную" style={{ display: "inline-flex" }}>
          <ILogo size={36} />
        </Link>
        {!collapsed && <span style={{ fontWeight: 800, fontSize: 17 }}>otclick</span>}
        <span style={{ marginLeft: "auto" }}>
          <IconBtn
            label={collapsed ? "развернуть меню" : "свернуть меню"}
            icon={
              <IChevRight
                size={16}
                style={{ transform: collapsed ? "none" : "rotate(180deg)", transition: "transform var(--dur) var(--ease)" }}
              />
            }
            onClick={toggleCollapsed}
          />
        </span>
      </div>

      <nav
        className="oc-sidebar-nav"
        aria-label="Основная навигация"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--r-lg)",
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          boxShadow: "var(--sh-1)",
        }}
      >
        {NAV.map((it) => {
          const active = pathname.startsWith(it.href);
          const badge = it.badge ? formatBadge(counts[it.badge]) : null;
          return (
            <Link
              key={it.id}
              href={it.href}
              className="oc-nav-item"
              aria-current={active ? "page" : undefined}
              title={collapsed ? it.label : undefined}
            >
              <span className="oc-nav-item__icon">{it.icon}</span>
              <span className="oc-nav-item__label">{it.label}</span>
              {badge && (
                <span className="oc-nav-badge" aria-label={`${counts[it.badge!]} новых`}>
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="oc-sidebar-spacer" style={{ flex: 1 }} />

      <div
        className="oc-sidebar-secondary"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--r-lg)",
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <LinkBtn
          href="/billing"
          kind="yellow"
          size="sm"
          icon={<IBolt size={14} />}
          style={{ justifyContent: "center", marginBottom: 4 }}
        >
          {collapsed ? "" : "Pro"}
        </LinkBtn>
        <a
          href="https://t.me/UnixAuto"
          target="_blank"
          rel="noopener noreferrer"
          className="oc-nav-item"
        >
          <span className="oc-nav-item__icon"><ITelegram /></span>
          <span className="oc-nav-item__label">Поддержка</span>
        </a>
        <Link href="/account" className="oc-nav-item">
          <span className="oc-nav-item__icon"><ISettings /></span>
          <span className="oc-nav-item__label">Настройки</span>
        </Link>
        <button type="button" onClick={signOut} className="oc-nav-item">
          <span className="oc-nav-item__icon"><ILogout /></span>
          <span className="oc-nav-item__label">Выйти</span>
        </button>
      </div>

      <div
        className="oc-sidebar-avatar"
        title={email ?? ""}
        style={{
          width: 44,
          height: 44,
          borderRadius: 14,
          overflow: "hidden",
          background: "linear-gradient(135deg, var(--yellow) 0%, var(--coral) 100%)",
          display: "grid",
          placeItems: "center",
          fontWeight: 700,
          color: "var(--ink)",
          fontSize: 13,
          flexShrink: 0,
        }}
      >
        {initials}
      </div>
    </aside>
  );
}
```

Note: the `Pro` button is conditional on plan state in the spec. That gating needs the billing status query and lands in Task 6 — here it renders unconditionally so this task stays independently shippable.

- [ ] **Step 10: Remove `Pro` from the worker bar**

Delete lines 203–222 of `frontend/src/components/otclick/worker-bar.tsx` (the `<Link href="/billing">…</Link>` block). Remove `Link` and `IBolt` from that file's imports if nothing else uses them.

- [ ] **Step 11: Verify**

```bash
npx vitest run && npx tsc --noEmit && npm run build
```

Expected: 8 tests pass, both other commands exit 0.

Then `npm run dev` and check:
- the sidebar shows six labelled items
- clicking the chevron collapses it to icons and the choice survives a page reload
- the current page's item is dark (`aria-current="page"`)
- if there are unread chats or pending todos, a coral badge shows the count
- `Pro` appears once, in the sidebar footer, and is gone from the worker bar
- at 390px width the bottom tab bar shows labels under the icons

- [ ] **Step 12: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src
git commit -m "feat(nav): labelled collapsible sidebar with badge counters

Adds vitest for pure-logic modules. Sidebar goes from six unlabelled
icons to labelled items with unread counters for chats, todo and
notifications, collapsible to icons with the choice persisted, and
aria-current on the active route. Mobile tab bar gains labels. Pro moves
out of the worker bar into the sidebar footer.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Shareable URL state and full-row clicks on /applications

**Files:**
- Create: `frontend/src/lib/applications-url.ts`
- Create: `frontend/src/lib/applications-url.test.ts`
- Modify: `frontend/src/app/(app)/applications/page.tsx`

**Interfaces:**
- Consumes: `SegmentedTabs`, `Pager`, `Skeleton`, `EmptyState`, `PageHeader` from Task 2
- Produces:
  - `ApplicationsView = { status: string; q: string; page: number }` — `page` is 0-based
  - `APPLICATION_STATUS_IDS: readonly string[]`
  - `DEFAULT_VIEW: ApplicationsView`
  - `parseView(params: URLSearchParams): ApplicationsView`
  - `serializeView(view: ApplicationsView): string` — a query string starting with `?`, or `""` when the view is the default

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/applications-url.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { DEFAULT_VIEW, parseView, serializeView } from "./applications-url";

const parse = (qs: string) => parseView(new URLSearchParams(qs));

describe("parseView", () => {
  it("returns the default view for an empty query", () => {
    expect(parse("")).toEqual(DEFAULT_VIEW);
  });

  it("reads status, query and 1-based page into a 0-based page", () => {
    expect(parse("status=captcha&q=abc&p=3")).toEqual({ status: "captcha", q: "abc", page: 2 });
  });

  it("falls back to 'all' for an unknown status", () => {
    expect(parse("status=nonsense").status).toBe("all");
  });

  it("clamps a non-positive or non-numeric page to the first page", () => {
    expect(parse("p=0").page).toBe(0);
    expect(parse("p=-4").page).toBe(0);
    expect(parse("p=abc").page).toBe(0);
  });

  it("trims the search query", () => {
    expect(parse("q=%20%20yandex%20%20").q).toBe("yandex");
  });
});

describe("serializeView", () => {
  it("serializes the default view to an empty string", () => {
    expect(serializeView(DEFAULT_VIEW)).toBe("");
  });

  it("omits keys that are at their default", () => {
    expect(serializeView({ status: "captcha", q: "", page: 0 })).toBe("?status=captcha");
    expect(serializeView({ status: "all", q: "abc", page: 0 })).toBe("?q=abc");
    expect(serializeView({ status: "all", q: "", page: 2 })).toBe("?p=3");
  });

  it("round-trips a fully populated view", () => {
    const view = { status: "failed", q: "ozon", page: 4 };
    expect(parse(serializeView(view).slice(1))).toEqual(view);
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
npx vitest run src/lib/applications-url.test.ts
```

Expected: FAIL — `Failed to resolve import "./applications-url"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/applications-url.ts`:

```ts
export type ApplicationsView = {
  status: string;
  q: string;
  /** 0-based internally; exposed in the URL as 1-based `p` */
  page: number;
};

export const APPLICATION_STATUS_IDS = [
  "all",
  "sent",
  "form_sent",
  "captcha",
  "failed",
  "skipped",
  "queued",
] as const;

export const DEFAULT_VIEW: ApplicationsView = { status: "all", q: "", page: 0 };

export function parseView(params: URLSearchParams): ApplicationsView {
  const rawStatus = params.get("status") ?? "";
  const status = (APPLICATION_STATUS_IDS as readonly string[]).includes(rawStatus)
    ? rawStatus
    : DEFAULT_VIEW.status;

  const rawPage = Number.parseInt(params.get("p") ?? "", 10);
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage - 1 : DEFAULT_VIEW.page;

  return { status, q: (params.get("q") ?? "").trim(), page };
}

export function serializeView(view: ApplicationsView): string {
  const params = new URLSearchParams();
  if (view.status !== DEFAULT_VIEW.status) params.set("status", view.status);
  if (view.q.trim()) params.set("q", view.q.trim());
  if (view.page > 0) params.set("p", String(view.page + 1));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
npx vitest run
```

Expected: PASS — 8 tests from Task 3 plus 8 here.

- [ ] **Step 5: Drive the page from the URL**

In `frontend/src/app/(app)/applications/page.tsx`:

Replace the three separate state hooks (`page`, `status`, `search` at lines 46–48) with URL-derived state:

```tsx
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { DEFAULT_VIEW, parseView, serializeView, type ApplicationsView } from "@/lib/applications-url";

// inside the component:
const router = useRouter();
const pathname = usePathname();
const searchParams = useSearchParams();
const view = useMemo(() => parseView(new URLSearchParams(searchParams.toString())), [searchParams]);
const { status, page } = view;
const [search, setSearch] = useState(view.q);

const setView = useCallback(
  (patch: Partial<ApplicationsView>) => {
    const next = { ...view, ...patch };
    router.replace(`${pathname}${serializeView(next)}`, { scroll: false });
  },
  [view, pathname, router],
);
```

Keep the existing 300ms debounce, but have it push to the URL instead of local state, and reset the page whenever the query changes:

```tsx
useEffect(() => {
  const t = setTimeout(() => {
    if (search.trim() !== view.q) setView({ q: search.trim(), page: 0 });
  }, 300);
  return () => clearTimeout(t);
}, [search, view.q, setView]);
```

Then in `load`, replace `searchDebounced` with `view.q` and delete the now-unused `searchDebounced` state and its effect. Replace `setStatus(f.id); setPage(0)` with `setView({ status: f.id, page: 0 })`, and `setPage(...)` in the pager with `setView({ page: ... })`.

Because `useSearchParams` requires it, wrap the page's default export in a Suspense boundary:

```tsx
import { Suspense } from "react";

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<Skeleton h={200} />}>
      <ApplicationsView />
    </Suspense>
  );
}
```

and rename the existing component body to `function ApplicationsView()`.

- [ ] **Step 6: Adopt the shared primitives**

In the same file:
- replace the hand-rolled status filter buttons (lines 205–243) with `<SegmentedTabs items={STATUSES.map(s => ({ id: s.id, label: s.label, count: counts[s.id] ?? 0 }))} value={status} onChange={(id) => setView({ status: id, page: 0 })} label="Статус отклика" />`
- replace the pagination block (lines 468–503) with `<Pager page={page} pages={pages} onChange={(p) => setView({ page: p })} />` and delete the local `pagerBtn` helper (lines 509–521)
- replace `<p>загрузка…</p>` (line 272) with `<div style={{ padding: 22 }}><Skeleton h={44} count={6} /></div>`
- replace `<p>откликов нет</p>` (lines 274–276) with:

```tsx
<EmptyState
  icon={<IList size={22} />}
  title={status === "all" && !view.q ? "Откликов пока нет" : "Ничего не найдено"}
  description={
    status === "all" && !view.q
      ? "Запусти автоотклик — результаты появятся здесь в реальном времени."
      : "Попробуй сбросить фильтр или изменить запрос."
  }
  action={
    status === "all" && !view.q
      ? { label: "Настроить фильтры", onClick: openFiltersDrawer }
      : { label: "Сбросить фильтры", onClick: () => setView(DEFAULT_VIEW) }
  }
/>
```

Import `openFiltersDrawer` from `@/components/filters-drawer` and `IList` from `@/components/otclick/icons`.

- [ ] **Step 7: Make the whole row clickable**

Replace the two inline expand buttons (the `тест · N вопр.` and `AI письмо` buttons, lines 322–365) with a single row-level toggle. Add to the row `<div>`:

```tsx
onClick={() => setOpenId(open ? null : a.id)}
role="button"
tabIndex={0}
aria-expanded={open}
onKeyDown={(e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    setOpenId(open ? null : a.id);
  }
}}
style={{ /* existing styles */, cursor: "pointer" }}
```

Keep the hh.ru `<a>` in the last column, and stop it from toggling the row:

```tsx
<a
  href={`https://hh.ru/vacancy/${a.vacancy_id}`}
  target="_blank"
  rel="noreferrer"
  aria-label="открыть вакансию на hh.ru"
  onClick={(e) => e.stopPropagation()}
  style={{ color: "var(--ink)", display: "inline-flex" }}
>
  <IExternal size={15} />
</a>
```

Replace the removed inline buttons with a non-interactive hint in the vacancy cell so users still know a row expands:

```tsx
{(qa.length > 0 || letter) && (
  <div style={{ marginTop: 4, fontSize: 11, fontWeight: 600, color: "var(--coral)" }}>
    {open ? "▾" : "▸"} {qa.length > 0 ? `тест · ${qa.length} вопр.` : "AI письмо"}
  </div>
)}
```

Finally, replace the two `onMouseEnter`/`onMouseLeave` handlers that mutate `style.background` (lines 296–301) with `className="oc-row"` and add to `globals.css`:

```css
.oc-row { transition: background var(--dur) var(--ease); }
.oc-row:hover { background: var(--bg-deep); }
```

- [ ] **Step 8: Verify**

```bash
npx vitest run && npx tsc --noEmit && npm run build
```

Expected: 16 tests pass, both other commands exit 0.

Then `npm run dev` and check:
- clicking a status tab puts `?status=…` in the address bar
- typing in search puts `?q=…` there after ~300ms and resets to page 1
- loading `http://localhost:3000/applications?status=captcha&q=abc&p=2` directly restores that exact tab, query, and page
- the browser back button steps back through filter changes
- clicking anywhere on a row expands it; clicking `↗` opens hh.ru without expanding
- `Tab` reaches a row and `Enter` expands it

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(applications): shareable URL state and full-row expand

Status filter, search query and page move from useState into the URL as
?status=&q=&p=, so a filtered view is a shareable link and the back
button works. Rows expand on click or Enter anywhere in the row instead
of only via a small inline button; the hh.ru link stops propagation.
Adopts SegmentedTabs, Pager, Skeleton and EmptyState.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: ⌘K command palette

**Files:**
- Create: `frontend/src/lib/command-registry.ts`
- Create: `frontend/src/lib/command-registry.test.ts`
- Create: `frontend/src/components/otclick/command-palette.tsx`
- Modify: `frontend/src/app/(app)/layout.tsx` (mount the palette)
- Modify: `frontend/src/app/globals.css` (palette classes)
- Modify: the 7 pages' `PageHeader` calls (add the palette trigger to `actions`)

**Interfaces:**
- Consumes: `KeyHint`, `PageHeader` from Tasks 1–2
- Produces:
  - `Command = { id: string; label: string; group: CommandGroup; keywords?: string; hint?: string }`
  - `CommandGroup = "Навигация" | "Действия" | "Отклики"`
  - `scoreCommand(cmd: Command, query: string): number` — `-1` means no match; higher is better
  - `matchCommands(commands: Command[], query: string): Command[]`
  - `openCommandPalette(): void` — module-level opener, same pattern as the existing `openFiltersDrawer`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/command-registry.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { matchCommands, scoreCommand, type Command } from "./command-registry";

const cmd = (id: string, label: string, keywords?: string): Command => ({
  id,
  label,
  group: "Навигация",
  keywords,
});

const COMMANDS = [
  cmd("dashboard", "Главная"),
  cmd("applications", "Отклики"),
  cmd("chats", "Чаты", "переписка рекрутёр"),
  cmd("start", "Запустить автоотклик", "старт worker"),
];

describe("scoreCommand", () => {
  it("scores an empty query as a neutral match", () => {
    expect(scoreCommand(cmd("a", "Главная"), "")).toBe(0);
  });

  it("ranks a prefix match above a mid-word match", () => {
    const prefix = scoreCommand(cmd("a", "Отклики"), "откл");
    const midWord = scoreCommand(cmd("b", "Переоткрыть"), "откл");
    expect(prefix).toBeGreaterThan(midWord);
  });

  it("ranks a word-start match above a mid-word match", () => {
    const wordStart = scoreCommand(cmd("a", "Запустить автоотклик"), "авто");
    const midWord = scoreCommand(cmd("b", "Переавтоматизация"), "авто");
    expect(wordStart).toBeGreaterThan(midWord);
  });

  it("is case-insensitive", () => {
    expect(scoreCommand(cmd("a", "Главная"), "ГЛАВ")).toBeGreaterThan(-1);
  });

  it("matches on keywords too", () => {
    expect(scoreCommand(cmd("a", "Чаты", "переписка"), "переписка")).toBeGreaterThan(-1);
  });

  it("returns -1 when nothing matches", () => {
    expect(scoreCommand(cmd("a", "Главная"), "zzz")).toBe(-1);
  });
});

describe("matchCommands", () => {
  it("returns every command in original order for an empty query", () => {
    expect(matchCommands(COMMANDS, "").map((c) => c.id)).toEqual([
      "dashboard",
      "applications",
      "chats",
      "start",
    ]);
  });

  it("drops non-matching commands", () => {
    expect(matchCommands(COMMANDS, "чат").map((c) => c.id)).toEqual(["chats"]);
  });

  it("finds a command by its keywords", () => {
    expect(matchCommands(COMMANDS, "worker").map((c) => c.id)).toEqual(["start"]);
  });

  it("ignores surrounding whitespace", () => {
    expect(matchCommands(COMMANDS, "  чат  ").map((c) => c.id)).toEqual(["chats"]);
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
npx vitest run src/lib/command-registry.test.ts
```

Expected: FAIL — `Failed to resolve import "./command-registry"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/command-registry.ts`:

```ts
export type CommandGroup = "Навигация" | "Действия" | "Отклики";

export type Command = {
  id: string;
  label: string;
  group: CommandGroup;
  keywords?: string;
  hint?: string;
};

/** -1 = no match. Higher is a better match. */
export function scoreCommand(cmd: Command, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 0;

  const haystack = `${cmd.label} ${cmd.keywords ?? ""}`.toLowerCase();
  const idx = haystack.indexOf(q);
  if (idx < 0) return -1;
  if (idx === 0) return 3;
  if (haystack[idx - 1] === " ") return 2;
  return 1;
}

export function matchCommands(commands: Command[], query: string): Command[] {
  return commands
    .map((cmd, i) => ({ cmd, i, score: scoreCommand(cmd, query) }))
    .filter((e) => e.score >= 0)
    .sort((a, b) => (b.score - a.score) || (a.i - b.i))
    .map((e) => e.cmd);
}
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
npx vitest run
```

Expected: PASS — 26 tests total.

- [ ] **Step 5: Add palette styles to `globals.css`**

```css
.oc-palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(26, 27, 31, .35);
  z-index: var(--z-modal);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 12vh 16px 16px;
  animation: oc-fadein var(--dur) var(--ease);
}
.oc-palette {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--sh-2);
  width: 100%;
  max-width: 560px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 70vh;
}
.oc-palette__input {
  border: none;
  outline: none;
  padding: var(--s-4);
  font-family: inherit;
  font-size: 16px;
  color: var(--ink);
  background: transparent;
  border-bottom: 1px solid var(--line-2);
}
.oc-palette__list { overflow-y: auto; padding: var(--s-1); margin: 0; list-style: none; }
.oc-palette__group {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--muted);
  font-weight: 700;
  padding: var(--s-2) var(--s-3) var(--s-1);
}
.oc-palette__item {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  color: var(--ink);
  text-align: left;
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-sm);
  cursor: pointer;
}
.oc-palette__item[aria-selected="true"] { background: var(--bg-deep); }
.oc-palette__hint { margin-left: auto; font-size: 11px; color: var(--muted); }
.oc-palette__empty { padding: var(--s-5); text-align: center; color: var(--muted); font-size: 13px; }
```

- [ ] **Step 6: Build the palette component**

Create `frontend/src/components/otclick/command-palette.tsx`. It follows the exact opener pattern already used by `frontend/src/components/filters-drawer.tsx` — open that file first and mirror how `openFiltersDrawer` publishes its event, so both overlays behave the same way.

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import { matchCommands, type Command, type CommandGroup } from "@/lib/command-registry";
import { openFiltersDrawer } from "@/components/filters-drawer";
import { pushToast } from "@/components/toaster";
import type { Application } from "@/lib/types";

const EVENT = "oc:open-command-palette";

export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(EVENT));
}

const GROUP_ORDER: CommandGroup[] = ["Навигация", "Действия", "Отклики"];

export default function CommandPalette() {
  const router = useRouter();
  const qc = useQueryClient();
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [recent, setRecent] = useState<Application[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setCursor(0);
    if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
  }, []);

  // open via the module-level opener or ⌘K / Ctrl+K
  useEffect(() => {
    function show() {
      triggerRef.current = document.activeElement;
      setOpen(true);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        show();
      }
    }
    window.addEventListener(EVENT, show);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(EVENT, show);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    supabase
      .from("applications")
      .select("id,vacancy_id,employer_id,status,created_at")
      .order("created_at", { ascending: false })
      .limit(20)
      .then(({ data }) => setRecent((data ?? []) as Application[]));
  }, [open, supabase]);

  const commands: (Command & { run: () => void })[] = useMemo(() => {
    const nav = [
      ["/dashboard", "Главная", "дашборд обзор"],
      ["/applications", "Отклики", "заявки вакансии"],
      ["/chats", "Чаты", "переписка рекрутёр сообщения"],
      ["/todo", "Todo", "задачи черновики анкеты"],
      ["/notifications", "Уведомления", "события"],
      ["/account", "Аккаунт", "настройки профиль hh"],
      ["/billing", "Подписка", "оплата тариф pro billing"],
    ].map(([href, label, keywords]) => ({
      id: `nav:${href}`,
      label,
      group: "Навигация" as const,
      keywords,
      run: () => router.push(href),
    }));

    const post = (path: string, ok: string) => async () => {
      try {
        await apiFetch(path, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["worker-status"] });
        pushToast({ kind: "success", title: ok });
      } catch (e) {
        pushToast({ kind: "error", title: e instanceof Error ? e.message : "не удалось" });
      }
    };

    const actions: (Command & { run: () => void })[] = [
      { id: "act:start", label: "Запустить автоотклик", group: "Действия", keywords: "старт worker run", run: post("/api/worker/start", "worker запущен") },
      { id: "act:stop", label: "Остановить автоотклик", group: "Действия", keywords: "стоп worker pause", run: post("/api/worker/stop", "worker остановлен") },
      { id: "act:agent-start", label: "Запустить ИИ-агента", group: "Действия", keywords: "агент ai старт", run: post("/api/worker/agent/start", "ИИ-агент запущен") },
      { id: "act:agent-stop", label: "Остановить ИИ-агента", group: "Действия", keywords: "агент ai стоп", run: post("/api/worker/agent/stop", "ИИ-агент остановлен") },
      { id: "act:filters", label: "Открыть фильтры", group: "Действия", keywords: "поиск настройки вакансий", run: openFiltersDrawer },
      { id: "act:sync", label: "Синхронизировать резюме", group: "Действия", keywords: "резюме hh обновить", run: post("/api/resumes/sync", "резюме синхронизированы") },
      { id: "act:refresh", label: "Обновить статус воркера", group: "Действия", keywords: "refresh статус", run: () => { qc.invalidateQueries({ queryKey: ["worker-status"] }); } },
      { id: "act:signout", label: "Выйти", group: "Действия", keywords: "logout выход", run: async () => { await supabase.auth.signOut(); router.push("/auth"); } },
    ];

    const apps = recent.map((a) => ({
      id: `app:${a.id}`,
      label: `vacancy ${a.vacancy_id}`,
      group: "Отклики" as const,
      keywords: `${a.employer_id ?? ""} ${a.status}`,
      hint: "открыть на hh.ru",
      run: () => window.open(`https://hh.ru/vacancy/${a.vacancy_id}`, "_blank", "noopener"),
    }));

    return [...nav, ...actions, ...apps];
  }, [router, qc, supabase, recent]);

  const results = useMemo(() => matchCommands(commands, query) as typeof commands, [commands, query]);

  useEffect(() => setCursor(0), [query]);

  if (!open) return null;

  function runAt(i: number) {
    const c = results[i];
    if (!c) return;
    close();
    c.run();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(results.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); runAt(cursor); }
  }

  let flat = -1;

  return (
    <div
      className="oc-palette-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}
    >
      <div className="oc-palette" role="dialog" aria-modal="true" aria-label="Командная палитра" onKeyDown={onKeyDown}>
        <input
          ref={inputRef}
          className="oc-palette__input"
          placeholder="куда пойдём или что сделаем?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Поиск команды"
        />
        {results.length === 0 ? (
          <div className="oc-palette__empty">ничего не нашлось</div>
        ) : (
          <ul className="oc-palette__list">
            {GROUP_ORDER.map((group) => {
              const inGroup = results.filter((c) => c.group === group);
              if (inGroup.length === 0) return null;
              return (
                <li key={group}>
                  <div className="oc-palette__group">{group}</div>
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {inGroup.map((c) => {
                      flat += 1;
                      const i = flat;
                      return (
                        <li key={c.id}>
                          <button
                            type="button"
                            className="oc-palette__item"
                            aria-selected={i === cursor}
                            onMouseEnter={() => setCursor(i)}
                            onClick={() => runAt(i)}
                          >
                            {c.label}
                            {c.hint && <span className="oc-palette__hint">{c.hint}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Mount it and add the trigger**

In `frontend/src/app/(app)/layout.tsx`, add `import CommandPalette from "@/components/otclick/command-palette";` and render `<CommandPalette />` next to `<FiltersDrawer />` and `<CaptchaModal />`.

Then give every `PageHeader` a trigger via its `actions` prop:

```tsx
actions={
  <Btn kind="ghost" size="sm" icon={<ISearch size={15} />} onClick={openCommandPalette}>
    поиск <KeyHint>⌘K</KeyHint>
  </Btn>
}
```

- [ ] **Step 8: Verify**

```bash
npx vitest run && npx tsc --noEmit && npm run build
```

Expected: 26 tests pass, both other commands exit 0.

Then `npm run dev` and check:
- `⌘K` (and `Ctrl+K`) opens the palette from any of the 7 pages
- typing `чат` narrows to Чаты; `worker` finds the start/stop actions
- `↓`/`↑` moves the highlight, `Enter` runs the highlighted item
- `Esc` closes and focus returns to the trigger button
- clicking the backdrop closes it, clicking inside does not
- the `поиск ⌘K` button in the header opens the same palette

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(nav): working ⌘K command palette

Adds a dependency-free palette covering the 7 routes, worker and agent
start/stop, filters, resume sync and sign-out, plus the 20 most recent
applications. Replaces the ⌘K hint that was rendered but bound to
nothing. Keyboard-driven with a focus trap and focus restore.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Clickable dashboard, restructured worker bar, todo tabs

**Files:**
- Modify: `frontend/src/app/(app)/dashboard/limit-ring.tsx`, `recent-applications-card.tsx`, `notifications-card.tsx`, `resumes-card.tsx`
- Modify: `frontend/src/components/otclick/worker-bar.tsx`
- Modify: `frontend/src/app/(app)/todo/page.tsx`
- Modify: `frontend/src/components/otclick/hh-banner.tsx`
- Create: `frontend/src/components/otclick/captcha-banner.tsx`
- Modify: `frontend/src/components/captcha-modal.tsx` (export a module-level opener if it has none)
- Modify: `frontend/src/components/otclick/sidebar.tsx` (gate the `Pro` button on plan state)

**Interfaces:**
- Consumes: `Card` (`interactive`), `Skeleton`, `EmptyState`, `Banner`, `SegmentedTabs`, `IconBtn`, `Tooltip` from Tasks 1–2
- Produces: no new exported API

- [ ] **Step 1: Make the dashboard cards clickable and give them real states**

`limit-ring.tsx` — wrap in `<Card tone="light" interactive={{ href: "/billing" }} …>` and add a hint line under the existing subtitle:

```tsx
<div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
  нужно больше — открыть тарифы →
</div>
```

`recent-applications-card.tsx`:
- replace `<p>загрузка…</p>` (line 126) with `<Skeleton h={60} count={4} />`
- replace the `пусто — запусти worker сверху` paragraph (lines 128–130) with:

```tsx
<EmptyState
  icon={<IList size={22} />}
  title="Откликов пока нет"
  description="Настрой фильтры и запусти автоотклик — первые отклики появятся здесь."
  action={{ label: "Настроить фильтры", onClick: openFiltersDrawer }}
/>
```

- replace the `все отклики` `<Link><span>` (lines 104–120) with `<LinkBtn href="/applications" kind="primary" size="sm" icon={<IPlus size={13} />}>все отклики</LinkBtn>`

`notifications-card.tsx`:
- replace `<p>загрузка…</p>` (line 136) with `<Skeleton h={40} count={4} />`
- replace `<p>пусто</p>` (line 138) with `<EmptyState icon={<IBell size={22} />} title="Тихо" description="Здесь появятся события воркера и ИИ-агента." />`
- turn each notification row into a link to `/notifications` by wrapping the row content in `<Link href="/notifications" style={{ textDecoration: "none", color: "inherit" }}>`

`resumes-card.tsx`:
- replace `<p>загрузка…</p>` (line 70) with `<Skeleton h={62} count={2} />`
- replace the `резюме не найдены` paragraph (lines 72–74) with `<EmptyState icon={<IDoc size={22} />} title="Резюме не найдены" description="Синхронизируй резюме с hh, чтобы автоотклик знал, чем откликаться." action={{ label: "Синхронизировать", onClick: sync }} />`

- [ ] **Step 2: Restructure the worker bar**

In `frontend/src/components/otclick/worker-bar.tsx`:

Wrap the status region so screen readers announce transitions — change the outer container's first child group to:

```tsx
<div role="status" aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 10 }}>
```

Make the metrics meaningful:

```tsx
<Link href="/applications" style={{ textDecoration: "none", color: "inherit", display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
  <span style={{ color: "#ffffff80" }}>сегодня</span>
  <span className="mono" style={{ fontWeight: 600 }}>
    {status?.today_count ?? 0}
    <span style={{ color: "#ffffff50" }}>/{status?.daily_limit ?? "—"}</span>
  </span>
</Link>
```

and wrap the queue metric in `<Tooltip text="вакансии, найденные фильтрами и ждущие отклика">…</Tooltip>`.

Collapse the trailing controls to two primary buttons plus an overflow. Keep the existing автоотклик and ИИ-агент buttons exactly as they are, and replace the standalone Фильтры and Обновить buttons with:

```tsx
const [menuOpen, setMenuOpen] = useState(false);
// ...
<div style={{ position: "relative" }}>
  <IconBtn label="ещё" icon={<span style={{ fontSize: 18, lineHeight: 1 }}>⋯</span>} onDark onClick={() => setMenuOpen((v) => !v)} />
  {menuOpen && (
    <div
      style={{
        position: "absolute",
        right: 0,
        top: "calc(100% + 8px)",
        background: "var(--surface)",
        color: "var(--ink)",
        borderRadius: "var(--r-md)",
        boxShadow: "var(--sh-2)",
        padding: 6,
        display: "flex",
        flexDirection: "column",
        gap: 2,
        zIndex: "var(--z-nav)",
        minWidth: 180,
      }}
      onMouseLeave={() => setMenuOpen(false)}
    >
      <button type="button" className="oc-nav-item" onClick={() => { setMenuOpen(false); openFiltersDrawer(); }}>
        <span className="oc-nav-item__icon"><IFilter size={16} /></span>
        <span className="oc-nav-item__label">Фильтры</span>
      </button>
      <button type="button" className="oc-nav-item" onClick={() => { setMenuOpen(false); refresh(); }}>
        <span className="oc-nav-item__icon"><IRefresh size={16} /></span>
        <span className="oc-nav-item__label">Обновить</span>
      </button>
    </div>
  )}
</div>
```

- [ ] **Step 3: Give `/todo` tabs and anchors**

In `frontend/src/app/(app)/todo/page.tsx`, add a `SegmentedTabs` under the `PageHeader` that scrolls to the matching section, and give each `<section>` an `id`:

```tsx
const SECTIONS = [
  { id: "forms", label: "Анкеты" },
  { id: "drafts", label: "Черновики" },
  { id: "tasks", label: "Задачи" },
] as const;

const [active, setActive] = useState<string>("forms");

useEffect(() => {
  const hash = window.location.hash.replace("#", "");
  if (SECTIONS.some((s) => s.id === hash)) setActive(hash);
}, []);

function goto(id: string) {
  setActive(id);
  window.history.replaceState(null, "", `#${id}`);
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

<SegmentedTabs
  items={[
    { id: "forms", label: "Анкеты", count: formDrafts.length },
    { id: "drafts", label: "Черновики", count: drafts.length },
    { id: "tasks", label: "Задачи", count: todos.length },
  ]}
  value={active}
  onChange={goto}
  label="Разделы Todo"
/>
```

Then add `id="forms"`, `id="drafts"`, `id="tasks"` to the three existing `<section>` elements (lines 295, 314, 324) and replace the three `Нет …` paragraphs with `EmptyState`s:

```tsx
// forms
<EmptyState icon={<IDoc size={22} />} title="Анкет нет" description="Когда вакансия попросит пройти тест, ИИ заполнит его и покажет здесь на проверку." />
// drafts
<EmptyState icon={<IMail size={22} />} title="Черновиков нет" description="Если ИИ не уверен в ответе рекрутёру, черновик появится здесь." action={{ label: "Открыть чаты", href: "/chats" }} />
// tasks
<EmptyState icon={<ICheck size={22} />} title="Задач нет" description="ИИ-агент создаёт задачи, когда рекрутёр просит что-то сделать вне переписки." />
```

Also replace the `Загрузка…` block (line 292) with `<Skeleton h={120} count={3} />`.

- [ ] **Step 4: Move `hh-banner` onto the shared `Banner`**

Rewrite the render of `frontend/src/components/otclick/hh-banner.tsx` to use the shared component, replacing its bespoke markup:

```tsx
if (kind === "warn") {
  return (
    <Banner
      tone="warn"
      title="токен скоро истечёт"
      description="мы обновим его автоматически"
    />
  );
}
return (
  <Banner
    tone="err"
    title="нет связи с hh"
    description="переподключи аккаунт, чтобы продолжить"
    action={{ label: "Переподключить", href: "/onboarding" }}
  />
);
```

Replace the loading placeholder (lines 56–67) with `<Skeleton h={50} radius="var(--r-md)" />`.

- [ ] **Step 5: Surface a pending captcha as a banner, not only a modal**

A captcha currently appears solely as `CaptchaModal`. If the user dismisses it or arrives later, nothing on the page says the worker is stuck. Add to `frontend/src/app/(app)/dashboard/page.tsx`, directly below `<HHBanner />`, a new client component `frontend/src/components/otclick/captcha-banner.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { Banner } from "@/components/otclick/ui";
import { openCaptchaModal } from "@/components/captcha-modal";

type Pending = { items: { id: string }[] };

export default function CaptchaBanner() {
  const { data } = useQuery({
    queryKey: ["captcha-pending"],
    queryFn: () => apiFetch<Pending>("/api/captcha/pending"),
    refetchInterval: 15000,
  });
  const n = data?.items?.length ?? 0;
  if (n === 0) return null;
  return (
    <Banner
      tone="err"
      title={n === 1 ? "hh просит пройти капчу" : `hh просит пройти капчу · ${n}`}
      description="автоотклик на паузе, пока капча не решена"
      action={{ label: "Решить", onClick: openCaptchaModal }}
    />
  );
}
```

Open `frontend/src/components/captcha-modal.tsx` first: reuse its existing module-level opener if it already exports one, and only add an `openCaptchaModal` export (mirroring `openFiltersDrawer`) if it does not. Match the real response shape of `/api/captcha/pending` rather than assuming `items`.

No separate sidebar badge is needed: the worker already inserts a `captcha` row into `notifications`, so the Уведомления badge from Task 3 already counts it.

- [ ] **Step 6: Gate the `Pro` button on plan state**

In `sidebar.tsx`, fetch billing status and hide `Pro` when the plan is active:

```tsx
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

const { data: billing } = useQuery({
  queryKey: ["billing-status"],
  queryFn: () => apiFetch<{ plan: string }>("/api/billing/status"),
  staleTime: 60_000,
});
const showPro = billing?.plan !== "active";
```

and wrap the `LinkBtn` in `{showPro && ( … )}`.

Open `frontend/src/app/(app)/billing/page.tsx` first and reuse whatever response shape it already expects from `/api/billing/status` — do not invent a field name.

- [ ] **Step 7: Verify**

```bash
npx vitest run && npx tsc --noEmit && npm run build
```

Expected: 26 tests pass, both other commands exit 0.

Then `npm run dev` and check:
- every dashboard card either navigates on click or contains a button that does
- loading the dashboard on a throttled connection shows shimmer blocks, not the word `загрузка…`
- an account with no applications sees an empty state with a working `Настроить фильтры` button
- the worker bar shows two buttons plus `⋯`, and the overflow opens Фильтры and Обновить
- `сегодня N/M` navigates to `/applications`
- `/todo#drafts` opens with the Черновики tab active and scrolled to that section

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): clickable dashboard, worker-bar overflow, todo tabs

Dashboard cards become real navigation targets and get shimmer loading
plus empty states with a next action instead of dead-end text. Worker bar
collapses five buttons to two plus an overflow, announces state changes
via role=status, and turns its metrics into links. Todo gains tabs with
counts and #forms/#drafts/#tasks anchors. hh-banner moves onto the shared
Banner. Pro hides when a plan is active.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Mobile and accessibility pass

**Files:**
- Modify: `frontend/src/app/globals.css` (responsive block)
- Modify: whichever files the checks below turn up

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: no new API

- [ ] **Step 1: Make the sidebar collapse state mobile-proof**

In the `@media (max-width: 720px)` block of `globals.css`, force the sidebar back to tab-bar geometry regardless of the collapsed class, since the desktop width is inline:

```css
  .oc-sidebar,
  .oc-sidebar--collapsed {
    width: auto !important;
  }
  .oc-sidebar--collapsed .oc-nav-item { justify-content: center; padding: 6px 4px; }
  .oc-sidebar--collapsed .oc-nav-item__label { display: block; }
```

Also hide the collapse toggle on mobile by adding `.oc-sidebar-logo { display: none !important; }` — it is already in the existing hide list, so verify rather than duplicate it.

- [ ] **Step 2: Check every page at 390px**

```bash
npm run dev
```

In the browser devtools device toolbar at 390×844, load each of `/dashboard`, `/applications`, `/chats`, `/todo`, `/notifications`, `/account`, `/billing` and confirm for each:
- no horizontal page scrollbar (wide tables scroll inside their own `.oc-scroll-x` container — that is correct and already implemented)
- the bottom tab bar shows six labelled items and does not overlap page content
- the worker bar wraps to at most two rows
- the `PageHeader` title and its actions do not collide

Fix any page that fails by adding a rule to the responsive block. Do not change desktop layout to fix a mobile problem.

- [ ] **Step 3: Keyboard sweep**

On each of the 7 pages, press `Tab` from the top of the document to the bottom and confirm:
- every stop shows the dark 2px focus ring
- focus order follows visual order
- no stop is invisible or clipped
- the palette (`⌘K`) traps focus while open and returns it on `Esc`

- [ ] **Step 4: Accessible-name sweep**

```bash
grep -rn "IconBtn" frontend/src | grep -v "label="
```

Expected: no output. Any hit is an `IconBtn` missing its required `label` — TypeScript should already have caught it, so a hit means a raw `<button>` mimicking an icon button; give it an `aria-label`.

```bash
grep -rnE "<button[^>]*>\s*<I[A-Z]" frontend/src/app frontend/src/components
```

Every match must have an `aria-label` on the same element. Fix any that do not.

- [ ] **Step 5: Confirm reduced motion still covers everything**

```bash
grep -n "transition:" frontend/src/app/globals.css | grep -v "var(--dur)"
```

Expected: no output. Any transition not expressed in `var(--dur)` escapes the existing `prefers-reduced-motion` override — rewrite it to use the token.

- [ ] **Step 6: Final verification**

```bash
npx vitest run && npx tsc --noEmit && npm run build
```

Expected: 26 tests pass, both other commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "fix(ui): mobile layout and accessibility pass

Sidebar collapse state no longer leaks into the mobile tab bar. Verifies
all 7 pages at 390px without horizontal overflow, every interactive
element reachable by keyboard with a visible focus ring, every icon-only
control named, and every transition expressed via --dur so the existing
prefers-reduced-motion override keeps covering it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Deferred — not in this plan

`/applications` still renders `vacancy 118322` and a raw `employer_id` as its primary column, because the `applications` table stores no `vacancy_title` or `employer_name`. This is a backend gap (migration + a write in `backend/app/services/apply.py`, which already fetches the full vacancy payload and discards those fields), deliberately excluded from this frontend plan and recorded in the spec's "Known limitation" section. The `EmptyState` and row layout built in Task 4 will display real titles with no further frontend work once those columns exist.
