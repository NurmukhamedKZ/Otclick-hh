"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, LinkBtn, Skeleton, Tag, Toggle } from "@/components/otclick/ui";
import { IArrow, IRefresh, ISearch, ITrash } from "@/components/otclick/icons";
import styles from "./page.module.css";

type QueryPair = { key: string; value: string };

type Preview = {
  raw_url: string;
  host: string;
  path: string;
  query_pairs: QueryPair[];
  parameters: Record<string, string[]>;
  unsupported_parameters: string[];
};

type SourceStats = {
  new: number;
  duplicate: number;
  hard_filtered: number;
  score_error: number;
};

type SearchSource = {
  id: string;
  resume_id: string | null;
  name: string;
  source_type: "search_url" | "hh_autosearch" | "recommendations";
  raw_url: string | null;
  query_pairs: QueryPair[];
  stats: SourceStats;
  enabled: boolean;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
};

function formatTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function SearchSourcesPage() {
  const [sources, setSources] = useState<SearchSource[] | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<SearchSource[]>("/api/search-sources");
      setSources(data);
      setError(null);
    } catch (err) {
      setSources([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить источники");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function previewUrl() {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiFetch<Preview>("/api/search-sources/preview-url", {
        method: "POST",
        body: JSON.stringify({ url: url.trim() }),
      });
      setPreview(data);
      if (!name.trim()) {
        const text = data.parameters.text?.[0]?.trim();
        setName(text || "HH поиск");
      }
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "Не удалось разобрать HH URL");
    } finally {
      setBusy(false);
    }
  }

  async function createSource() {
    if (!preview || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch<SearchSource>("/api/search-sources", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), url: preview.raw_url, enabled: true }),
      });
      setName("");
      setUrl("");
      setPreview(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить источник");
    } finally {
      setBusy(false);
    }
  }

  async function setEnabled(source: SearchSource, enabled: boolean) {
    setBusyId(source.id);
    setError(null);
    try {
      const next = await apiFetch<SearchSource>(`/api/search-sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      });
      setSources((current) => (current ?? []).map((item) => (item.id === source.id ? next : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить источник");
    } finally {
      setBusyId(null);
    }
  }

  async function removeSource(source: SearchSource) {
    if (!window.confirm(`Удалить источник «${source.name}»? Найденные вакансии останутся в backlog.`)) return;
    setBusyId(source.id);
    setError(null);
    try {
      await apiFetch(`/api/search-sources/${source.id}`, { method: "DELETE" });
      setSources((current) => (current ?? []).filter((item) => item.id !== source.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить источник");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className={styles.page}>
      <Card>
        <div className={styles.header}>
          <div>
            <div className={styles.headerTitle}>Источники вакансий</div>
            <div className={styles.headerSub}>
              Сейчас — HH search URL. Автопоиски HH будут импортироваться через web-session после live-проверки.
            </div>
          </div>
          <div className={styles.spacer} />
          <LinkBtn href="/vacancies" kind="ghost" size="sm" icon={<IArrow size={14} style={{ transform: "rotate(180deg)" }} />}>
            вакансии
          </LinkBtn>
          <Btn kind="ghost" size="sm" icon={<IRefresh size={14} />} onClick={load}>
            обновить
          </Btn>
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 750, marginBottom: 12 }}>Добавить HH поиск</div>
        <div className={styles.formGrid}>
          <label>
            <span className={styles.fieldLabel}>Название</span>
            <input
              className={styles.input}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Например: CIO Москва"
              maxLength={120}
            />
          </label>
          <label>
            <span className={styles.fieldLabel}>URL поиска hh.ru</span>
            <input
              className={styles.input}
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setPreview(null);
              }}
              placeholder="https://hh.ru/search/vacancy?..."
              inputMode="url"
            />
          </label>
        </div>

        <div className={styles.actions}>
          <Btn kind="soft" size="sm" loading={busy} disabled={!url.trim()} onClick={previewUrl}>
            проверить URL
          </Btn>
          <Btn kind="primary" size="sm" loading={busy} disabled={!preview || !name.trim()} onClick={createSource}>
            сохранить источник
          </Btn>
        </div>

        {preview && (
          <div className={styles.preview}>
            <div className={styles.previewRow}>
              <div className={styles.previewKey}>HH</div>
              <div>{preview.host}{preview.path}</div>
            </div>
            <div className={styles.previewRow}>
              <div className={styles.previewKey}>Параметры</div>
              <div className={styles.params}>
                {preview.query_pairs.map((pair, index) => (
                  <Tag key={`${pair.key}-${pair.value}-${index}`} tone="neutral">
                    {pair.key}={pair.value}
                  </Tag>
                ))}
              </div>
            </div>
            {preview.unsupported_parameters.length > 0 && (
              <div className={styles.warning}>
                Неизвестные параметры не удаляются: {preview.unsupported_parameters.join(", ")}. Они будут передаваться HH как в исходном URL.
              </div>
            )}
          </div>
        )}
        {error && <div className={styles.error}>{error}</div>}
      </Card>

      <div>
        <div style={{ fontWeight: 750, marginBottom: 10 }}>Сохранённые источники</div>
        {sources === null ? (
          <Card><Skeleton h={90} count={3} /></Card>
        ) : sources.length === 0 ? (
          <Card>
            <EmptyState
              icon={<ISearch size={22} />}
              title="Источников пока нет"
              description="Вставь URL готовой поисковой выдачи HH и проверь параметры перед сохранением."
            />
          </Card>
        ) : (
          <div className={styles.list}>
            {sources.map((source) => {
              const checked = formatTime(source.last_checked_at);
              const success = formatTime(source.last_success_at);
              return (
                <Card key={source.id} className={styles.sourceCard}>
                  <div className={styles.sourceHead}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className={styles.sourceName}>{source.name}</div>
                      {source.raw_url && <div className={styles.sourceUrl}>{source.raw_url}</div>}
                    </div>
                    <Toggle
                      on={source.enabled}
                      disabled={busyId === source.id}
                      onChange={(enabled) => setEnabled(source, enabled)}
                    />
                  </div>

                  <div className={styles.sourceMeta}>
                    <Tag tone={source.enabled ? "ok" : "neutral"}>{source.enabled ? "включён" : "выключен"}</Tag>
                    <Tag tone="neutral">{source.source_type}</Tag>
                    {checked && <Tag tone="neutral">проверка {checked}</Tag>}
                    {success && <Tag tone="ok">успех {success}</Tag>}
                    {source.last_error && <Tag tone="err">ошибка</Tag>}
                  </div>

                  <div className={styles.sourceMeta}>
                    <Tag tone="ok">новых {source.stats?.new ?? 0}</Tag>
                    <Tag tone="neutral">дубликатов {source.stats?.duplicate ?? 0}</Tag>
                    <Tag tone="neutral">hard filter {source.stats?.hard_filtered ?? 0}</Tag>
                    <Tag tone={(source.stats?.score_error ?? 0) > 0 ? "err" : "neutral"}>
                      score errors {source.stats?.score_error ?? 0}
                    </Tag>
                  </div>

                  {source.last_error && <div className={styles.error}>{source.last_error}</div>}

                  <div className={styles.sourceActions}>
                    {source.raw_url && (
                      <a
                        href={source.raw_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="oc-btn oc-btn--ghost oc-btn--sm"
                      >
                        открыть HH
                      </a>
                    )}
                    <Btn
                      kind="ghost"
                      size="sm"
                      icon={<ITrash size={14} />}
                      disabled={busyId === source.id}
                      onClick={() => removeSource(source)}
                    >
                      удалить
                    </Btn>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
