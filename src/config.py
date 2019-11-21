# Copyright (C) 2019  alfred richardsn
#
# This file is part of TellerBot.
#
# TellerBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with TellerBot.  If not, see <https://www.gnu.org/licenses/>.
from os import getenv


def getenv_int(key, default=None):
    """Convert the value of the environment variable key to an integer."""
    env = getenv(key)
    try:
        return int(env)
    except (TypeError, ValueError):
        return default


def getenv_bool(key, default=None):
    """Convert the value of the environment variable key to a boolean."""
    env = getenv(key)
    return env == "true" if env in ("true", "false") else default


TOKEN_FILENAME = getenv("TOKEN_FILENAME")
INTERNAL_HOST = getenv("INTERNAL_HOST", "127.0.0.1")
SERVER_HOST = getenv("SERVER_HOST")
SERVER_PORT = getenv_int("SERVER_PORT")
WEBHOOK_PATH = getenv("WEBHOOK_PATH")
DATABASE_NAME = getenv("DATABASE_NAME", "tellerbot")
DATABASE_HOST = getenv("DATABASE_HOST", "127.0.0.1")
DATABASE_USERNAME = getenv("DATABASE_USERNAME")
DATABASE_PASSWORD_FILENAME = getenv("DATABASE_PASSWORD_FILENAME")

LOGGER_LEVEL = getenv("LOGGER_LEVEL")
LOG_FILENAME = getenv("LOG_FILENAME")

SUPPORT_CHAT_ID = getenv_int("SUPPORT_CHAT_ID")
EXCEPTIONS_CHAT_ID = getenv_int("EXCEPTIONS_CHAT_ID")

ORDERS_COUNT = getenv_int("ORDERS_COUNT")
ORDERS_LIMIT_HOURS = getenv_int("ORDERS_LIMIT_HOURS")
ORDERS_LIMIT_COUNT = getenv_int("ORDERS_LIMIT_COUNT")

ESCROW_ENABLED = getenv_bool("ESCROW_ENABLED")
WIF_FILENAME = getenv("WIF_FILENAME")
