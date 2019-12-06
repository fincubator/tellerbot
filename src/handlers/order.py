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
"""Handlers for showing orders and reacting to query buttons attached to them."""
import typing
from decimal import Decimal
from functools import wraps
from time import time

import pymongo
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils.exceptions import MessageCantBeDeleted
from aiogram.utils.exceptions import MessageNotModified
from bson.decimal128 import Decimal128
from bson.objectid import ObjectId
from motor.core import AgnosticBaseCursor as Cursor

from src import states
from src.bot import dp
from src.bot import tg
from src.config import Config
from src.database import database
from src.database import STATE_KEY
from src.escrow import get_escrow_instance
from src.escrow.escrow_offer import EscrowOffer
from src.handlers.base import orders_list
from src.handlers.base import private_handler
from src.handlers.base import show_order
from src.i18n import _
from src.money import money
from src.money import MoneyValueError
from src.money import normalize

OrderType = typing.Mapping[str, typing.Any]


def order_handler(
    handler: typing.Callable[[types.CallbackQuery, OrderType], typing.Any]
):
    """Simplify handling callback queries attached to order.

    Add order of ``OrderType`` to arguments of ``handler``.
    """

    @wraps(handler)
    async def decorator(call: types.CallbackQuery):
        order_id = call.data.split()[1]
        order = await database.orders.find_one({"_id": ObjectId(order_id)})
        if not order:
            await call.answer(_("Order is not found."))
            return

        return await handler(call, order)

    return decorator


async def show_orders(
    call: types.CallbackQuery,
    cursor: Cursor,
    start: int,
    quantity: int,
    buttons_data: str,
    invert: bool,
    user_id: typing.Optional[int] = None,
):
    """Send list of orders.

    :param cursor: Cursor of MongoDB query to orders.
    :param chat_id: Telegram chat ID.
    :param start: Start index.
    :param quantity: Quantity of orders in cursor.
    :param buttons_data: Beginning of callback data of left/right buttons.
    :param user_id: If cursor is user-specific, Telegram ID of user
        who created all orders in cursor.
    :param invert: Invert all prices.
    """
    if start >= quantity > 0:
        await call.answer(_("There are no more orders."))
        return

    try:
        await call.answer()
        await orders_list(
            cursor,
            call.message.chat.id,
            start,
            quantity,
            buttons_data,
            user_id=user_id,
            message_id=call.message.message_id,
            invert=invert,
        )
    except MessageNotModified:
        await call.answer(_("There are no previous orders."))


@dp.callback_query_handler(
    lambda call: call.data.startswith("get_order "), state=any_state
)
@order_handler
async def get_order_button(call: types.CallbackQuery, order: OrderType):
    """Choose order from order book."""
    await call.answer()
    await show_order(order, call.message.chat.id, call.from_user.id, show_id=True)


@private_handler(commands=["id"])
@private_handler(regexp="(ID: )?[a-f0-9]{24}")
async def get_order_command(message: types.Message):
    """Get order from ID.

    Order ID is indicated after **/id** or **ID:** in message text.
    """
    args = message.text.split()
    order_id = args[1] if len(args) > 1 else args[0]
    order = await database.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        await tg.send_message(message.chat.id, _("Order is not found."))
        return
    await show_order(order, message.chat.id, message.from_user.id)


@dp.callback_query_handler(
    lambda call: call.data.startswith(("invert ", "revert ")), state=any_state
)
@order_handler
async def invert_button(call: types.CallbackQuery, order: OrderType):
    """React to invert button query."""
    args = call.data.split()

    invert = args[0] == "invert"
    location_message_id = int(args[2])
    edit = bool(int(args[3]))
    show_id = call.message.text.startswith("ID")

    await call.answer()
    await show_order(
        order,
        call.message.chat.id,
        call.from_user.id,
        message_id=call.message.message_id,
        location_message_id=location_message_id,
        show_id=show_id,
        invert=invert,
        edit=edit,
    )


async def aggregate_orders(buy: str, sell: str) -> typing.Tuple[Cursor, int]:
    """Aggregate and query orders with specified currency pair.

    Return cursor with unexpired orders sorted by price and creation
    time and quantity of documents in it.
    """
    query = {
        "buy": buy,
        "sell": sell,
        "$or": [
            {"expiration_time": {"$exists": False}},
            {"expiration_time": {"$gt": time()}},
        ],
    }
    cursor = database.orders.aggregate(
        [
            {"$match": query},
            {"$addFields": {"price_buy": {"$ifNull": ["$price_buy", ""]}}},
            {
                "$sort": {
                    "price_buy": pymongo.ASCENDING,
                    "start_time": pymongo.DESCENDING,
                }
            },
        ]
    )
    quantity = await database.orders.count_documents(query)
    return cursor, quantity


@dp.callback_query_handler(
    lambda call: call.data.startswith("orders "), state=any_state
)
async def orders_button(call: types.CallbackQuery):
    """React to left/right button query in order book."""
    query = {
        "$or": [
            {"expiration_time": {"$exists": False}},
            {"expiration_time": {"$gt": time()}},
        ]
    }
    cursor = database.orders.find(query).sort("start_time", pymongo.DESCENDING)
    quantity = await database.orders.count_documents(query)

    args = call.data.split()
    start = max(0, int(args[1]))
    invert = bool(int(args[2]))
    await show_orders(
        call, cursor, start, quantity, "orders", invert, user_id=call.from_user.id
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("my_orders "), state=any_state
)
async def my_orders_button(call: types.CallbackQuery):
    """React to left/right button query in list of user's orders."""
    query = {"user_id": call.from_user.id}
    cursor = database.orders.find(query).sort("start_time", pymongo.DESCENDING)
    quantity = await database.orders.count_documents(query)

    args = call.data.split()
    start = max(0, int(args[1]))
    invert = bool(int(args[2]))
    await show_orders(call, cursor, start, quantity, "my_orders", invert)


@dp.callback_query_handler(
    lambda call: call.data.startswith("matched_orders "), state=any_state
)
async def matched_orders_button(call: types.CallbackQuery):
    """React to left/right button query in list of orders matched by currency pair."""
    args = call.data.split()
    start = max(0, int(args[3]))
    invert = bool(int(args[4]))
    cursor, quantity = await aggregate_orders(args[1], args[2])
    await call.answer()
    await show_orders(
        call,
        cursor,
        start,
        quantity,
        "matched_orders {} {}".format(args[1], args[2]),
        invert,
        user_id=call.from_user.id,
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("similar "), state=any_state
)
@order_handler
async def similar_button(call: types.CallbackQuery, order: OrderType):
    """React to "Similar" button by sending list of similar orders.

    Similar orders are ones that have the same currency pair.
    """
    cursor, quantity = await aggregate_orders(order["buy"], order["sell"])
    await call.answer()
    await orders_list(
        cursor,
        call.message.chat.id,
        0,
        quantity,
        "matched_orders {} {}".format(order["buy"], order["sell"]),
        user_id=call.from_user.id,
    )


@dp.callback_query_handler(lambda call: call.data.startswith("match "), state=any_state)
@order_handler
async def match_button(call: types.CallbackQuery, order: OrderType):
    """React to "Match" button by sending list of matched orders.

    Matched orders are ones that have the inverted currency pair.
    """
    cursor, quantity = await aggregate_orders(order["sell"], order["buy"])
    await call.answer()
    await orders_list(
        cursor,
        call.message.chat.id,
        0,
        quantity,
        "matched_orders {} {}".format(order["sell"], order["buy"]),
        user_id=call.from_user.id,
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("escrow "), state=any_state
)
@order_handler
async def escrow_button(call: types.CallbackQuery, order: OrderType):
    """React to "Escrow" button by starting escrow exchange."""
    if not Config.ESCROW_ENABLED:
        await call.answer(
            _("Escrow is temporarily unavailable. Sorry for the inconvenience.")
        )
        return
    args = call.data.split()
    currency_arg = args[2]
    edit = bool(int(args[3]))

    if currency_arg == "sum_buy":
        sum_currency = order["buy"]
        new_currency = order["sell"]
        new_currency_arg = "sum_sell"
    elif currency_arg == "sum_sell":
        sum_currency = order["sell"]
        new_currency = order["buy"]
        new_currency_arg = "sum_buy"
    else:
        return

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(
            _("Change to {}").format(new_currency),
            callback_data="escrow {} {} 1".format(order["_id"], new_currency_arg),
        )
    )
    answer = _("Send exchange sum in {}.").format(sum_currency)
    if edit:
        await database.escrow.update_one(
            {"pending_input_from": call.from_user.id},
            {"$set": {"sum_currency": currency_arg}},
        )
        await call.answer()
        await tg.edit_message_text(
            answer, call.message.chat.id, call.message.message_id, reply_markup=keyboard
        )
    else:
        init_user = await database.users.find_one({"id": call.from_user.id})
        counter_user = await database.users.find_one({"id": order["user_id"]})
        await database.escrow.delete_many({"init.send_address": {"$exists": False}})
        offer = EscrowOffer(
            **{
                "_id": ObjectId(),
                "order": order["_id"],
                "buy": order["buy"],
                "sell": order["sell"],
                "type": "buy" if get_escrow_instance(order["buy"]) else "sell",
                "time": time(),
                "sum_currency": currency_arg,
                "init": {
                    "id": init_user["id"],
                    "locale": init_user.get("locale"),
                    "mention": call.from_user.mention,
                },
                "counter": {
                    "id": counter_user["id"],
                    "locale": counter_user.get("locale"),
                    "mention": order["mention"],
                },
                "pending_input_from": call.message.chat.id,
            }
        )
        await offer.insert_document()
        await call.answer()
        await tg.send_message(call.message.chat.id, answer, reply_markup=keyboard)
        await states.Escrow.amount.set()


@dp.callback_query_handler(lambda call: call.data.startswith("edit "), state=any_state)
@order_handler
async def edit_button(call: types.CallbackQuery, order: OrderType):
    """React to "Edit" button by entering edit mode on order."""
    args = call.data.split()
    field = args[2]

    if field == "sum_buy":
        answer = _("Send new amount of buying.")
    elif field == "sum_sell":
        answer = _("Send new amount of selling.")
    elif field == "price":
        answer = _("Send new price.")
    elif field == "payment_system":
        answer = _("Send new payment system.")
    elif field == "duration":
        answer = _("Send new duration.")
    elif field == "comments":
        answer = _("Send new comments.")
    else:
        answer = None

    await call.answer()
    if answer:
        result = await tg.send_message(call.message.chat.id, answer)
        await database.users.update_one(
            {"id": call.from_user.id},
            {
                "$set": {
                    "edit.order_message_id": call.message.message_id,
                    "edit.message_id": result.message_id,
                    "edit.order_id": order["_id"],
                    "edit.field": field,
                    "edit.location_message_id": int(args[3]),
                    "edit.invert": bool(int(args[4])),
                    "edit.show_id": call.message.text.startswith("ID"),
                }
            },
        )
        await states.field_editing.set()


@private_handler(state=states.field_editing)
async def edit_field(message: types.Message, state: FSMContext):
    """Ask new value of chosen order's field during editing."""
    user = await database.users.find_one({"id": message.from_user.id})
    edit = user["edit"]
    field = edit["field"]
    invert = edit["invert"]
    update_dict = {}
    set_dict = {}
    error = None

    if message.text == "-":
        if field == "price":
            unset_dict = {"price_buy": True, "price_sell": True}
        else:
            unset_dict = {field: True}
            if field == "duration":
                unset_dict["expiration_time"] = True
                unset_dict["notify"] = True
        update_dict["$unset"] = unset_dict

    elif field == "sum_buy":
        try:
            transaction_sum = money(message.text)
        except MoneyValueError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({"_id": edit["order_id"]})
            set_dict["sum_buy"] = Decimal128(transaction_sum)
            if "price_sell" in order:
                set_dict["sum_sell"] = Decimal128(
                    normalize(transaction_sum * order["price_sell"].to_decimal())
                )

    elif field == "sum_sell":
        try:
            transaction_sum = money(message.text)
        except MoneyValueError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({"_id": edit["order_id"]})
            set_dict["sum_sell"] = Decimal128(transaction_sum)
            if "price_buy" in order:
                set_dict["sum_buy"] = Decimal128(
                    normalize(transaction_sum * order["price_buy"].to_decimal())
                )

    elif field == "price":
        try:
            price = money(message.text)
        except MoneyValueError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({"_id": edit["order_id"]})

            if invert:
                price_sell = normalize(Decimal(1) / price)
                set_dict["price_buy"] = Decimal128(price)
                set_dict["price_sell"] = Decimal128(price_sell)

                if order["sum_currency"] == "buy":
                    set_dict["sum_sell"] = Decimal128(
                        normalize(order["sum_buy"].to_decimal() * price_sell)
                    )
                elif "sum_sell" in order:
                    set_dict["sum_buy"] = Decimal128(
                        normalize(order["sum_sell"].to_decimal() * price)
                    )
            else:
                price_buy = normalize(Decimal(1) / price)
                set_dict["price_buy"] = Decimal128(price_buy)
                set_dict["price_sell"] = Decimal128(price)

                if order["sum_currency"] == "sell":
                    set_dict["sum_buy"] = Decimal128(
                        normalize(order["sum_sell"].to_decimal() * price_buy)
                    )
                elif "sum_buy" in order:
                    set_dict["sum_sell"] = Decimal128(
                        normalize(order["sum_buy"].to_decimal() * price)
                    )

    elif field == "payment_system":
        payment_system = message.text.replace("\n", " ")
        if len(payment_system) >= 150:
            await tg.send_message(
                message.chat.id,
                _(
                    "This value should contain less than {} characters "
                    "(you sent {} characters)."
                ).format(150, len(payment_system)),
            )
            return
        set_dict["payment_system"] = payment_system

    elif field == "duration":
        try:
            duration = int(message.text)
            if duration <= 0:
                raise ValueError
        except ValueError:
            error = _("Send natural number.")
        else:
            if duration <= 100000:
                order = await database.orders.find_one({"_id": edit["order_id"]})
                set_dict["duration"] = duration
                expiration_time = order["start_time"] + duration * 24 * 60 * 60
                set_dict["expiration_time"] = expiration_time
                set_dict["notify"] = expiration_time > time()

    elif field == "comments":
        comments = message.text
        if len(comments) >= 150:
            await tg.send_message(
                message.chat.id,
                _(
                    "This value should contain less than {} characters "
                    "(you sent {} characters)."
                ).format(150, len(comments)),
            )
            return
        set_dict["comments"] = comments

    if set_dict:
        update_dict["$set"] = set_dict

    if update_dict:
        result = await database.orders.update_one(
            {"_id": edit["order_id"]}, update_dict
        )
        if result.modified_count:
            order = await database.orders.find_one({"_id": edit["order_id"]})
            await show_order(
                order,
                message.chat.id,
                message.from_user.id,
                message_id=edit["order_message_id"],
                location_message_id=edit["location_message_id"],
                show_id=edit["show_id"],
                invert=edit["invert"],
                edit=True,
            )
        await database.users.update_one(
            {"id": message.from_user.id}, {"$unset": {"edit": True, STATE_KEY: True}}
        )
        await message.delete()
        try:
            await tg.delete_message(message.chat.id, edit["message_id"])
        except MessageCantBeDeleted:
            return
    elif error:
        await message.delete()
        await tg.edit_message_text(error, message.chat.id, edit["message_id"])


@dp.callback_query_handler(
    lambda call: call.data.startswith("delete "), state=any_state
)
@order_handler
async def delete_button(call: types.CallbackQuery, order: OrderType):
    """React to "Delete" button by asking user to confirm deletion."""
    args = call.data.split()
    location_message_id = int(args[2])
    show_id = call.message.text.startswith("ID")

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(
            _("Yes, I'm totally sure"),
            callback_data="confirm_delete {} {}".format(
                order["_id"], location_message_id
            ),
        )
    )
    keyboard.row(
        types.InlineKeyboardButton(
            _("No"),
            callback_data="revert {} {} 0 {}".format(
                order["_id"], location_message_id, int(show_id)
            ),
        )
    )

    await tg.edit_message_text(
        _("Are you sure you want to delete the order?"),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("confirm_delete "), state=any_state
)
async def confirm_delete_button(call: types.CallbackQuery):
    """Delete order after confirmation button query."""
    order_id = call.data.split()[1]
    order = await database.orders.find_one_and_delete(
        {"_id": ObjectId(order_id), "user_id": call.from_user.id}
    )
    if not order:
        await call.answer(_("Couldn't delete order."))
        return

    location_message_id = int(call.data.split()[2])
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    _("Hide"), callback_data="hide {}".format(location_message_id)
                )
            ]
        ]
    )
    await tg.edit_message_text(
        _("Order is deleted."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
    )


@dp.callback_query_handler(lambda call: call.data.startswith("hide "), state=any_state)
async def hide_button(call: types.CallbackQuery):
    """React to "Hide" button by deleting messages with location object and order."""
    try:
        await call.message.delete()
    except MessageCantBeDeleted:
        await call.answer(_("Couldn't hide order."))
        return
    location_message_id = call.data.split()[1]
    if location_message_id != "-1":
        await tg.delete_message(call.message.chat.id, location_message_id)


@private_handler(commands=["p", "pair"], state=any_state)
async def search_currencies(message: types.Message, state: FSMContext):
    r"""Search orders by currency pair.

    Currency pair is indicated with one or two space separated
    arguments after **/pair** or **/p** in message text. If two
    arguments are sent, then first is the currency order's creator
    wants to sell and second is the currency that order's creator
    wants to buy. If one argument is sent, then it's any of the
    currencies in a pair.

    Any argument can be replaced with \*, which results in searching
    pairs with any currency in place of the wildcard.

    Examples:
        ==========  =================================================
        Command     Description
        ==========  =================================================
        /p BTC USD  Show orders that sell BTC and buy USD (BTC → USD)
        /p BTC *    Show orders that sell BTC and buy any currency
        /p * USD    Show orders that sell any currency and buy USD
        /p BTC      Show orders that sell or buy BTC
        /p * *      Equivalent to /book
        ==========  =================================================

    """
    query = {
        "$or": [
            {"expiration_time": {"$exists": False}},
            {"expiration_time": {"$gt": time()}},
        ]
    }

    source = message.text.upper().split()
    if len(source) == 2:
        query = {"$and": [query, {"$or": [{"sell": source[1]}, {"buy": source[1]}]}]}
    elif len(source) == 3:
        sell, buy = source[1], source[2]
        if sell != "*":
            query["sell"] = sell
        if buy != "*":
            query["buy"] = buy
    else:
        await tg.send_message(
            message.chat.id, _("Send currency or currency pair as an argument.")
        )
        return

    cursor = database.orders.find(query).sort("start_time", pymongo.DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(
        cursor, message.chat.id, 0, quantity, "orders", user_id=message.from_user.id
    )


@private_handler(commands=["c", "creator"], state=any_state)
async def search_by_creator(message: types.Message, state: FSMContext):
    """Search orders by creator.

    Creator is indicated with username (with or without @) or user ID
    after **/creator** or **/c** in message text.

    In contrast to usernames and user IDs, names aren't unique and
    therefore not supported.
    """
    query: typing.Dict[str, typing.Any] = {
        "$or": [
            {"expiration_time": {"$exists": False}},
            {"expiration_time": {"$gt": time()}},
        ],
    }
    source = message.text.split()
    try:
        creator = source[1]
        if creator.isdigit():
            query["user_id"] = int(creator)
        elif creator[0] == "@":
            query["mention"] = creator
        else:
            query["mention"] = "@" + creator
    except IndexError:
        await tg.send_message(
            message.chat.id, _("Send username as an argument."),
        )
        return

    cursor = database.orders.find(query).sort("start_time", pymongo.DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(
        cursor, message.chat.id, 0, quantity, "orders", user_id=message.from_user.id
    )
