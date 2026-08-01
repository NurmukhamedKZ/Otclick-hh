# Task 0 — спайк: доступно ли резюме с hh

Дата проверки: 2026-08-01. Пользователь: `c6881321-734f-4b40-9cff-ef7665720405`.

С хоста запускать с `SUPABASE_URL=http://localhost:54321` — в `.env` лежит
in-network `http://kong:8000`, вне контейнера он не резолвится.

## GET /resumes/{id}

```
keys: ['_progress', 'access', 'actions', 'age', 'alternate_url', 'area', 'birth_date',
 'blocked', 'business_trip_readiness', 'can_publish_or_update', 'certificate',
 'citizenship', 'contact', 'created_at', 'download', 'driver_license_types',
 'education', 'employment', 'employment_form', 'employments', 'experience',
 'experience_group_by_company', 'finished', 'first_name', 'gender', 'has_vehicle',
 'hidden_fields', 'id', 'language', 'last_name']

download: {"pdf": {"url": "https://api.hh.ru/resumes/<id>/download/<name>.pdf?type=pdf"},
           "rtf": {"url": "…?type=rtf"}}

contact: [{"value": {"formatted": "+7 701 118-70-21"}, "type": {"id": "cell"},
           "comment": "Telegram: …\nLinkedln: …\nGithub: …"},
          {"type": {"id": "email"}, "value": "…"}]

summary head:
Желаемая должность: AI-инженер
ФИО: Әшекей Нұрмұхамед
Возраст: 23
Пол: Мужской
Город: Алматы
Гражданство: Казахстан
```

## Скачивание PDF

```
200 application/pdf; charset=utf-8 46584 байт
magic: b'%PDF-1.5'
```

Обычный `requests.get(url, headers={"Authorization": f"Bearer <token>"})` работает.

## ВЕРДИКТ

hh отдаёт и резюме, и PDF — идём по основному плану. Фолбэк с ручной загрузкой
PDF не нужен.

## Побочные находки

- Ссылки на Telegram/LinkedIn/GitHub лежат не отдельными полями, а в
  `contact[].comment` свободным текстом. В `facts` (Task 1) их не тащим; если
  формы часто спрашивают LinkedIn — распарсить комментарий регуляркой отдельной
  задачей.
- `_resume_summary` печатает `Релокация` сырым словарём (`{'type': {...}}`).
  Существующий дефект `form_filler`, к этой фиче отношения не имеет — не трогаю.
