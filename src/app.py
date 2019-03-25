# Copyright (C) 2019  alfred richardsn
#
# This file is part of BailsBot.
#
# BailsBot is free software: you can redistribute it and/or modify
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
# along with BailsBot.  If not, see <https://www.gnu.org/licenses/>.


import config
from .bot import bot, dp

from aiogram.utils.executor import start_webhook


async def on_startup(dp):
    await bot.delete_webhook()
    url = 'https://{}'.format(config.SERVER_HOST)
    await bot.set_webhook(url + config.WEBHOOK_PATH)


def main():
    start_webhook(
        dispatcher=dp,
        webhook_path=config.WEBHOOK_PATH,
        on_startup=on_startup,
        host='127.0.0.1',
        port=config.SERVER_PORT
    )
