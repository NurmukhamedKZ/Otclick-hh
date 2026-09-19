#!/bin/sh
set -eu

replace_token() {
  token="$1"
  value="$2"
  [ -n "$value" ] || {
    echo "frontend runtime config is missing value for $token" >&2
    exit 1
  }

  escaped="$(printf '%s' "$value" | sed 's/[\\&|]/\\&/g')"
  files="$(grep -RIl -- "$token" /app/.next 2>/dev/null || true)"
  if [ -n "$files" ]; then
    # shellcheck disable=SC2086
    sed -i "s|$token|$escaped|g" $files
  fi
}

# URL placeholders must themselves be valid URLs because Supabase validates the
# public URL while Next.js prerenders pages during the GitHub Actions build.
replace_token 'https://otclick-runtime-supabase.invalid' "${NEXT_PUBLIC_SUPABASE_URL:?NEXT_PUBLIC_SUPABASE_URL is required}"
replace_token '__OTCLICK_SUPABASE_ANON_KEY__' "${NEXT_PUBLIC_SUPABASE_ANON_KEY:?NEXT_PUBLIC_SUPABASE_ANON_KEY is required}"
replace_token 'https://otclick-runtime-api.invalid' "${NEXT_PUBLIC_API_URL:?NEXT_PUBLIC_API_URL is required}"
replace_token '__OTCLICK_GOOGLE_AUTH_ENABLED__' "${NEXT_PUBLIC_GOOGLE_AUTH_ENABLED:-false}"

exec npm start
