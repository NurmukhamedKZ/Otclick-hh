-- ============================================================
-- 026_free_plan.sql — убрать триал, ввести бесплатный тир.
--
-- Раньше новый пользователь получал plan='trial' на 7 дней, после чего доступ
-- пропадал совсем. Теперь триала нет: новый пользователь сразу 'free' и
-- работает бессрочно, но в ручном режиме и с суммарным лимитом откликов
-- (services/plan.limits_for + worker/limiter). Ворота "пустить/не пустить"
-- заменены на "какие лимиты применить".
--
-- trial_ends НЕ удаляем — историческая колонка, ничего не стоит, и по ней
-- читается старая когорта.
-- Run AFTER 025_atomic_counters_and_retention.sql
-- ============================================================

-- Существующие триальщики (и активные, и истёкшие) → free. Их уже отправленные
-- отклики лежат в applications, поэтому часть из них сразу окажется за
-- суммарным лимитом — это ожидаемо и правильно.
UPDATE public.profiles SET plan = 'free' WHERE plan = 'trial';

-- Тот же SECURITY DEFINER + search_path, что в 024, только без триала.
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  INSERT INTO public.profiles (id, plan)
  VALUES (new.id, 'free')
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$;

-- Дефолт колонки (001_init) тоже указывал на триал — строка, вставленная в
-- обход триггера, снова получила бы 'trial'.
ALTER TABLE public.profiles ALTER COLUMN plan SET DEFAULT 'free';

-- Суммарный лимит free считается запросом
--   applications WHERE user_id = ? AND status IN ('sent','form_sent')
-- на каждой итерации цикла воркера; индекс под него уже есть —
-- idx_applications_user_status (002_indexes.sql).
