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

from aiogram import Bot
from aiogram import types
from aiogram.bot import api
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher

from src.config import config
from src.database import MongoStorage
from src.i18n import i18n


tg = Bot("0:", loop=asyncio.get_event_loop(), validate_token=False)
dp = Dispatcher(tg)


def setup():
    """Set API token from config to bot and setup dispatcher."""
    with open(config.TOKEN_FILENAME, "r") as token_file:
        token = token_file.read().strip()
        api.check_token(token)
        tg._ctx_token.set(token)
        tg.id = int(token.split(":")[0])

    dp.storage = MongoStorage()

    i18n.reload()
    dp.middleware.setup(i18n)

    logging.basicConfig(level=config.LOGGER_LEVEL)
    dp.middleware.setup(LoggingMiddleware())


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
