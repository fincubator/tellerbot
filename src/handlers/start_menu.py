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
"""Handlers for start menu."""
import re
import typing
from time import time

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import any_state
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.emoji import emojize
from babel import Locale
from pymongo import DESCENDING

from src import states
from src.bot import tg
from src.config import Config
from src.database import database
from src.handlers.base import help_message
from src.handlers.base import inline_control_buttons
from src.handlers.base import orders_list
from src.handlers.base import private_handler
from src.handlers.base import start_keyboard
from src.i18n import _
from src.i18n import i18n


@private_handler(commands=["start"], state=any_state)
async def handle_start_command(message: types.Message, state: FSMContext):
    """Handle /start.

    Ask for language if user is new or show menu.
    """
    user = {"id": message.from_user.id, "chat": message.chat.id}
    result = await database.users.update_one(user, {"$setOnInsert": user}, upsert=True)

    if not result.matched_count:
        keyboard = InlineKeyboardMarkup()
        for language in i18n.available_locales:
            keyboard.row(
                InlineKeyboardButton(
                    Locale(language).display_name,
                    callback_data="locale {}".format(language),
                )
            )
        await tg.send_message(
            message.chat.id, _("Please, choose your language."), reply_markup=keyboard
        )
        return

    await state.finish()
    await tg.send_message(
        message.chat.id, help_message(), reply_markup=start_keyboard()
    )


@private_handler(commands=["create"], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(":heavy_plus_sign:")), state=any_state
)
async def handle_create(message: types.Message, state: FSMContext):
    """Start order creation by asking user for currency they want to buy."""
    current_time = time()
    user_orders = await database.orders.count_documents(
        {
            "user_id": message.from_user.id,
            "start_time": {"$gt": current_time - Config.ORDERS_LIMIT_HOURS * 3600},
        }
    )
    if user_orders >= Config.ORDERS_LIMIT_COUNT:
        await tg.send_message(
            message.chat.id,
            _("You can't create more than {} orders in {} hours.").format(
                Config.ORDERS_LIMIT_COUNT, Config.ORDERS_LIMIT_HOURS
            ),
        )
        return

    creation = {"user_id": message.from_user.id}
    await database.creation.find_one_and_replace(creation, creation)

    await tg.send_message(
        message.chat.id,
        _("What currency do you want to buy?"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=await inline_control_buttons(back=False, skip=False)
        ),
    )


@private_handler(commands=["book"], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(":closed_book:")), state=any_state
)
async def handle_book(
    message: types.Message,
    state: FSMContext,
    command: typing.Optional[Command.CommandObj] = None,
):
    r"""Show order book with specified currency pair.

    Currency pair is indicated with one or two space separated
    arguments after **/book** in message text. If two arguments are
    sent, then first is the currency order's creator wants to sell
    and second is the currency order's creator wants to buy. If one
    argument is sent, then it's any of the currencies in a pair.

    Any argument can be replaced with \*, which results in searching
    pairs with any currency in place of the wildcard.

    Examples:
        =============  =================================================
        Command        Description
        =============  =================================================
        /book BTC USD  Show orders that sell BTC and buy USD (BTC → USD)
        /book BTC *    Show orders that sell BTC and buy any currency
        /book * USD    Show orders that sell any currency and buy USD
        /book BTC      Show orders that sell or buy BTC
        /book * *      Equivalent to /book
        =============  =================================================

    """
    query = {
        "$or": [
            {"expiration_time": {"$exists": False}},
            {"expiration_time": {"$gt": time()}},
        ]
    }

    if command is not None:
        source = message.text.upper().split()
        if len(source) == 2:
            currency = source[1]
            if currency != "*":
                query = {
                    "$and": [query, {"$or": [{"sell": source[1]}, {"buy": source[1]}]}]
                }
        elif len(source) >= 3:
            sell, buy = source[1], source[2]
            if sell != "*":
                query["sell"] = sell
            if buy != "*":
                query["buy"] = buy

    cursor = database.orders.find(query).sort("start_time", DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(
        cursor, message.chat.id, 0, quantity, "orders", user_id=message.from_user.id
    )


@private_handler(commands=["my"], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(":bust_in_silhouette:")), state=any_state
)
async def handle_my_orders(message: types.Message, state: FSMContext):
    """Show user's orders."""
    query = {"user_id": message.from_user.id}
    cursor = database.orders.find(query).sort("start_time", DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(cursor, message.chat.id, 0, quantity, "my_orders")


@private_handler(commands=["locale"], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(":abcd:")), state=any_state)
async def choose_locale(message: types.Message):
    """Show list of languages."""
    keyboard = InlineKeyboardMarkup()
    for language in i18n.available_locales:
        keyboard.row(
            InlineKeyboardButton(
                Locale(language).display_name,
                callback_data="locale {}".format(language),
            )
        )
    await tg.send_message(
        message.chat.id, _("Choose your language."), reply_markup=keyboard
    )


@private_handler(commands=["help"], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(":question:")), state=any_state
)
async def help_command(message: types.Message):
    """Handle request to support."""
    await states.asking_support.set()
    await tg.send_message(
        message.chat.id,
        _("What's your question?"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(_("Cancel"), callback_data="unhelp")]
            ]
        ),
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
        else:
            mention_regexp = f"^{creator}$" if creator[0] == "@" else f"^@{creator}$"
            user = await database.users.find_one(
                {
                    "mention": re.compile(mention_regexp, re.IGNORECASE),
                    "has_username": True,
                }
            )
            query["user_id"] = user["id"]
    except IndexError:
        await tg.send_message(
            message.chat.id, _("Send username as an argument."),
        )
        return

    cursor = database.orders.find(query).sort("start_time", DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(
        cursor, message.chat.id, 0, quantity, "orders", user_id=message.from_user.id
    )


@private_handler(commands=["subscribe", "s"], state=any_state)
@private_handler(commands=["unsubscribe", "u"], state=any_state)
async def subcribe_to_pair(
    message: types.Message, state: FSMContext, command: Command.CommandObj,
):
    r"""Manage subscription to pairs.

    Currency pair is indicated with two space separated arguments
    after **/subscribe** or **/unsubscribe** in message text. First
    argument is the currency order's creator wants to sell and second
    is the currency order's creator wants to buy.

    Similarly to **/book**, any argument can be replaced with \*, which
    results in subscribing to pairs with any currency in place of the
    wildcard.

    Without arguments commands show list of user's subscriptions.
    """
    source = message.text.upper().split()

    if len(source) == 1:
        user = await database.subscriptions.find_one({"id": message.from_user.id})
        sublist = ""
        if user:
            for i, sub in enumerate(user["subscriptions"]):
                sublist += "\n{}. {} → {}".format(
                    i + 1,
                    sub["sell"] if sub["sell"] else "*",
                    sub["buy"] if sub["buy"] else "*",
                )
        if sublist:
            answer = _("Your subscriptions:") + sublist
        else:
            answer = _("You don't have subscriptions.")
        await tg.send_message(message.chat.id, answer, reply_markup=start_keyboard())
        return

    try:
        sell, buy = source[1], source[2]
        sub = {"sell": None, "buy": None}
        if sell != "*":
            sub["sell"] = sell
        if buy != "*":
            sub["buy"] = buy
    except IndexError:
        await tg.send_message(
            message.chat.id,
            _("Send currency or currency pair as an argument."),
            reply_markup=start_keyboard(),
        )
        return

    if command.command[0] == "s":
        update_result = await database.subscriptions.update_one(
            {"id": message.from_user.id},
            {
                "$setOnInsert": {"chat": message.chat.id},
                "$addToSet": {"subscriptions": sub},
            },
            upsert=True,
        )
        if not update_result.matched_count or update_result.modified_count:
            await tg.send_message(
                message.chat.id,
                _("Subscription is added."),
                reply_markup=start_keyboard(),
            )
        else:
            await tg.send_message(
                message.chat.id,
                _("Subscription already exists."),
                reply_markup=start_keyboard(),
            )
    elif command.command[0] == "u":
        delete_result = await database.subscriptions.update_one(
            {"id": message.from_user.id}, {"$pull": {"subscriptions": sub}}
        )
        if delete_result.modified_count:
            await tg.send_message(
                message.chat.id,
                _("Subscription is deleted."),
                reply_markup=start_keyboard(),
            )
        else:
            await tg.send_message(
                message.chat.id,
                _("Couldn't delete subscription."),
                reply_markup=start_keyboard(),
            )
    else:
        raise AssertionError(f"Unknown command: {command.command}")
