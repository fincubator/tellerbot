from configparser import ConfigParser
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()

parser = ConfigParser()
parser.read(ROOT_DIR / "config.ini")

TOKEN_FILE = parser.get("Connection", "token_filename")
SERVER_HOST = parser.get("Connection", "server_host")
SERVER_PORT = parser.getint("Connection", "server_port")
WEBHOOK_PATH = parser.get("Connection", "webhook_path")
DATABASE_NAME = parser.get("Connection", "database_name")

LOGGER_LEVEL = parser.get("Logging", "logger_level")
LOG_FILENAME = parser.get("Logging", "log_filename")

SUPPORT_CHAT_ID = parser.getint("Chat IDs", "support")
EXCEPTIONS_CHAT_ID = parser.getint("Chat IDs", "exceptions")

ORDERS_COUNT = parser.getint("Orders", "count")
ORDERS_LIMIT_HOURS = parser.getint("Orders", "limit_hours")
ORDERS_LIMIT_COUNT = parser.getint("Orders", "limit_count")

WIF_FILENAME = parser.get("Blockchain", "wif_filename")
