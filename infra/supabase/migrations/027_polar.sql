-- ============================================================
-- 027_polar.sql — переход с CloudPayments на Polar.sh.
--
-- `payments` не трогаем: provider='polar', provider_payment_id = Polar order id,
-- UNIQUE на нём уже есть, идемпотентность вебхука работает как была.
--
-- profiles.cp_subscription_id ОСТАВЛЯЕМ — ничего не стоит, по ней читается
-- история платежей CloudPayments.
-- Run AFTER 026_free_plan.sql
-- ============================================================

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS polar_customer_id text,
  ADD COLUMN IF NOT EXISTS polar_subscription_id text;

-- 001_init задал payments.provider DEFAULT 'cloudpayments'. Код всегда пишет
-- provider явно, но дефолт, помечающий новые платежи мёртвым провайдером, —
-- ловушка для следующего, кто вставит строку руками.
ALTER TABLE public.payments ALTER COLUMN provider SET DEFAULT 'polar';

-- Колонки пишет только сервисная роль (вебхук). 024 уже отобрал UPDATE у
-- anon/authenticated целиком, так что отдельный REVOKE не нужен — но новые
-- колонки не должны случайно попасть в GRANT из 024, а он поимённый. Проверка:
-- authenticated может писать только onboarded и timezone.
