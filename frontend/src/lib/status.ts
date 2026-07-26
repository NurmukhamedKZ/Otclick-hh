export const STATUS_COLOR: Record<string, string> = {
  queued: "bg-gray-100 text-gray-700",
  sent: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-700",
  captcha: "bg-yellow-100 text-yellow-800",
  skipped: "bg-gray-100 text-gray-500",
  form_required: "bg-blue-100 text-blue-800",
  vacancy_gone: "bg-gray-100 text-gray-500",
  test_solved: "bg-purple-100 text-purple-800",
};

export const STATUS_LABEL: Record<string, string> = {
  queued: "в очереди",
  sent: "отправлен",
  failed: "ошибка",
  captcha: "капча",
  skipped: "пропущен",
  form_required: "форма",
  vacancy_gone: "удалена",
  test_solved: "тест решён",
  form_pending: "форма на подтверждении",
  form_sent: "форма отправлена",
  resume_missing: "резюме недоступно",
  limit_day: "лимит дня",
  token_dead: "нужно переподключить hh",
  account_banned: "аккаунт заблокирован",
};
