"""Constants for the Napper integration."""

DOMAIN = "napper"
API_BASE_URL = "https://api.napper.app"
APP_VERSION = "6.84.0"

CONF_EMAIL = "email"
CONF_OTP = "otp"
CONF_ID_TOKEN = "id_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_DEVICE_ID = "device_id"
CONF_USER_ID = "user_id"

DEFAULT_SCAN_INTERVAL_SECONDS = 60
MAX_NAP_SENSORS = 4

SERVICE_START_NAP = "start_nap"
SERVICE_STOP_SLEEP = "stop_sleep"
SERVICE_LOG_BEDTIME = "log_bedtime"
SERVICE_LOG_WAKE_UP = "log_wake_up"

STATIC_URL_PATH = "/napper_static"
CARD_FILENAME = "napper-circle-card.js"
CARD_URL = f"{STATIC_URL_PATH}/{CARD_FILENAME}"

NAP_ORDINAL_DE: dict[int, str] = {
    1: "Erstes Nickerchen",
    2: "Zweites Nickerchen",
    3: "Drittes Nickerchen",
    4: "Viertes Nickerchen",
    5: "Fünftes Nickerchen",
    6: "Sechstes Nickerchen",
}
