"""hh.ru OAuth client credentials.

The defaults are the ones the official hh.ru Android app ships with, inherited
from `hh-applicant-tool`. They are not ours and hh can rotate them at any
moment, which would break every deployment at once — so they are overridable:
set HH_CLIENT_ID / HH_CLIENT_SECRET in .env to use your own registered
application (https://dev.hh.ru/admin) and stop depending on them.
"""

import os

ANDROID_CLIENT_ID = os.getenv(
    "HH_CLIENT_ID",
    "HIOMIAS39CA9DICTA7JIO64LQKQJF5AGIK74G9ITJKLNEDAOH5FHS5G1JI7FOEGD",
)

ANDROID_CLIENT_SECRET = os.getenv(
    "HH_CLIENT_SECRET",
    "V9M870DE342BGHFRUJ5FTCGCUA1482AN0DI8C5TFI9ULMA89H10N60NOP8I4JMVS",
)
