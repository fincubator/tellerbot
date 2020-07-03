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
import asyncio
import logging
import typing
from time import time

from aiogram import Bot
from aiogram import types
from aiogram.bot import api
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher
from aiogram.dispatcher.middlewares import BaseMiddleware

from src.config import config
from src.database import database
from src.database import database_user
from src.database import MongoStorage
from src.i18n import i18n


class IncomingHistoryMiddleware(BaseMiddleware):
    """Middleware for storing incoming history."""

    async def trigger(self, action, args):
        """Save incoming data in the database."""
        if (
            "update" not in action
            and "error" not in action
            and action.startswith("pre_process_")
        ):
            await database.logs.insert_one(
                {
                    "direction": "in",
                    "type": action.split("pre_process_", 1)[1],
                    "data": args[0].to_python(),
                }
            )


class TellerBot(Bot):
    """Custom bot class."""

    async def request(self, method, data=None, *args, **kwargs):
        """Make a request and save it in the database."""
        result = await super().request(method, data, *args, **kwargs)
        if (
            config.DATABASE_LOGGING_ENABLED
            and result
            and method
            not in (
                api.Methods.GET_UPDATES,
                api.Methods.SET_WEBHOOK,
                api.Methods.DELETE_WEBHOOK,
                api.Methods.GET_WEBHOOK_INFO,
                api.Methods.GET_ME,
            )
        ):
            # On requests Telegram either returns True on success or relevant object.
            # To store only useful information, method's payload is saved if result is
            # a boolean and result is saved otherwise.
            await database.logs.insert_one(
                {
                    "direction": "out",
                    "type": method,
                    "data": data if isinstance(result, bool) else result,
                }
            )
        return result


class DispatcherManual(Dispatcher):
    """Dispatcher with user availability in database check."""

    async def process_update(self, update: types.Update):
        """Process update object with user availability in database check.

        If bot doesn't know the user, it pretends they sent /start message.
        """
        user = None
        if update.message:
            user = update.message.from_user
            chat = update.message.chat
        elif update.callback_query and update.callback_query.message:
            user = update.callback_query.from_user
            chat = update.callback_query.message.chat
        if user:
            db_user = await database.users.find_one({"id": user.id, "chat": chat.id})
            if db_user is None:
                if update.message:
                    update.message.text = "/start"
                elif update.callback_query:
                    await update.callback_query.answer()
                    update = types.Update(
                        update_id=update.update_id,
                        message={
                            "message_id": -1,
                            "from": user.to_python(),
                            "chat": chat.to_python(),
                            "date": int(time()),
                            "text": "/start",
                        },
                    )
            database_user.set(db_user)
        return await super().process_update(update)


tg = TellerBot(None, loop=asyncio.get_event_loop(), validate_token=False)
dp = DispatcherManual(tg)


def setup():
    """Set API token from config to bot and setup dispatcher."""
    with open(config.TOKEN_FILENAME, "r") as token_file:
        tg._ctx_token.set(token_file.read().strip())

    dp.storage = MongoStorage()

    i18n.reload()
    dp.middleware.setup(i18n)

    logging.basicConfig(level=config.LOGGER_LEVEL)
    dp.middleware.setup(LoggingMiddleware())
    if config.DATABASE_LOGGING_ENABLED:
        dp.middleware.setup(IncomingHistoryMiddleware())


def private_handler(*args, **kwargs):
    """Register handler only for private message."""

    def decorator(handler: typing.Callable):
        dp.register_message_handler(
            handler,
            lambda message: message.chat.type == types.ChatType.PRIVATE,  # noqa: E721
            *args,
            **kwargs
        )
        return handler

    return decorator


state_handlers = {}


def state_handler(state):
    """Associate ``state`` with decorated handler."""

    def decorator(handler):
        state_handlers[state.state] = handler
        return handler

    return decorator
