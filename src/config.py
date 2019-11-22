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


class Config:
    """Data holder for configuration values."""

    TOKEN_FILENAME: str
    INTERNAL_HOST: str = "127.0.0.1"
    SERVER_HOST: str
    SERVER_PORT: int
    WEBHOOK_PATH: str
    DATABASE_NAME: str = "tellerbot"
    DATABASE_HOST: str = "127.0.0.1"
    DATABASE_USERNAME: str
    DATABASE_PASSWORD_FILENAME: str

    LOGGER_LEVEL: str
    LOG_FILENAME: str

    SUPPORT_CHAT_ID: int
    EXCEPTIONS_CHAT_ID: int

    ORDERS_COUNT: int
    ORDERS_LIMIT_HOURS: int
    ORDERS_LIMIT_COUNT: int

    ESCROW_ENABLED: bool
    WIF_FILENAME: str
    OP_CHECK_TIMEOUT_HOURS: int


for name, annotation in Config.__annotations__.items():
    if annotation == int:
        value = getenv_int(name)
    elif annotation == bool:
        value = getenv_bool(name)
    else:
        value = getenv(name)
    if value:
        setattr(Config, name, value)
