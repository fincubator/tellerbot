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
import os
import typing
from pathlib import Path

from aiogram import types
from aiogram.contrib.middlewares.i18n import I18nMiddleware
from pymongo import ReturnDocument

from src.database import database


class I18nMiddlewareManual(I18nMiddleware):
    """I18n middleware which gets user locale from database."""

    def __init__(self, domain, path=None, default="en"):
        """Initialize I18nMiddleware without finding locales."""
        super(I18nMiddleware, self).__init__()

        if path is None:
            path = os.path.join(os.getcwd(), "locales")

        self.domain = domain
        self.path = path
        self.default = default

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
        chat: types.Chat = types.Chat.get_current()
        await database.users.update_many(
            {"id": {"$ne": user.id}, "mention": user.mention},
            {"$set": {"has_username": False}},
        )
        document = await database.users.find_one_and_update(
            {"id": user.id},
            {
                "$set": {"mention": user.mention, "has_username": bool(user.username)},
                "$setOnInsert": {"chat": chat.id, "locale": user.language_code},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return document["locale"]


_ = i18n = I18nMiddlewareManual("bot", Path(__file__).parents[1] / "locale")
