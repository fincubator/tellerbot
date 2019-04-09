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
