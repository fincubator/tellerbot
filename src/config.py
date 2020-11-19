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


DEFAULT_VALUES = {
    "SET_WEBHOOK": False,
    "INTERNAL_HOST": "127.0.0.1",
    "DATABASE_HOST": "127.0.0.1",
    "DATABASE_PORT": 27017,
    "DATABASE_NAME": "tellerbot",
    "ESCROW_ENABLED": False,
}


def get_typed_env(key):
    """Get an environment variable with inferred type."""
    env = getenv(key)
    if env is None:
        return None
    elif env == "true":
        return True
    elif env == "false":
        return False
    try:
        return int(env)
    except ValueError:
        return env


class Config:
    """Lazy interface to configuration values."""

    def __setattr__(self, name, value):
        """Set configuration value."""
        super().__setattr__(name, value)

    def __getattr__(self, name):
        """Get configuration value.

        Return value of environment variable ``name`` if it is set or
        default value otherwise.
        """
        env = get_typed_env(name)
        if env is not None:
            value = env
        elif name not in DEFAULT_VALUES:
            raise AttributeError(f"config has no option '{name}'")
        else:
            value = DEFAULT_VALUES[name]
        setattr(self, name, value)
        return value


config = Config()
