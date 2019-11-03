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
from time import time

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.emoji import emojize
from babel import Locale
from pymongo import DESCENDING

from src import states
from src.config import ORDERS_LIMIT_COUNT
from src.config import ORDERS_LIMIT_HOURS
from src.database import database
from src.handlers import help_message
from src.handlers import inline_control_buttons
from src.handlers import orders_list
from src.handlers import private_handler
from src.handlers import start_keyboard
from src.handlers import tg
from src.i18n import _
from src.i18n import i18n


@private_handler(commands=['start'], state=any_state)
async def handle_start_command(message: types.Message, state: FSMContext):
    """Handle /start.

    Ask for language if user is new or show menu.
    """
    user = {'id': message.from_user.id, 'chat': message.chat.id}
    result = await database.users.update_one(user, {'$setOnInsert': user}, upsert=True)

    if not result.matched_count:
        keyboard = InlineKeyboardMarkup()
        for language in i18n.available_locales:
            keyboard.row(
                InlineKeyboardButton(
                    Locale(language).display_name,
                    callback_data='locale {}'.format(language),
                )
            )
        await tg.send_message(
            message.chat.id, _('Please, choose your language.'), reply_markup=keyboard
        )
        return

    await state.finish()
    await tg.send_message(
        message.chat.id, help_message(), reply_markup=start_keyboard()
    )


@private_handler(commands=['create'], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(':heavy_plus_sign:')), state=any_state
)
async def handle_create(message: types.Message, state: FSMContext):
    """Start order creation by asking user for currency they want to buy."""
    current_time = time()
    user_orders = await database.orders.count_documents(
        {
            'user_id': message.from_user.id,
            'start_time': {'$gt': current_time - ORDERS_LIMIT_HOURS * 3600},
        }
    )
    if user_orders >= ORDERS_LIMIT_COUNT:
        await tg.send_message(
            message.chat.id,
            _("You can't create more than {} orders in {} hours.").format(
                ORDERS_LIMIT_COUNT, ORDERS_LIMIT_HOURS
            ),
        )
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'mention': message.from_user.mention}},
        upsert=True,
    )
    await states.OrderCreation.first()

    await tg.send_message(
        message.chat.id,
        _('What currency do you want to buy?'),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True, no_next=True)
        ),
    )


@private_handler(commands=['book'], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(':closed_book:')), state=any_state
)
async def handle_book(message: types.Message, state: FSMContext):
    """Show order book."""
    query = {
        '$or': [
            {'expiration_time': {'$exists': False}},
            {'expiration_time': {'$gt': time()}},
        ]
    }
    cursor = database.orders.find(query).sort('start_time', DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(
        cursor, message.chat.id, 0, quantity, 'orders', user_id=message.from_user.id
    )


@private_handler(commands=['my'], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(':bust_in_silhouette:')), state=any_state
)
async def handle_my_orders(message: types.Message, state: FSMContext):
    """Show user's orders."""
    query = {'user_id': message.from_user.id}
    cursor = database.orders.find(query).sort('start_time', DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(cursor, message.chat.id, 0, quantity, 'my_orders')


@private_handler(commands=['locale'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':abcd:')), state=any_state)
async def choose_locale(message: types.Message):
    """Show list of languages."""
    keyboard = InlineKeyboardMarkup()
    for language in i18n.available_locales:
        keyboard.row(
            InlineKeyboardButton(
                Locale(language).display_name,
                callback_data='locale {}'.format(language),
            )
        )
    await tg.send_message(
        message.chat.id, _('Choose your language.'), reply_markup=keyboard
    )


@private_handler(commands=['help'], state=any_state)
@private_handler(
    lambda msg: msg.text.startswith(emojize(':question:')), state=any_state
)
async def help_command(message: types.Message):
    """Handle request to support."""
    await states.asking_support.set()
    await tg.send_message(
        message.chat.id,
        _("What's your question?"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(_('Cancel'), callback_data='unhelp')]
            ]
        ),
    )
