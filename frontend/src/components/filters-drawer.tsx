"use client";

import { useEffect, useState } from "react";
import { useFilters } from "@/hooks/useFilters";
import { useBlacklist } from "@/hooks/useBlacklist";
import { Btn, Card, Toggle } from "@/components/otclick/ui";
import { IClose, IFilter, IPlus, ITrash } from "@/components/otclick/icons";
import type { Filter, FilterCreate, Resume, ResumesList } from "@/lib/types";
import { apiFetch } from "@/lib/api";
import { pushToast } from "@/components/toaster";

const EVENT = "filters-drawer";

export function openFiltersDrawer() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { open: true } }));
}

const AREAS = [
  { value: "", label: "любое" },
  { value: "40", label: "Казахстан" },
  { value: "113", label: "Россия" },
];

const EXPERIENCE = [
  { value: "", label: "не важно" },
  { value: "noExperience", label: "без опыта" },
  { value: "between1And3", label: "1–3 года" },
  { value: "between3And6", label: "3–6 лет" },
  { value: "moreThan6", label: "> 6 лет" },
];

// hh deprecated `schedule`/`employment` in favour of these.
const WORK_FORMAT = [
  { value: "", label: "любой" },
  { value: "ON_SITE", label: "в офисе" },
  { value: "REMOTE", label: "удалённо" },
  { value: "HYBRID", label: "гибрид" },
  { value: "FIELD_WORK", label: "разъездная" },
];

const EMPLOYMENT_FORM = [
  { value: "", label: "любая" },
  { value: "FULL", label: "полная" },
  { value: "PART", label: "частичная" },
  { value: "PROJECT", label: "проект" },
  { value: "SIDE_JOB", label: "подработка" },
];

const SEARCH_FIELD = [
  { value: "name", label: "в названии вакансии" },
  { value: "", label: "везде (название, компания, описание)" },
];

const PERIOD = [
  { value: "7", label: "за неделю" },
  { value: "14", label: "за 2 недели" },
  { value: "30", label: "за месяц" },
  { value: "", label: "за всё время" },
];

const WORK_FORMAT_LABEL: Record<string, string> = Object.fromEntries(
  WORK_FORMAT.filter((w) => w.value).map((w) => [w.value, w.label]),
);
const EXPERIENCE_LABEL: Record<string, string> = Object.fromEntries(
  EXPERIENCE.filter((e) => e.value).map((e) => [e.value, e.label]),
);

type Tab = "filters" | "blacklist";

function filterTitle(f: Filter, resumes: Resume[] = []): string {
  if (f.name) return f.name;
  if (f.text) return f.text;
  const resume = resumes.find((r) => r.id === f.resume_id);
  if (resume?.title) return resume.title;
  const parts: string[] = [];
  if (f.area === 40) parts.push("KZ");
  if (f.area === 113) parts.push("RU");
  return parts.length ? parts.join(" · ") : "пустой фильтр";
}

export default function FiltersDrawer() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("filters");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [creating, setCreating] = useState(false);
  const [newResumeId, setNewResumeId] = useState("");

  const { items: filters, error: filterError, create, update, remove } = useFilters();
  const { items: blacklist, error: blacklistError, add: addBl, remove: removeBl } = useBlacklist();
  const [newCompany, setNewCompany] = useState("");
  const [newCompanyId, setNewCompanyId] = useState("");

  useEffect(() => {
    function onToggle(e: Event) {
      const detail = (e as CustomEvent<{ open: boolean }>).detail;
      setOpen(!!detail?.open);
    }
    window.addEventListener(EVENT, onToggle);
    return () => window.removeEventListener(EVENT, onToggle);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    if (open) {
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
  }, [open]);

  useEffect(() => {
    if (open) {
      apiFetch<ResumesList>("/api/resumes")
        .then((d) => setResumes(d.items))
        .catch(() => undefined);
    }
  }, [open]);

  useEffect(() => {
    if (filters && filters.length > 0 && !selectedId) {
      setSelectedId(filters[0].id);
    }
    if (filters && selectedId && !filters.find((f) => f.id === selectedId)) {
      setSelectedId(filters[0]?.id ?? null);
    }
  }, [filters, selectedId]);

  async function handleCreate() {
    if (resumes.length === 0) {
      pushToast({ kind: "error", title: "Сначала синхронизируй резюме" });
      return;
    }
    if (!newResumeId) {
      pushToast({ kind: "error", title: "Выбери резюме для фильтра" });
      return;
    }
    setCreating(true);
    try {
      const row = await create({ enabled: true, resume_id: newResumeId });
      setSelectedId(row.id);
      setNewResumeId("");
      pushToast({ kind: "success", title: "фильтр создан" });
    } catch (e) {
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "create failed" });
    } finally {
      setCreating(false);
    }
  }

  const selected = filters?.find((f) => f.id === selectedId) ?? null;

  return (
    <>
      <div
        onClick={() => setOpen(false)}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.3)",
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: "opacity .25s",
          zIndex: 50,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(640px, 96vw)",
          background: "var(--bg)",
          transform: open ? "translateX(0)" : "translateX(100%)",
          transition: "transform .3s cubic-bezier(.2,.8,.2,1)",
          zIndex: 51,
          padding: 24,
          overflow: "auto",
          boxShadow: "-20px 0 60px rgba(0,0,0,0.15)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 18,
          }}
        >
          <div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>Фильтры и чёрный список</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              Управляй, на какие вакансии бот откликается
            </div>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="close"
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              border: "none",
              background: "var(--surface)",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
              color: "var(--ink)",
            }}
          >
            <IClose size={18} />
          </button>
        </div>

        <div
          style={{
            display: "inline-flex",
            background: "var(--surface)",
            padding: 6,
            borderRadius: 999,
            marginBottom: 18,
          }}
        >
          {(["filters", "blacklist"] as const).map((id) => (
            <button
              type="button"
              key={id}
              onClick={() => setTab(id)}
              style={{
                border: "none",
                padding: "7px 16px",
                borderRadius: 999,
                fontSize: 13,
                fontWeight: 600,
                background: tab === id ? "var(--ink)" : "transparent",
                color: tab === id ? "#F5F1E6" : "var(--ink)",
                cursor: "pointer",
              }}
            >
              {id === "filters" ? "Фильтры" : "Чёрный список"}
            </button>
          ))}
        </div>

        {tab === "filters" && (
          <>
            {filterError && (
              <p style={{ color: "var(--err)", fontSize: 13, marginBottom: 10 }}>{filterError}</p>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
              {filters === null && (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>загрузка…</div>
              )}
              {filters?.map((f) => (
                <div
                  key={f.id}
                  onClick={() => setSelectedId(f.id)}
                  style={{
                    cursor: "pointer",
                    padding: "14px 16px",
                    borderRadius: 14,
                    background: "var(--surface)",
                    color: "var(--ink)",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    outline: selectedId === f.id ? "2px solid var(--yellow)" : "none",
                    outlineOffset: -2,
                  }}
                >
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 12,
                      flexShrink: 0,
                      background: f.enabled ? "var(--yellow)" : "var(--bg-deep)",
                      color: "var(--ink)",
                      display: "grid",
                      placeItems: "center",
                    }}
                  >
                    <IFilter size={15} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 700,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      «{filterTitle(f, resumes)}»
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--muted)",
                        marginTop: 2,
                      }}
                    >
                      {[
                        f.area === 40 ? "KZ" : f.area === 113 ? "RU" : null,
                        f.work_format ? WORK_FORMAT_LABEL[f.work_format] : null,
                        f.experience ? EXPERIENCE_LABEL[f.experience] : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </div>
                  </div>
                  <div onClick={(e) => e.stopPropagation()}>
                    <Toggle
                      on={f.enabled}
                      onChange={async (next) => {
                        await update(f.id, { enabled: next });
                      }}
                    />
                  </div>
                </div>
              ))}
              <div
                style={{
                  border: "1.5px dashed var(--muted-2)",
                  borderRadius: 14,
                  padding: 14,
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <select
                  value={newResumeId}
                  onChange={(e) => setNewResumeId(e.target.value)}
                  disabled={resumes.length === 0}
                  style={{ ...inputStyle, flex: "1 1 180px", width: "auto" }}
                >
                  <option value="">
                    {resumes.length === 0 ? "— нет резюме —" : "— выбери резюме —"}
                  </option>
                  {resumes.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.title ?? r.hh_resume_id}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleCreate}
                  disabled={creating || !newResumeId}
                  style={{
                    border: "none",
                    background: newResumeId ? "var(--ink)" : "var(--bg-deep)",
                    borderRadius: 12,
                    padding: "10px 16px",
                    color: newResumeId ? "#F5F1E6" : "var(--muted)",
                    fontWeight: 600,
                    fontSize: 13,
                    cursor: newResumeId ? "pointer" : "not-allowed",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontFamily: "inherit",
                    flexShrink: 0,
                  }}
                >
                  <IPlus size={14} /> {creating ? "создаём…" : "новый фильтр"}
                </button>
              </div>
            </div>

            {selected && (
              <FilterEditor
                key={selected.id}
                filter={selected}
                resumes={resumes}
                onUpdate={(patch) => update(selected.id, patch)}
                onDelete={async () => {
                  if (!confirm("Удалить фильтр?")) return;
                  await remove(selected.id);
                }}
              />
            )}
          </>
        )}

        {tab === "blacklist" && (
          <Card tone="light">
            <div style={{ fontSize: 14, color: "var(--muted)", marginBottom: 14 }}>
              Бот не будет откликаться в эти компании, даже если вакансия подходит по фильтру.
            </div>
            {blacklistError && (
              <p style={{ color: "var(--err)", fontSize: 13, marginBottom: 10 }}>{blacklistError}</p>
            )}
            <div
              style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 18 }}
            >
              {blacklist === null && (
                <span style={{ color: "var(--muted)", fontSize: 13 }}>загрузка…</span>
              )}
              {blacklist?.length === 0 && (
                <span style={{ color: "var(--muted)", fontSize: 13 }}>список пуст</span>
              )}
              {blacklist?.map((b) => (
                <span
                  key={b.id}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "7px 12px",
                    background: "var(--bg-deep)",
                    borderRadius: 999,
                    fontSize: 13,
                  }}
                >
                  {b.employer_name ?? `id ${b.employer_id}`}
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm("Убрать из чёрного списка?")) removeBl(b.id);
                    }}
                    aria-label="remove"
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "var(--muted)",
                      display: "inline-flex",
                      padding: 0,
                      cursor: "pointer",
                    }}
                  >
                    <IClose size={12} />
                  </button>
                </span>
              ))}
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!newCompanyId.trim()) return;
                try {
                  await addBl({
                    employer_id: newCompanyId.trim(),
                    employer_name: newCompany.trim() || null,
                    reason: "manual",
                  });
                  setNewCompany("");
                  setNewCompanyId("");
                } catch (err) {
                  pushToast({
                    kind: "error",
                    title: err instanceof Error ? err.message : "add failed",
                  });
                }
              }}
              style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
            >
              <input
                value={newCompanyId}
                onChange={(e) => setNewCompanyId(e.target.value)}
                placeholder="employer_id"
                style={{
                  flex: "1 1 120px",
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: "1px solid var(--line)",
                  background: "#fff",
                  outline: "none",
                  fontFamily: "inherit",
                  fontSize: 14,
                }}
              />
              <input
                value={newCompany}
                onChange={(e) => setNewCompany(e.target.value)}
                placeholder="название (опц.)"
                style={{
                  flex: "2 1 180px",
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: "1px solid var(--line)",
                  background: "#fff",
                  outline: "none",
                  fontFamily: "inherit",
                  fontSize: 14,
                }}
              />
              <Btn type="submit" kind="primary" icon={<IPlus size={14} />}>
                добавить
              </Btn>
            </form>
          </Card>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 24,
            padding: "16px 0",
            borderTop: "1px solid var(--line)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            изменения сохраняются автоматически
          </span>
          <Btn kind="primary" onClick={() => setOpen(false)}>
            готово
          </Btn>
        </div>
      </div>
    </>
  );
}

function FilterEditor({
  filter,
  resumes,
  onUpdate,
  onDelete,
}: {
  filter: Filter;
  resumes: Resume[];
  onUpdate: (patch: Partial<FilterCreate>) => Promise<unknown>;
  onDelete: () => Promise<void>;
}) {
  const [name, setName] = useState(filter.name ?? "");
  const [editingName, setEditingName] = useState(false);
  const [text, setText] = useState(filter.text ?? "");
  const [excludedText, setExcludedText] = useState(filter.excluded_text ?? "");
  const [area, setArea] = useState(filter.area ? String(filter.area) : "");
  const [workFormat, setWorkFormat] = useState(filter.work_format ?? "");
  const [employmentForm, setEmploymentForm] = useState(filter.employment_form ?? "");
  const [searchField, setSearchField] = useState(filter.search_field ?? "");
  const [period, setPeriod] = useState(filter.period ? String(filter.period) : "");
  const [experience, setExperience] = useState(filter.experience ?? "");
  const [resumeId, setResumeId] = useState(filter.resume_id ?? "");

  async function commit(patch: Partial<FilterCreate>) {
    try {
      await onUpdate(patch);
    } catch (e) {
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "save failed" });
    }
  }

  const expPills = EXPERIENCE.filter((e) => e.value);

  return (
    <Card tone="light" style={{ padding: 20 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div style={{ flex: 1, minWidth: 0, marginRight: 12 }}>
          {editingName ? (
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => {
                setEditingName(false);
                if (name !== (filter.name ?? "")) commit({ name: name.trim() || null });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  setName(filter.name ?? "");
                  setEditingName(false);
                }
              }}
              placeholder={filterTitle(filter, resumes)}
              style={{
                ...inputStyle,
                fontSize: 16,
                fontWeight: 700,
                padding: "6px 10px",
              }}
            />
          ) : (
            <button
              type="button"
              onClick={() => {
                setName(filter.name ?? "");
                setEditingName(true);
              }}
              title="Нажми, чтобы переименовать"
              style={{
                border: "none",
                background: "transparent",
                padding: 0,
                fontSize: 16,
                fontWeight: 700,
                color: "var(--ink)",
                cursor: "text",
                fontFamily: "inherit",
                textAlign: "left",
                maxWidth: "100%",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                display: "block",
              }}
            >
              «{filterTitle(filter, resumes)}»
            </button>
          )}
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            нажми на название, чтобы переименовать
          </div>
        </div>
        <Btn kind="ghost" size="sm" icon={<ITrash size={13} />} onClick={onDelete}>
          удалить
        </Btn>
      </div>

      <EditorField
        label="позиция"
        hint="Короткий запрос = больше вакансий. Лучше 1-2 слова (название должности). Список через запятую сужает выдачу почти до нуля."
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => text !== (filter.text ?? "") && commit({ text: text || null })}
          placeholder="Python разработчик"
          style={inputStyle}
        />
      </EditorField>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))", gap: 14 }}>
        <EditorField label="где искать" hint="«везде» ловит вакансии, где слово мелькнуло в описании">
          <select
            value={searchField}
            onChange={(e) => {
              setSearchField(e.target.value);
              commit({ search_field: e.target.value || null });
            }}
            style={inputStyle}
          >
            {SEARCH_FIELD.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </EditorField>
        <EditorField label="свежесть" hint="чем короче период, тем меньше запросов к hh">
          <select
            value={period}
            onChange={(e) => {
              setPeriod(e.target.value);
              commit({ period: e.target.value ? Number(e.target.value) : null });
            }}
            style={inputStyle}
          >
            {PERIOD.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </EditorField>
      </div>

      <EditorField
        label="исключить слова"
        hint="Через запятую. hh уберёт из выдачи вакансии с этими словами."
      >
        <input
          value={excludedText}
          onChange={(e) => setExcludedText(e.target.value)}
          onBlur={() =>
            excludedText !== (filter.excluded_text ?? "") &&
            commit({ excluded_text: excludedText.trim() || null })
          }
          placeholder="продажи, стажёр, 1С"
          style={inputStyle}
        />
      </EditorField>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))", gap: 14 }}>
        <EditorField label="регион">
          <select
            value={area}
            onChange={(e) => {
              setArea(e.target.value);
              commit({ area: e.target.value ? Number(e.target.value) : null });
            }}
            style={inputStyle}
          >
            {AREAS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </EditorField>
        <EditorField label="формат работы">
          <select
            value={workFormat}
            onChange={(e) => {
              setWorkFormat(e.target.value);
              commit({ work_format: e.target.value || null });
            }}
            style={inputStyle}
          >
            {WORK_FORMAT.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </EditorField>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))", gap: 14 }}>
        <EditorField label="занятость">
          <select
            value={employmentForm}
            onChange={(e) => {
              setEmploymentForm(e.target.value);
              commit({ employment_form: e.target.value || null });
            }}
            style={inputStyle}
          >
            {EMPLOYMENT_FORM.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </EditorField>
        <EditorField label="резюме *">
          <select
            value={resumeId}
            onChange={(e) => {
              if (!e.target.value) return;
              setResumeId(e.target.value);
              commit({ resume_id: e.target.value });
            }}
            style={inputStyle}
          >
            {resumes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title ?? r.hh_resume_id}
              </option>
            ))}
          </select>
        </EditorField>
      </div>

      <div style={{ marginTop: 6, marginBottom: 14 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            marginBottom: 8,
          }}
        >
          опыт работы
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => {
              setExperience("");
              commit({ experience: null });
            }}
            style={pillStyle(experience === "")}
          >
            не важно
          </button>
          {expPills.map((e) => (
            <button
              type="button"
              key={e.value}
              onClick={() => {
                setExperience(e.value);
                commit({ experience: e.value });
              }}
              style={pillStyle(experience === e.value)}
            >
              {e.label}
            </button>
          ))}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 4,
          paddingTop: 14,
          borderTop: "1px solid var(--line)",
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>AI-фильтр релевантности</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            Бот пропустит вакансии, которые ИИ счёл нерелевантными резюме
          </div>
        </div>
        <Toggle
          on={filter.ai_filter_enabled}
          onChange={(next) => commit({ ai_filter_enabled: next })}
        />
      </div>
    </Card>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 14px",
  borderRadius: 12,
  border: "1px solid var(--line)",
  background: "#fff",
  outline: "none",
  fontFamily: "inherit",
  fontSize: 14,
  color: "var(--ink)",
};

function EditorField({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
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
      {children}
      {hint && (
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function pillStyle(active: boolean): React.CSSProperties {
  return {
    padding: "8px 14px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    border: "none",
    background: active ? "var(--ink)" : "var(--bg-deep)",
    color: active ? "#F5F1E6" : "var(--ink)",
    cursor: "pointer",
    fontFamily: "inherit",
  };
}
