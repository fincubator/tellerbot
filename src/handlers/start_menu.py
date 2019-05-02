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


from time import time

from babel import Locale
from pymongo import DESCENDING

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils import markdown
from aiogram.utils.emoji import emojize

from . import tg, private_handler, start_keyboard, inline_control_buttons, help_message, orders_list
from ..database import database
from ..i18n import i18n, _
from .. import states


@private_handler(commands=['start'], state=any_state)
async def handle_start_command(message: types.Message, state: FSMContext):
    user = {'id': message.from_user.id, 'chat': message.chat.id}
    result = await database.users.update_one(
        user, {'$setOnInsert': user}, upsert=True
    )

    if not result.matched_count:
        keyboard = InlineKeyboardMarkup()
        for language in i18n.available_locales:
            keyboard.row(InlineKeyboardButton(
                Locale(language).display_name,
                callback_data='locale {}'.format(language)
            ))
        await tg.send_message(
            message.chat.id,
            _('Please, choose your language.'),
            reply_markup=keyboard
        )
        return

    await state.finish()
    await tg.send_message(
        message.chat.id, help_message(),
        reply_markup=start_keyboard()
    )


@private_handler(commands=['create'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':heavy_plus_sign:')), state=any_state)
async def handle_create(message: types.Message, state: FSMContext):
    if message.from_user.username:
        username = '@' + message.from_user.username
    else:
        username = markdown.link(message.from_user.full_name, message.from_user.url)

    await database.creation.insert_one({
        'user_id': message.from_user.id,
        'username': username
    })
    await states.OrderCreation.first()

    await tg.send_message(
        message.chat.id,
        _('What currency do you want to buy?'),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True, no_next=True)
        )
    )


@private_handler(commands=['book'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':closed_book:')), state=any_state)
async def handle_book(message: types.Message, state: FSMContext):
    query = {
        '$or': [
            {'expiration_time': {'$exists': False}},
            {'expiration_time': {'$gt': time()}}
        ]
    }
    cursor = database.orders.find(query).sort('start_time', DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(cursor, message.chat.id, 0, quantity, 'orders', user_id=message.from_user.id)


@private_handler(commands=['my'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':bust_in_silhouette:')), state=any_state)
async def handle_my_orders(message: types.Message, state: FSMContext):
    query = {'user_id': message.from_user.id}
    cursor = database.orders.find(query).sort('start_time', DESCENDING)
    quantity = await database.orders.count_documents(query)
    await state.finish()
    await orders_list(cursor, message.chat.id, 0, quantity, 'my_orders')


@private_handler(commands=['locale'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':abcd:')), state=any_state)
async def choose_locale(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    for language in i18n.available_locales:
        keyboard.row(InlineKeyboardButton(
            Locale(language).display_name,
            callback_data='locale {}'.format(language)
        ))
    await tg.send_message(
        message.chat.id,
        _('Choose your language.'),
        reply_markup=keyboard
    )


@private_handler(commands=['help'], state=any_state)
@private_handler(lambda msg: msg.text.startswith(emojize(':question:')), state=any_state)
async def help_command(message: types.Message):
    await states.asking_support.set()
    await tg.send_message(
        message.chat.id,
        _('Send your questions and feedback in the next message, '
          'and I will forward it to the support.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(_('Cancel'), callback_data='unhelp')
        ]])
    )
