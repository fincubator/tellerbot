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
import typing
from time import time

from aiogram.utils.exceptions import TelegramAPIError

from src.bot import tg
from src.database import database
from src.handlers.base import show_order
from src.i18n import i18n
from src.money import gateway_currency_regexp


async def run_loop():
    """Notify order creators about expired orders in infinite loop."""
    while True:
        cursor = database.orders.find(
            {"expiration_time": {"$lte": time()}, "notify": True}
        )
        sent = False
        async for order in cursor:
            user = await database.users.find_one({"id": order["user_id"]})
            message = i18n("order_expired", locale=user["locale"])
            message += "\nID: {}".format(order["_id"])
            try:
                if sent:
                    await asyncio.sleep(1)  # Avoid Telegram limit
                await tg.send_message(user["chat"], message)
            except TelegramAPIError:
                pass
            else:
                await show_order(order, user["chat"], user["id"], locale=user["locale"])
                sent = True
            finally:
                await database.orders.update_one(
                    {"_id": order["_id"]}, {"$set": {"notify": False}}
                )
        if not sent:
            await asyncio.sleep(1)  # Reduce database load


async def order_notification(order: typing.Mapping[str, typing.Any]):
    """Notify users about order.

    Subscriptions to these notifications are managed with
    **/subscribe** or **/unsubscribe** commands of ``start_menu``
    handlers.
    """
    users = database.subscriptions.find(
        {
            "subscriptions": {
                "$elemMatch": {
                    "buy": {"$in": [gateway_currency_regexp(order["buy"]), None]},
                    "sell": {"$in": [gateway_currency_regexp(order["sell"]), None]},
                }
            },
        }
    )
    async for user in users:
        if user["id"] == order["user_id"]:
            continue
        order = await database.orders.find_one({"_id": order["_id"]})  # Update order
        if not order:
            return
        await show_order(
            order, user["chat"], user["id"], show_id=True, locale=user["locale"]
        )
        await asyncio.sleep(1)  # Avoid Telegram limit
