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
import secrets

from aiogram.utils import executor

from src import bot
from src import handlers  # noqa: F401
from src import notifications
from src.bot import dp
from src.bot import tg
from src.config import config
from src.escrow import close_blockchains
from src.escrow import connect_to_blockchains


async def on_startup(webhook_path, *args):
    """Prepare bot before starting.

    Set webhook and run background tasks.
    """
    await tg.delete_webhook()
    await tg.set_webhook("https://" + config.SERVER_HOST + webhook_path)
    asyncio.create_task(notifications.run_loop())
    asyncio.create_task(connect_to_blockchains())


def main():
    """Start bot in webhook mode.

    Bot's main entry point.
    """
    url_token = secrets.token_urlsafe()
    webhook_path = config.WEBHOOK_PATH + "/" + url_token

    bot.setup()
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=webhook_path,
        on_startup=lambda *args: on_startup(webhook_path, *args),
        on_shutdown=lambda *args: close_blockchains(),
        host=config.INTERNAL_HOST,
        port=config.SERVER_PORT,
    )
    print()  # noqa: T001  Executor stopped with ^C

    # Stop all background tasks
    loop = asyncio.get_event_loop()
    for task in asyncio.all_tasks(loop):
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
