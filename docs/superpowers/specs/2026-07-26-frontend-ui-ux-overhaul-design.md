# Frontend UI/UX Overhaul — Design

**Date:** 2026-07-26
**Scope:** `frontend/src` — design system, 7 authed app pages, navigation, ⌘K command palette
**Out of scope:** landing (`app/page.tsx`), `app/auth/`, `app/onboarding/`, dark mode, new backend endpoints, Tailwind-utility migration

## Problem

The app works but does not read as a designed product:

1. **No component layer.** `ui.tsx` is 342 lines (Card, Btn, Tag, StatusDot, Toggle, Field, TextInput, Select). The other ~9.4k lines of TSX are inline `style={{}}`. Inline styles cannot express `:hover`, `:focus-visible`, `:active`, `[disabled]`, or media queries — so the app has almost none of them. Hover is faked in three places with `onMouseEnter`/`onMouseLeave` handlers that mutate `style.background` directly.
2. **No scale discipline.** Seven ad-hoc border radii (8/10/12/14/16/18/22), spacing values picked per-file, no shadow or motion tokens, `z-index` hardcoded per component (sidebar `50`, modals inline).
3. **Navigation is not discoverable.** The sidebar is six unlabelled icons with only a `title` attribute. No counters, no breadcrumbs, no page titles, no "what do I do next". `components/otclick/topbar.tsx` exists but is imported by nothing — `app/(app)/layout.tsx` renders only `WorkerBar` — so **no app page has a heading at all**. The dead `Topbar` also contains the non-functional search input and the unbound `⌘K` hint.
4. **Dead affordances.** Dashboard cards look like cards but are not clickable. `LimitRing`, `NotificationsCard`, `ResumesCard`, `RecentApplicationsCard` are inert.
5. **Loading and empty states are bare text.** `загрузка…`, `откликов нет`, `Нет черновиков.`, `Нет задач.` — an empty screen is a dead end with no next action.
6. **Invalid interactive DOM.** `<Link><Btn>…</Btn></Link>` nests a `<button>` inside an `<a>` → two tab stops, broken keyboard activation. Two occurrences are in scope (`account/page.tsx:251, 261`); five more are in the out-of-scope landing and one in the dead `Topbar`.
7. **`/applications` state is unshareable.** Status filter, search query, and page number live in `useState`. No URL reflection, so no shareable link and the browser back button does nothing.

## Decisions

**Keep the visual language.** The cream `#EFEAE0` + yellow `#F5CB3D` / coral `#E96B58` editorial palette, Manrope + Instrument Serif + JetBrains Mono stay. It is recognizable and already matches the landing page, which is out of scope — changing the app palette would split the product in two.

**CSS classes + tokens in `globals.css`, not Tailwind utilities, not shadcn/ui.** Components emit semantic classes (`.oc-btn`, `.oc-card`, `.oc-nav-item`); all cosmetics and interactive states live in `globals.css`. Rationale: the codebase already uses exactly this pattern (`.oc-sidebar`, `.oc-scroll-x`, `.oc-chat-card`, `.oc-auth-grid`), so this is continuation rather than migration. A Tailwind-utility rewrite would touch every one of ~30 TSX files with a diff too large to review safely; shadcn/ui adds radix-ui + cmdk + cva + tailwind-merge and deletes `ui.tsx` entirely — the largest scope and risk for a project whose primitives mostly already exist. Accepted cost: two edit sites (TSX for structure, CSS for appearance).

## Architecture

### 1. Token layer — `globals.css` (152 → ~700 lines)

Colors unchanged. Added, because their absence is what makes the UI drift:

```css
:root {
  /* spacing */
  --s-1: 6px;  --s-2: 10px; --s-3: 14px;
  --s-4: 18px; --s-5: 22px; --s-6: 28px;
  /* radii */
  --r-sm: 10px; --r-md: 16px; --r-lg: 22px; --r-pill: 999px;
  /* elevation */
  --sh-1: 0 1px 0 var(--line-2);
  --sh-2: 0 8px 24px -12px rgba(26,27,31,.28);
  /* motion */
  --dur: 140ms; --ease: cubic-bezier(.2,.8,.2,1);
  /* focus */
  --focus-ring: 2px solid var(--ink);
  --focus-offset: 2px;
  /* layers */
  --z-drawer: 40; --z-nav: 50; --z-modal: 60; --z-toast: 70;
}
```

The existing `@media (prefers-reduced-motion: reduce)` block already neutralizes animation and transition durations globally; every new transition must therefore be expressed via `--dur` so that block keeps covering it.

### 2. Component layer — `ui.tsx` (342 → ~750 lines) + `.oc-*` classes

Existing components keep their public props (so no call-site churn) and switch from inline style objects to classes:

| Component | Change |
|---|---|
| `Btn` | emits `.oc-btn .oc-btn--{kind} .oc-btn--{size}`; gains `:hover` (1px lift + `--sh-2`), `:active` (settle), `:focus-visible`, `[disabled]`; new `loading` prop → inline spinner + `aria-busy` |
| `Card` | new `interactive` prop → renders as a link/button, hover lift, focus ring, correct cursor |
| `Tag`, `StatusDot`, `Toggle` | `:focus-visible`; `Toggle` gets `role="switch"` + `aria-checked` |
| `TextInput`, `Select` | `:focus`, `:invalid`, `:disabled`, explicit placeholder color |

New components:

- **`LinkBtn`** — a `next/link` styled as a button. Replaces all six `<Link><Btn>` nestings. This is a correctness fix, not decoration.
- **`IconBtn`** — square icon-only button; `aria-label` is a **required** prop, paired with `Tooltip`.
- **`Skeleton`** — shimmer block; replaces every text loading placeholder.
- **`EmptyState`** — icon + title + description + primary CTA. Every empty state gets an action, because a dead end is the current bug.
- **`PageHeader`** — title + subtitle + `Breadcrumbs` + actions slot. Applied to all 7 pages, none of which currently has a heading. Supersedes the dead `topbar.tsx`, which is deleted as part of this step (its only content — a fake search input, an unbound `⌘K` hint, and a `Pro` button — is either reimplemented properly or dropped).
- **`Breadcrumbs`** — `Главная / <section>` (+ `/ <entity>` on a chat).
- **`SegmentedTabs`** — the status filter row in `/applications`, currently hand-rolled inline buttons.
- **`Pager`** — extracted from the local `pagerBtn()` helper in `applications/page.tsx`.
- **`Tooltip`** — CSS-only via `data-tip` attribute. No new dependency.
- **`Banner`** — tone `ok`/`warn`/`err` + optional action. Absorbs `hh-banner` and carries captcha / limit warnings.
- **`KeyHint`** — styled `<kbd>`, used by the ⌘K trigger and the palette.

`Skeleton` and `EmptyState` replace: `загрузка…` and `откликов нет` (`applications`), `Загрузка…`, `Нет тестов на проверку.`, `Нет черновиков.`, `Нет задач.` (`todo`), plus the equivalents in `chats`, `notifications`, `account`, `billing`, and the dashboard cards.

### 3. Navigation

**Sidebar** (`components/otclick/sidebar.tsx`): 76px icons-only → **216px with labels**, collapsible back to 76px. Collapsed state persists in `localStorage` (`oc-sidebar-collapsed`); collapsed items show `Tooltip`. Active item gains `aria-current="page"` alongside the existing `pathname.startsWith()` check.

**Badge counters** on Чаты, Todo, Уведомления. Served by one new hook `hooks/useNavCounts.ts` — no new backend endpoint:
- Чаты: sum of `unread` over `/api/chats` (the field already exists in `useChats`' `Chat` type)
- Todo: `form_drafts.length + drafts.length + todos.length` from the existing `useFormDrafts` / `useRecruiter` hooks
- Уведомления: unread count from the `notifications` table, refreshed by the existing Realtime subscription in `RealtimeBridge`

**Mobile** (`@media (max-width: 720px)`): the tab bar keeps its fixed-bottom layout but gains 11px labels under each icon; badges render as dots. Currently it is six unlabelled icons.

**`PageHeader` is added to all 7 pages** and carries a real ⌘K palette trigger in its actions slot.

### 4. ⌘K command palette — `components/otclick/command-palette.tsx`

Hand-rolled, zero new dependencies. Sources:
- 7 route navigations
- actions: start/stop автоотклик, start/stop ИИ-агент, open filters drawer, sync resumes, refresh worker status, sign out
- the 20 most recent applications → open on hh.ru

Behavior: `⌘K` / `Ctrl+K` opens, `Esc` closes, `↑`/`↓` moves, `Enter` executes, substring match over labels. `role="dialog" aria-modal="true"`, focus trap, focus restored to the trigger on close. Registered once in `app/(app)/layout.tsx` next to the other global overlays (`FiltersDrawer`, `CaptchaModal`, `Toaster`) using `--z-modal`.

### 5. Clickability and deep links

| Now | After |
|---|---|
| dashboard cards are inert rectangles | RecentApplications → `/applications`, Notifications → `/notifications`, Resumes → `/account`, LimitRing → `/billing` |
| only the `↗` icon in an application row is clickable | the whole row toggles the detail panel; `↗` stays a separate hh.ru link |
| `/applications` filter/search/page are `useState` only | reflected in the URL as `?status=&q=&p=` via `useSearchParams` + `router.replace` — links are shareable and the back button works |
| `/todo` has 3 unanchored sections | `SegmentedTabs` with counts + `#forms`, `#drafts`, `#tasks` anchors |
| `Pro` sits in the worker-bar, unrelated to worker state | moves to the sidebar footer, rendered only when there is no active plan |
| no way back from `/billing`, `/account` | `Breadcrumbs` in `PageHeader` |
| captcha appears as a silent modal | sidebar badge + `Banner` with a CTA, in addition to the modal |
| `/chats?n=` deep link exists | kept, plus `Главная / Чаты / <employer>` breadcrumb |

### 6. Worker bar

Five buttons in one row → two primary (автоотклик, ИИ-агент) plus a `⋯` overflow menu (фильтры, обновить); `Pro` leaves for the sidebar footer. Metrics become links: `сегодня 12/50` → `/applications`, `в очереди` → `Tooltip` explaining what the queue is. The state region gets `role="status"` so a screen reader announces transitions. On mobile it wraps to two deliberate rows instead of the current reflow.

### 7. Accessibility baseline

- `:focus-visible` on every interactive element, via the `--focus-ring` token
- `aria-label` required on every icon-only control (enforced by `IconBtn`'s prop type)
- `aria-current="page"` on the active nav item
- `role="status"` on the worker state, `role="switch"` on `Toggle`, `role="dialog" aria-modal` + focus trap on the palette
- `prefers-reduced-motion` already handled globally; new transitions must use `--dur` to stay covered

## Known limitation — out of scope, needs a separate task

`/applications` renders `vacancy 118322` and a raw `employer_id` as the primary column, because the `applications` table stores neither `vacancy_title` nor `employer_name` (`form_drafts` does store them). No amount of redesign fixes this — the main column stays a meaningless ID. The fix is a migration adding both columns plus writing them in `services/apply.py`, which already fetches the full vacancy payload and simply discards those fields. Backend work, deliberately excluded from this design. Recorded here so it is not mistaken for a UI defect.

## Implementation order and verification

1. **Tokens + `ui.tsx` rewrite** → `npm run build` clean, `npx tsc --noEmit` clean, dashboard renders unchanged apart from new hover/focus states
2. **Sidebar + `PageHeader` + `Breadcrumbs` + `useNavCounts`** → all 7 pages have a title and a path back; badge counts match the row counts on `/todo` and `/notifications`
3. **⌘K palette** → opens on `⌘K` and `Ctrl+K`, every command executes, `Esc` restores focus to the trigger
4. **Clickability + URL state** → `/applications?status=captcha&q=abc&p=2` restores that exact view on load; back button steps through filter changes
5. **Worker bar + mobile** → at 390px width no horizontal page scroll on any of the 7 pages
6. **a11y pass** → Tab traverses every page with a visible focus ring at each stop; no icon-only control lacks `aria-label`

Each step must leave `npm run build` and `npx tsc --noEmit` clean before the next begins.
