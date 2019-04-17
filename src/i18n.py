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


from aiogram.contrib.middlewares.i18n import I18nMiddleware
from aiogram.types import User
from babel import Locale
from typing import Any, Tuple, Optional

import config
from .database import database


class I18nMiddlewareManual(I18nMiddleware):
    async def get_user_locale(
        self, action: Optional[str] = None, args: Optional[Tuple[Any]] = None
    ) -> str:
        user: User = User.get_current()
        document = await database.users.find_one({'id': user.id})
        if document:
            return document.get('locale')

        locale: Locale = user.locale
        if locale:
            language = locale.language
            return language


i18n = I18nMiddlewareManual('bot', config.LOCALES_DIR)
