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
from aiogram.utils.emoji import emojize
from bson.decimal128 import Decimal128
from pymongo import ReturnDocument

from src import whitelist
from src.bot import dp
from src.bot import tg
from src.config import config
from src.database import database
from src.handlers.base import inline_control_buttons
from src.handlers.base import private_handler
from src.handlers.base import show_order
from src.handlers.base import start_keyboard
from src.handlers.base import state_handler
from src.handlers.base import state_handlers
from src.i18n import i18n
from src.money import money
from src.money import MoneyValueError
from src.money import normalize
from src.notifications import order_notification
from src.states import OrderCreation


CURRENCY_REGEXP = re.compile(r"^(?:([A-Z]+)\.)?([A-Z]+)$")


@dp.callback_query_handler(lambda call: call.data.startswith("state "), state=any_state)
async def change_state(call: types.CallbackQuery, state: FSMContext):
    """React to back/skip button query."""
    args = call.data.split()
    query_state_name = args[1]
    direction = args[2]

    state_name = await state.get_state()
    if state_name != query_state_name:
        return await call.answer(i18n("wrong_button"))

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
        answer = i18n("back_error")
    elif direction == "skip":
        answer = i18n("skip_error")
    return await call.answer(answer)


async def cancel_order_creation(user_id: int, chat_id: int):
    """Cancel order creation."""
    await dp.current_state().finish()

    order = await database.creation.delete_one({"user_id": user_id})
    if not order.deleted_count:
        await tg.send_message(
            chat_id,
            i18n("no_creation"),
            reply_markup=start_keyboard(),
        )
        return True

    await tg.send_message(
        chat_id, i18n("order_cancelled"), reply_markup=start_keyboard()
    )


@dp.callback_query_handler(lambda call: call.data == "cancel", state=any_state)
async def cancel_button(call: types.CallbackQuery, state: FSMContext):
    """React to cancel button."""
    await call.answer()
    await cancel_order_creation(call.from_user.id, call.message.chat.id)


async def get_currency_with_gateway(currency_type: str, message: types.Message):
    """Try to append gateway from message text to currency."""
    gateway = message.text.upper()

    if len(gateway) >= 20:
        await tg.send_message(
            message.chat.id,
            i18n("exceeded_character_limit {limit} {sent}").format(
                limit=20, sent=len(gateway)
            ),
        )
        return None

    if any(ch < "A" or ch > "Z" for ch in gateway):
        await tg.send_message(message.chat.id, i18n("non_latin_characters_gateway"))
        return None

    order = await database.creation.find_one({"user_id": message.from_user.id})
    if gateway not in whitelist.CRYPTOCURRENCY[order[currency_type]]:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton(
                i18n("request_whitelisting"),
                callback_data="whitelisting_request {}.{}".format(
                    gateway, order[currency_type]
                ),
            )
        )
        keyboard.row(InlineKeyboardButton(i18n("cancel"), callback_data="cancel"))
        await tg.send_message(
            message.chat.id,
            i18n("gateway_not_whitelisted {currency}").format(
                currency=order[currency_type]
            ),
            reply_markup=keyboard,
        )
        return False

    return order, gateway + "." + order[currency_type]


async def match_currency(currency_type: str, message: types.Message):
    """Match message text with currency pattern."""
    text = message.text.upper()

    if len(text) >= 20:
        await tg.send_message(
            message.chat.id,
            i18n("exceeded_character_limit {limit} {sent}").format(
                limit=20, sent=len(text)
            ),
        )
        return None

    match = CURRENCY_REGEXP.match(text)
    if not match:
        await tg.send_message(message.chat.id, i18n("non_latin_characters_currency"))
        return None

    whitelisting_request_answer = None
    gateway, currency = match.groups()
    if currency in whitelist.FIAT:
        if gateway is not None:
            await tg.send_message(message.chat.id, i18n("no_fiat_gateway"))
            return None
    elif currency in whitelist.CRYPTOCURRENCY:
        gateways = whitelist.CRYPTOCURRENCY[currency]
        if gateway is None:
            if gateways:
                await database.creation.update_one(
                    {"user_id": message.from_user.id},
                    {"$set": {currency_type: currency}},
                )
                await tg.send_message(
                    message.chat.id,
                    i18n("choose_gateway {currency}").format(currency=currency),
                    reply_markup=whitelist.gateway_keyboard(currency, currency_type),
                )
                await OrderCreation.next()
                return None
        elif gateway not in gateways:
            whitelisting_request_answer = i18n(
                "gateway_not_whitelisted {currency}"
            ).format(currency=currency)
    else:
        whitelisting_request_answer = i18n("currency_not_whitelisted")

    if whitelisting_request_answer is not None:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton(
                i18n("request_whitelisting"),
                callback_data=f"whitelisting_request {match.group(0)}",
            )
        )
        keyboard.row(InlineKeyboardButton(i18n("cancel"), callback_data="cancel"))
        await tg.send_message(
            message.chat.id, whitelisting_request_answer, reply_markup=keyboard
        )
        return None

    return f"{gateway}.{currency}" if gateway else currency


@dp.callback_query_handler(
    lambda call: call.data.startswith("whitelisting_request "), state=any_state
)
async def whitelisting_request(call: types.CallbackQuery):
    """Send whitelisting request to support or increment requests count."""
    currency = call.data.split()[1]
    request = await database.whitelisting_requests.find_one_and_update(
        {"_id": currency},
        {"$addToSet": {"users": call.from_user.id}},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )

    double_request = False
    if request:
        if call.from_user.id in request["users"]:
            double_request = True
        else:
            support_text = emojize(":label: #whitelisting_request {} - {}.").format(
                currency, len(request["users"]) + 1
            )
            if len(request["users"]) == 1:
                message = await tg.send_message(config.SUPPORT_CHAT_ID, support_text)
                await database.whitelisting_requests.update_one(
                    {"_id": request["_id"]},
                    {"$set": {"message_id": message.message_id}},
                )
            else:
                await tg.edit_message_text(
                    support_text,
                    config.SUPPORT_CHAT_ID,
                    request["message_id"],
                )

    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        i18n("double_request") if double_request else i18n("request_sent"),
    )


@private_handler(state=OrderCreation.buy)
async def choose_buy(message: types.Message, state: FSMContext):
    """Set currency user wants to buy and ask for one they want to sell."""
    if message.text.startswith(emojize(":x:")):
        await cancel_order_creation(message.from_user.id, message.chat.id)
        return

    match = await match_currency("buy", message)
    if not match:
        return

    await database.creation.update_one(
        {"user_id": message.from_user.id}, {"$set": {"buy": match}}
    )
    await OrderCreation.sell.set()
    await tg.send_message(
        message.chat.id,
        i18n("ask_sell_currency"),
        reply_markup=whitelist.currency_keyboard("sell"),
    )


@private_handler(state=OrderCreation.buy_gateway)
async def choose_buy_gateway(message: types.Message, state: FSMContext):
    """Set gateway of buy currency and ask for sell currency."""
    if message.text.startswith(emojize(":fast_reverse_button:")):
        await OrderCreation.previous()
        await tg.send_message(
            message.chat.id,
            i18n("ask_buy_currency"),
            reply_markup=whitelist.currency_keyboard("buy"),
        )
        return
    elif message.text.startswith(emojize(":x:")):
        await cancel_order_creation(message.from_user.id, message.chat.id)
        return
    elif not message.text.startswith(emojize(":fast_forward:")):
        gateway_result = await get_currency_with_gateway("buy", message)
        if not gateway_result:
            return
        order, currency = gateway_result
        await database.creation.update_one(
            {"_id": order["_id"]}, {"$set": {"buy": currency}}
        )

    await OrderCreation.sell.set()
    await tg.send_message(
        message.chat.id,
        i18n("ask_sell_currency"),
        reply_markup=whitelist.currency_keyboard("sell"),
    )


async def set_price_state(message: types.Message, order: Mapping[str, Any]):
    """Ask for price."""
    await OrderCreation.price.set()
    buttons = await inline_control_buttons(back=False)
    buttons.insert(0, [InlineKeyboardButton(i18n("invert"), callback_data="price buy")])
    await tg.send_message(
        message.chat.id,
        i18n("ask_buy_price {of_currency} {per_currency}").format(
            of_currency=order["sell"], per_currency=order["buy"]
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@private_handler(state=OrderCreation.sell)
async def choose_sell(message: types.Message, state: FSMContext):
    """Set currency user wants to sell and ask for price."""
    if message.text.startswith(emojize(":fast_reverse_button:")):
        await OrderCreation.buy.set()
        await tg.send_message(
            message.chat.id,
            i18n("ask_buy_currency"),
            reply_markup=whitelist.currency_keyboard("buy"),
        )
        return
    elif message.text.startswith(emojize(":x:")):
        await cancel_order_creation(message.from_user.id, message.chat.id)
        return

    match = await match_currency("sell", message)
    if not match:
        return

    order = await database.creation.find_one_and_update(
        {"user_id": message.from_user.id, "buy": {"$ne": match}},
        {"$set": {"sell": match, "price_currency": "sell"}},
        return_document=ReturnDocument.AFTER,
    )
    if not order:
        await tg.send_message(
            message.chat.id,
            i18n("same_currency_error"),
            reply_markup=whitelist.currency_keyboard("sell"),
        )
        return

    await set_price_state(message, order)


@private_handler(state=OrderCreation.sell_gateway)
async def choose_sell_gateway(message: types.Message, state: FSMContext):
    """Set gateway of sell currency and ask for price."""
    if message.text.startswith(emojize(":fast_reverse_button:")):
        await OrderCreation.previous()
        await tg.send_message(
            message.chat.id,
            i18n("ask_sell_currency"),
            reply_markup=whitelist.currency_keyboard("sell"),
        )
        return
    elif message.text.startswith(emojize(":x:")):
        await cancel_order_creation(message.from_user.id, message.chat.id)
        return

    same_gateway = False
    if not message.text.startswith(emojize(":fast_forward:")):
        gateway_result = await get_currency_with_gateway("sell", message)
        if not gateway_result:
            return
        order, currency = gateway_result
        if currency == order["buy"]:
            same_gateway = True
        else:
            await database.creation.update_one(
                {"_id": order["_id"]},
                {"$set": {"sell": currency, "price_currency": "sell"}},
            )
    else:
        order = await database.creation.find_one_and_update(
            {"user_id": message.from_user.id, "$expr": {"$ne": ["$buy", "$sell"]}},
            {"$set": {"price_currency": "sell"}},
            return_document=ReturnDocument.AFTER,
        )
        if not order:
            order = await database.creation.find_one({"user_id": message.from_user.id})
            same_gateway = True

    if same_gateway:
        await tg.send_message(
            message.chat.id,
            i18n("same_gateway_error"),
            reply_markup=whitelist.gateway_keyboard(order["sell"], "sell"),
        )
    else:
        await set_price_state(message, order)


async def price_ask(
    call: types.CallbackQuery, order: Mapping[str, Any], price_currency: str
):
    """Edit currency of price in message to ``price_currency`` field value."""
    if price_currency == "sell":
        answer = i18n("ask_buy_price {of_currency} {per_currency}").format(
            of_currency=order["sell"], per_currency=order["buy"]
        )
        callback_command = "buy"
    else:
        answer = i18n("ask_sell_price {of_currency} {per_currency}").format(
            of_currency=order["buy"], per_currency=order["sell"]
        )
        callback_command = "sell"

    buttons = await inline_control_buttons()
    callback_data = f"price {callback_command}"
    buttons.insert(
        0,
        [InlineKeyboardButton(i18n("invert"), callback_data=callback_data)],
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
        await call.answer(i18n("no_creation"))
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
        message.chat.id, i18n("ask_sum_currency"), reply_markup=keyboard
    )


@state_handler(OrderCreation.amount)
async def sum_handler(call: types.CallbackQuery):
    """Ask for sum currency."""
    order = await database.creation.find_one_and_update(
        {"user_id": call.from_user.id}, {"$unset": {"price_currency": True}}
    )

    if not order:
        await call.answer(i18n("no_creation"))
        return True

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(order["buy"], callback_data="sum buy"),
        InlineKeyboardButton(order["sell"], callback_data="sum sell"),
    )
    for row in await inline_control_buttons():
        keyboard.row(*row)

    await tg.edit_message_text(
        i18n("ask_sum_currency"),
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
        call.message.chat.id,
        i18n("ask_order_sum {currency}").format(currency=order[sum_currency]),
    )


@private_handler(state=OrderCreation.amount)
async def choose_sum(message: types.Message, state: FSMContext):
    """Set sum.

    If price and sum in another currency were not specified, ask for
    sum in another currency. Otherwise calculate it if price was
    specified, and, finally, ask for cashless payment system.
    """
    order = await database.creation.find_one({"user_id": message.from_user.id})
    if "sum_currency" not in order:
        currency = message.text.upper()
        if currency == order["buy"]:
            sum_currency = "buy"
        elif currency == order["sell"]:
            sum_currency = "sell"
        else:
            await tg.send_message(
                message.chat.id, i18n("choose_sum_currency_with_buttons")
            )
            return
        await database.creation.update_one(
            {"_id": order["_id"]}, {"$set": {"sum_currency": sum_currency}}
        )
        await tg.send_message(
            message.chat.id, i18n("ask_order_sum {currency}").format(currency=currency)
        )
        return

    try:
        transaction_sum = money(message.text)
    except MoneyValueError as exception:
        await tg.send_message(message.chat.id, str(exception))
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
            i18n("ask_order_sum {currency}").format(
                currency=order[update_dict["sum_currency"]]
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=await inline_control_buttons(back=False)
            ),
        )
        return

    await database.creation.update_one({"_id": order["_id"]}, {"$set": update_dict})
    if order["buy"] not in whitelist.FIAT and order["sell"] not in whitelist.FIAT:
        await OrderCreation.location.set()
        await tg.send_message(
            message.chat.id,
            i18n("ask_location"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=await inline_control_buttons()
            ),
        )
        return
    await OrderCreation.payment_system.set()
    await tg.send_message(
        message.chat.id,
        i18n("cashless_payment_system"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.payment_system)
async def payment_system_handler(call: types.CallbackQuery):
    """Ask for cashless payment system."""
    direction = call.data.split()[2]
    order = await database.creation.find_one({"user_id": call.from_user.id})
    if order["buy"] not in whitelist.FIAT and order["sell"] not in whitelist.FIAT:
        if direction == "back":
            state = await OrderCreation.previous()
        elif direction == "skip":
            state = await OrderCreation.next()
        return await state_handlers[state](call)
    await tg.edit_message_text(
        i18n("cashless_payment_system"),
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
            i18n("exceeded_character_limit {limit} {sent}").format(
                limit=150, sent=len(payment_system)
            ),
        )
        return

    await database.creation.update_one(
        {"user_id": message.from_user.id}, {"$set": {"payment_system": payment_system}}
    )
    await OrderCreation.location.set()
    await tg.send_message(
        message.chat.id,
        i18n("ask_location"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.location)
async def location_handler(call: types.CallbackQuery):
    """Ask for location."""
    await tg.edit_message_text(
        i18n("ask_location"),
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
        await tg.send_message(message.chat.id, i18n("location_not_found"))
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
            i18n("ask_duration {limit}").format(limit=config.ORDER_DURATION_LIMIT),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=await inline_control_buttons()
            ),
        )
        return

    keyboard = InlineKeyboardMarkup(row_width=5)

    answer = i18n("choose_location") + "\n\n"
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
        i18n("ask_duration {limit}").format(limit=config.ORDER_DURATION_LIMIT),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


@state_handler(OrderCreation.duration)
async def duration_handler(call: types.CallbackQuery):
    """Ask for duration."""
    await tg.edit_message_text(
        i18n("ask_duration {limit}").format(limit=config.ORDER_DURATION_LIMIT),
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
        await tg.send_message(message.chat.id, i18n("send_natural_number"))
        return

    if duration > config.ORDER_DURATION_LIMIT:
        await tg.send_message(
            message.chat.id,
            i18n("exceeded_duration_limit {limit}").format(
                limit=config.ORDER_DURATION_LIMIT
            ),
        )
        return

    await database.creation.update_one(
        {"user_id": message.from_user.id}, {"$set": {"duration": duration}}
    )

    await OrderCreation.comments.set()
    await tg.send_message(
        message.chat.id,
        i18n("ask_comments"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons()
        ),
    )


async def set_order(order: MutableMapping[str, Any], chat_id: int):
    """Set missing values and finish order creation."""
    order["start_time"] = time()
    if "duration" not in order:
        order["duration"] = config.ORDER_DURATION_LIMIT
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
    await tg.send_message(chat_id, i18n("order_set"), reply_markup=start_keyboard())
    await show_order(order, chat_id, order["user_id"], show_id=True)
    asyncio.create_task(order_notification(order))


@state_handler(OrderCreation.comments)
async def comment_handler(call: types.CallbackQuery):
    """Ask for comments."""
    await tg.edit_message_text(
        i18n("ask_comments"),
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
            i18n("exceeded_character_limit {limit} {sent}").format(
                limit=150, sent=len(comments)
            ),
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
    await dp.current_state().finish()
