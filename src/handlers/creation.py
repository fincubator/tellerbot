# Copyright (C) 2019, 2020  alfred richardsn
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
"""Handlers for order creation.

Handlers decorated with ``state_handler`` are called by
``change_state`` when user skips (where it is possible) or goes back to
corresponding step using back/skip inline buttons. Handlers decorated
with ``private_handler`` are called when user sends value.
"""
import asyncio
import re
from datetime import datetime
from decimal import Decimal
from time import time
from typing import Any
from typing import Mapping
from typing import MutableMapping

import requests
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.types import ContentType
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from bson.decimal128 import Decimal128
from pymongo import ReturnDocument

from src.bot import dp
from src.bot import tg
from src.database import database
from src.handlers.base import inline_control_buttons
from src.handlers.base import private_handler
from src.handlers.base import show_order
from src.handlers.base import start_keyboard
from src.handlers.base import state_handler
from src.handlers.base import state_handlers
from src.i18n import _
from src.i18n import i18n
from src.money import money
from src.money import MoneyValueError
from src.money import normalize
from src.notifications import order_notification
from src.states import OrderCreation


CURRENCY_REGEXP = re.compile(r"^(?:(\w+)\.)?(\w+)$")


@dp.callback_query_handler(lambda call: call.data.startswith("state "), state=any_state)
async def change_state(call: types.CallbackQuery, state: FSMContext):
    """React to back/skip button query."""
    args = call.data.split()
    query_state_name = args[1]
    direction = args[2]

    state_name = await state.get_state()
    if state_name != query_state_name:
        return await call.answer(_("You're using the wrong button."))

    if state_name in OrderCreation.all_states_names:
        if direction == "back":
            new_state = await OrderCreation.previous()
        elif direction == "skip":
            new_state = await OrderCreation.next()
        handler = state_handlers.get(new_state)
        if handler:
            error = await handler(call)
            if not error:
                return await call.answer()
        await state.set_state(state_name)

    if direction == "back":
        answer = _("Couldn't go back.")
    elif direction == "skip":
        answer = _("Couldn't skip.")
    return await call.answer(answer)


@dp.callback_query_handler(lambda call: call.data == "cancel", state=any_state)
async def cancel_order_creation(call: types.CallbackQuery, state: FSMContext):
    """Cancel order creation."""
    await state.finish()
    await call.answer()

    order = await database.creation.delete_one({"user_id": call.from_user.id})
    if not order.deleted_count:
        await tg.send_message(
            call.message.chat.id,
            _("You are not creating order."),
            reply_markup=start_keyboard(),
        )
        return True

    await tg.send_message(
        call.message.chat.id, _("Order is cancelled."), reply_markup=start_keyboard()
    )


@state_handler(OrderCreation.buy)
async def create_order_handler(call: types.CallbackQuery):
    """Ask currency user wants to buy."""
    await tg.edit_message_text(
        _("What currency do you want to buy?"),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons(back=False)
        ),
    )


async def match_currency(message: types.Message):
    """Match message text with currency pattern."""
    text = message.text.upper()

    if len(text) >= 20:
        await tg.send_message(
            message.chat.id,
            _(
                "This value should contain less than {} characters "
                "(you sent {} characters)."
            ).format(20, len(text)),
        )
        return None

    match = CURRENCY_REGEXP.match(text)
    if not match:
        await tg.send_message(
            message.chat.id, _("Currency may only contain latin characters.")
        )
        return None

    return match


@private_handler(state=OrderCreation.buy)
async def choose_buy(message: types.Message, state: FSMContext):
    """Set currency user wants to buy and ask for one they want to sell."""
    match = await match_currency(message)
    if not match:
        return
    await database.creation.update_one(
        {"user_id": message.from_user.id}, {"$set": {"buy": match.group(0)}}
    )
    await OrderCreation.sell.set()
    await tg.send_message(
        message.chat.id,
        _("What currency do you want to sell?"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons(skip=False)
        ),
    )


@state_handler(OrderCreation.sell)
async def choose_buy_handler(call: types.CallbackQuery):
    """Ask currency user wants to sell."""
    order = await database.creation.find_one({"user_id": call.from_user.id})
    await tg.edit_message_text(
        _("What currency do you want to sell?"),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons(skip="sell" in order)
        ),
    )


@private_handler(state=OrderCreation.sell)
async def choose_sell(message: types.Message, state: FSMContext):
    """Set currency user wants to sell and ask for price."""
    match = await match_currency(message)
    if not match:
        return

    order = await database.creation.find_one_and_update(
        {"user_id": message.from_user.id},
        {"$set": {"sell": match.group(0), "price_currency": "sell"}},
        return_document=ReturnDocument.AFTER,
    )

    await OrderCreation.price.set()
    buttons = await inline_control_buttons()
    buttons.insert(0, [InlineKeyboardButton(_("Invert"), callback_data="price buy")])
    await tg.send_message(
        message.chat.id,
        _("At what price (in {}/{}) do you want to buy?").format(
            order["sell"], order["buy"]
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def price_ask(
    call: types.CallbackQuery, order: Mapping[str, Any], price_currency: str
):
    """Edit currency of price in message to ``price_currency`` field value."""
    if price_currency == "sell":
        answer = _("At what price (in {}/{}) do you want to buy?").format(
            order["sell"], order["buy"]
        )
        callback_command = "buy"
    else:
        answer = _("At what price (in {}/{}) do you want to sell?").format(
            order["buy"], order["sell"]
        )
        callback_command = "sell"

    buttons = await inline_control_buttons()
    callback_data = f"price {callback_command}"
    buttons.insert(
        0, [InlineKeyboardButton(_("Invert"), callback_data=callback_data)],
    )
    await tg.edit_message_text(
        answer,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("price "), state=OrderCreation.price
)
async def invert_price(call: types.CallbackQuery):
    """Change currency of price."""
    price_currency = call.data.split()[1]
    order = await database.creation.find_one_and_update(
        {"user_id": call.from_user.id}, {"$set": {"price_currency": price_currency}}
    )
    await price_ask(call, order, price_currency)


@state_handler(OrderCreation.price)
async def price_handler(call: types.CallbackQuery):
    """Ask for price."""
    order = await database.creation.find_one({"user_id": call.from_user.id})
    if not order:
        await call.answer(_("You are not creating order."))
        return True

    price_currency = order.get("price_currency")
    if not price_currency:
        price_currency = "sell"
        await database.creation.update_one(
            {"_id": order["_id"]}, {"$set": {"price_currency": price_currency}}
        )
    await price_ask(call, order, price_currency)


@private_handler(state=OrderCreation.price)
async def choose_price(message: types.Message, state: FSMContext):
    """Set price and ask for sum currency."""
    try:
        price = money(message.text)
    except MoneyValueError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.creation.find_one({"user_id": message.from_user.id})
    if order["price_currency"] == "sell":
        update_dict = {
            "price_sell": Decimal128(price),
            "price_buy": Decimal128(normalize(Decimal(1) / price)),
        }
    else:
        update_dict = {
            "price_buy": Decimal128(price),
            "price_sell": Decimal128(normalize(Decimal(1) / price)),
        }

    order = await database.creation.find_one_and_update(
        {"user_id": message.from_user.id},
        {"$set": update_dict, "$unset": {"price_currency": True}},
        return_document=ReturnDocument.AFTER,
    )

    await OrderCreation.amount.set()

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(order["buy"], callback_data="sum buy"),
        InlineKeyboardButton(order["sell"], callback_data="sum sell"),
    )
    for row in await inline_control_buttons():
        keyboard.row(*row)

    await tg.send_message(
        message.chat.id, _("Choose currency of order sum."), reply_markup=keyboard
    )


@state_handler(OrderCreation.amount)
async def sum_handler(call: types.CallbackQuery):
    """Ask for sum currency."""
    order = await database.creation.find_one_and_update(
        {"user_id": call.from_user.id}, {"$unset": {"price_currency": True}}
    )

    if not order:
        await call.answer(_("You are not creating order."))
        return True

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(order["buy"], callback_data="sum buy"),
        InlineKeyboardButton(order["sell"], callback_data="sum sell"),
    )
    for row in await inline_control_buttons():
        keyboard.row(*row)

    await tg.edit_message_text(
        _("Choose currency of order sum."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
    )


@dp.callback_query_handler(
    lambda call: call.data.startswith("sum "), state=OrderCreation.amount
)
async def choose_sum_currency(call: types.CallbackQuery):
    """Set sum currency and ask for sum in that currency."""
    sum_currency = call.data.split()[1]
    order = await database.creation.find_one_and_update(
        {"user_id": call.from_user.id}, {"$set": {"sum_currency": sum_currency}}
    )
    await call.answer()
    await tg.send_message(
        call.message.chat.id, _("Send order sum in {}.").format(order[sum_currency])
    )


@private_handler(state=OrderCreation.amount)
async def choose_sum(message: types.Message, state: FSMContext):
    """Set sum.

    If price and sum in another currency were not specified, ask for
    sum in another currency. Otherwise calculate it if price was
    specified, and, finally, ask for cashless payment system.
    """
    try:
        transaction_sum = money(message.text)
    except MoneyValueError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.creation.find_one(
        {"user_id": message.from_user.id, "sum_currency": {"$exists": True}}
    )
    if not order:
        await tg.send_message(
            message.chat.id, _("Choose currency of sum with buttons.")
        )
        return

    update_dict = {"sum_" + order["sum_currency"]: Decimal128(transaction_sum)}

    new_sum_currency = "sell" if order["sum_currency"] == "buy" else "buy"
    sum_field = f"sum_{new_sum_currency}"
    price_field = f"price_{new_sum_currency}"

    if price_field in order:
        update_dict[sum_field] = Decimal128(
            normalize(transaction_sum * order[price_field].to_decimal())
        )
    elif sum_field not in order:
        update_dict["sum_currency"] = new_sum_currency
        await database.creation.update_one({"_id": order["_id"]}, {"$set": update_dict})
        await tg.send_message(
            message.chat.id,
            _("Send order sum in {}.").format(order[update_dict["sum_currency"]]),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=await inline_control_buttons(back=False)
            ),
        )
        return

    await database.creation.update_one({"_id": order["_id"]}, {"$set": update_dict})
    await OrderCreation.payment_system.set()
    await tg.send_message(
        message.chat.id,
        _("Send cashless payment system."),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.payment_system)
async def payment_system_handler(call: types.CallbackQuery):
    """Ask for cashless payment system."""
    await tg.edit_message_text(
        _("Send cashless payment system."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@private_handler(state=OrderCreation.payment_system)
async def choose_payment_system(message: types.Message, state: FSMContext):
    """Set payment system and ask for location."""
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

    await database.creation.update_one(
        {"user_id": message.from_user.id}, {"$set": {"payment_system": payment_system}}
    )
    await OrderCreation.location.set()
    await tg.send_message(
        message.chat.id,
        _("Send location of a preferred meeting point for cash payment."),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.location)
async def location_handler(call: types.CallbackQuery):
    """Ask for location."""
    await tg.edit_message_text(
        _("Send location of a preferred meeting point for cash payment."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@private_handler(state=OrderCreation.location, content_types=ContentType.TEXT)
async def text_location(message: types.Message, state: FSMContext):
    """Find location by name.

    If there is only one option, set it and ask for duration. Otherwise
    send a list of these options for user to choose.
    """
    query = message.text

    language = i18n.ctx_locale.get()
    location_cache = await database.locations.find_one({"q": query, "lang": language})

    if location_cache:
        results = location_cache["results"]
    else:
        params = {"q": query, "format": "json", "accept-language": language}
        request = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": "TellerBot"},
        )

        results = [
            {
                "display_name": result["display_name"],
                "lat": result["lat"],
                "lon": result["lon"],
            }
            for result in request.json()[:10]
        ]

        # Cache results to reduce dublicate requests
        await database.locations.insert_one(
            {
                "q": query,
                "lang": language,
                "results": results,
                "date": datetime.utcnow(),
            }
        )

    if not results:
        await tg.send_message(message.chat.id, _("Location is not found."))
        return

    if len(results) == 1:
        location = results[0]
        await database.creation.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"lat": float(location["lat"]), "lon": float(location["lon"])}},
        )
        await OrderCreation.duration.set()
        await tg.send_message(
            message.chat.id,
            _("Send duration of order in days."),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=await inline_control_buttons()
            ),
        )
        return

    keyboard = InlineKeyboardMarkup(row_width=5)

    answer = _("Choose one of these locations:") + "\n\n"
    buttons = []
    for i, result in enumerate(results):
        answer += "{}. {}\n".format(i + 1, result["display_name"])
        buttons.append(
            InlineKeyboardButton(
                f"{i + 1}",
                callback_data="location {} {}".format(result["lat"], result["lon"]),
            )
        )
    keyboard.add(*buttons)

    await tg.send_message(message.chat.id, answer, reply_markup=keyboard)


@dp.callback_query_handler(
    lambda call: call.data.startswith("location "), state=OrderCreation.location
)
async def geocoded_location(call: types.CallbackQuery):
    """Choose location from list of options and ask for duration."""
    latitude, longitude = call.data.split()[1:]
    await database.creation.update_one(
        {"user_id": call.from_user.id},
        {"$set": {"lat": float(latitude), "lon": float(longitude)}},
    )
    await OrderCreation.duration.set()
    await call.answer()
    await duration_handler(call)


@private_handler(state=OrderCreation.location, content_types=ContentType.LOCATION)
async def choose_location(message: types.Message, state: FSMContext):
    """Set location from Telegram object and ask for duration."""
    location = message.location
    await database.creation.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"lat": location.latitude, "lon": location.longitude}},
    )
    await OrderCreation.duration.set()
    await tg.send_message(
        message.chat.id,
        _("Send duration of order in days."),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.duration)
async def duration_handler(call: types.CallbackQuery):
    """Ask for duration."""
    await tg.edit_message_text(
        _("Send duration of order in days."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@private_handler(state=OrderCreation.duration)
async def choose_duration(message: types.Message, state: FSMContext):
    """Set duration and ask for comments."""
    try:
        duration = int(message.text)
        if duration <= 0:
            raise ValueError
    except ValueError:
        await tg.send_message(message.chat.id, _("Send natural number."))
        return

    if duration <= 100000:  # More than ~274 years is practically non-expiring
        await database.creation.update_one(
            {"user_id": message.from_user.id}, {"$set": {"duration": duration}}
        )

    await OrderCreation.comments.set()
    await tg.send_message(
        message.chat.id,
        _("Add any additional comments."),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


async def set_order(order: MutableMapping[str, Any], chat_id: int):
    """Set missing values and finish order creation."""
    order["start_time"] = time()
    if "duration" in order:
        order["expiration_time"] = time() + order["duration"] * 24 * 60 * 60
        order["notify"] = True
    if "price_sell" not in order and "sum_buy" in order and "sum_sell" in order:
        order["price_sell"] = Decimal128(
            normalize(order["sum_sell"].to_decimal() / order["sum_buy"].to_decimal())
        )
        order["price_buy"] = Decimal128(
            normalize(order["sum_buy"].to_decimal() / order["sum_sell"].to_decimal())
        )

    inserted_order = await database.orders.insert_one(order)
    order["_id"] = inserted_order.inserted_id
    await tg.send_message(chat_id, _("Order is set."), reply_markup=start_keyboard())
    await show_order(order, chat_id, order["user_id"], show_id=True)
    asyncio.create_task(order_notification(order))


@state_handler(OrderCreation.comments)
async def comment_handler(call: types.CallbackQuery):
    """Ask for comments."""
    await tg.edit_message_text(
        _("Add any additional comments."),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@private_handler(state=OrderCreation.comments)
async def choose_comments(message: types.Message, state: FSMContext):
    """Set comments and finish order creation."""
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

    order = await database.creation.find_one_and_delete(
        {"user_id": message.from_user.id}
    )
    if order:
        order["comments"] = comments
        await set_order(order, message.chat.id)
    await state.finish()


@state_handler(OrderCreation.set_order)
async def choose_comments_handler(call: types.CallbackQuery):
    """Finish order creation."""
    order = await database.creation.find_one_and_delete({"user_id": call.from_user.id})
    await call.answer()
    if order:
        await set_order(order, call.message.chat.id)
    await dp.get_current().current_state().finish()
