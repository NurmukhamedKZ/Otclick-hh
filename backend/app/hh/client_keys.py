"""hh.ru OAuth client credentials.

The defaults are the ones the official hh.ru Android app ships with, inherited
from `hh-applicant-tool`. They are not ours and hh can rotate them at any
moment, which would break every deployment at once — so they are overridable:
set HH_CLIENT_ID / HH_CLIENT_SECRET in .env to use your own registered
application (https://dev.hh.ru/admin, or https://dev.hh.kz/admin for Kazakhstan)
and stop depending on them.

Known failure mode: the borrowed Android client answers `?error=geo_forbidden`
on /oauth/authorize for users outside its region — the login succeeds and hh
then refuses to hand out the code. Your own application, registered in the
right region, comes with its own HH_REDIRECT_URI (the Android one is a custom
scheme the browser never actually loads; yours will be an https URL, which is
fine — we intercept the redirect before it resolves).
"""

from app.config import settings

# Via settings, not os.getenv: the repo-root .env is parsed by pydantic-settings
# and never reaches os.environ, so `cd backend && uvicorn` would silently ignore
# an override that works in docker (env_file) — the worst kind of config bug.
ANDROID_CLIENT_ID = (
    settings.HH_CLIENT_ID
    or "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD"
)

ANDROID_CLIENT_SECRET = (
    settings.HH_CLIENT_SECRET
    or "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS"
)

# Must match the redirect_uri registered for the client above, byte for byte —
# hh rejects the token exchange otherwise.
REDIRECT_URI = settings.HH_REDIRECT_URI or "hhandroid://oauthresponse"
