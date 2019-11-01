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
from pathlib import Path
from typing import Any
from typing import Optional
from typing import Tuple

from aiogram.contrib.middlewares.i18n import I18nMiddleware
from aiogram.types import User
from babel import Locale

from src.database import database


class I18nMiddlewareManual(I18nMiddleware):
    async def get_user_locale(
        self, action: Optional[str] = None, args: Optional[Tuple[Any]] = None
    ) -> Optional[str]:
        if action not in ('pre_process_message', 'pre_process_callback_query'):
            return None

        user: User = User.get_current()
        document = await database.users.find_one({'id': user.id})
        if document:
            return document.get('locale')

        locale: Locale = user.locale
        if locale:
            return locale.language
        return None


i18n = I18nMiddlewareManual('bot', Path(__file__).parents[1] / 'locale')
_ = i18n.gettext
