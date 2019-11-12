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
from time import time

from aiogram.utils.exceptions import TelegramAPIError

from src.bot import tg
from src.database import database
from src.handlers import show_order
from src.i18n import _


async def run_loop():
    """Notify order creators about expired orders in infinite loop."""
    while True:
        cursor = database.orders.find(
            {"expiration_time": {"$lte": time()}, "notify": True}
        )
        async for order in cursor:
            user = await database.users.find_one({"id": order["user_id"]})
            message = _("Your order has expired.", locale=user["locale"])
            message += "\nID: {}".format(order["_id"])
            try:
                await tg.send_message(user["chat"], message)
            except TelegramAPIError:
                pass
            else:
                await show_order(order, user["chat"], user["id"])
                await asyncio.sleep(1)  # Avoid Telegram limit
            finally:
                await database.orders.update_one(
                    {"_id": order["_id"]}, {"$set": {"notify": False}}
                )
