# Copyright (C) 2019, 2020  alfred richardsn
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
import gettext
import typing
from pathlib import Path

from aiogram import types
from aiogram.contrib.middlewares.i18n import I18nMiddleware

from src.database import database_user


class I18nMiddlewareManual(I18nMiddleware):
    """I18n middleware which gets user locale from database."""

    def __init__(self, domain, path, default="en"):
        """Initialize I18nMiddleware without finding locales."""
        super(I18nMiddleware, self).__init__()

        self.domain = domain
        self.path = path
        self.default = default

    def find_locales(self) -> typing.Dict[str, gettext.NullTranslations]:
        """Load all compiled locales from path and add default fallbacks."""
        translations = super().find_locales()
        for translation in translations.values():
            translation.add_fallback(translations[self.default])
        return translations

    async def get_user_locale(
        self, action: str, args: typing.Tuple[typing.Any]
    ) -> typing.Optional[str]:
        """Get user locale by querying collection of users in database.

        Return value of ``locale`` field in user's corresponding
        document if it exists, otherwise return user's Telegram
        language if possible.
        """
        if action not in ("pre_process_message", "pre_process_callback_query"):
            return None

        user: types.User = types.User.get_current()
        document = database_user.get()
        if document:
            locale = document.get("locale", user.language_code)
        else:
            locale = user.language_code
        return locale if locale in self.available_locales else self.default


i18n = plural_i18n = I18nMiddlewareManual("bot", Path(__file__).parents[1] / "locale")
