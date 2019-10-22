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


from asyncio import create_task

from aiogram.utils import executor

import config
from src.escrow import connect_to_blockchains
from src.notifications import run_loop
from src.registered_handlers import tg, dp


async def on_startup(*args):
    await tg.delete_webhook()
    url = 'https://{}'.format(config.SERVER_HOST)
    await tg.set_webhook(url + config.WEBHOOK_PATH)
    create_task(run_loop())
    create_task(connect_to_blockchains())


def main():
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=config.WEBHOOK_PATH,
        on_startup=on_startup,
        host='127.0.0.1',
        port=config.SERVER_PORT
    )
