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
from .database import database

import re
import json
import asyncio

from aiogram import Bot, executor, types
from aiogram.dispatcher import Dispatcher
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.middlewares.i18n import I18nMiddleware


SETTINGS = [
    {'name': 'Payment methods', 'field': 'payment_methods', 'default': None},
    {'name': 'BitShares username', 'field': 'bitshares_username', 'default': None},
    # {'name': 'Order creation UI', 'field': 'order_creation_ui', 'default': 0}
]


bot = Bot(token=config.TOKEN, loop=asyncio.get_event_loop())
dp = Dispatcher(bot)


i18n = I18nMiddleware('bot', config.LOCALES_DIR)
dp.middleware.setup(i18n)
_ = i18n.gettext


class OrderCreation(StatesGroup):
    amount = State()


class Settings(StatesGroup):
    payment_methods = State()
    username = State()


def user_handler(handler):
    def decorator(obj, *args, **kwargs):
        if isinstance(obj, types.Message):
            user = database.users.find_one({'id': obj.chat.id})
        elif isinstance(obj, types.CallbackQuery) and obj.message:
            user = database.users.find_one({'id': obj.message.chat.id})

        return handler(obj, user, *args, **kwargs)
    return decorator


def private_handler(*args, **kwargs):
    def decorator(handler):
        new_handler = user_handler(handler)
        dp.register_message_handler(
            new_handler,
            lambda message: message.chat.type == types.ChatType.PRIVATE,
            *args, **kwargs
        )
        return new_handler
    return decorator


@private_handler(commands=['start', 'help'])
async def handle_start_command(message, user, *args, **kwargs):
    new_user = {}
    for setting in SETTINGS:
        new_user[setting['field']] = setting['default']
    database.users.update_one(
        {'id': message.from_user.id},
        {'$setOnInsert': new_user},
        upsert=True
    )
    keyboard = types.ReplyKeyboardMarkup(row_width=2)
    keyboard.add(
        types.KeyboardButton('\U0001f4bb ' + _('Buy')),
        types.KeyboardButton('\U0001f4b5 ' + _('Sell')),
        types.KeyboardButton('\u2699\ufe0f ' + _('Settings'))
    )
    await bot.send_message(
        message.chat.id,
        _("Hello, I'm BailsBot and I can help you meet with people that you "
          "can swap money with.\n\nChoose one of the options on your keyboard."),
        reply_markup=keyboard
    )


async def orders_list(chat_id, start, count=10):
    orders = database.orders.find()[start:start + count]
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(text='\u2b05\ufe0f', callback_data='orders {}'.format(start - count)),
        types.InlineKeyboardButton(text='\u27a1\ufe0f', callback_data='orders {}'.format(start + count))
    )
    await bot.send_message(
        chat_id,
        '\n'.join([
            '{}. {} - {:.2f}'.format(start + i + 1, order['username'], order['amount'])
            for i, order in enumerate(orders)
        ]),
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda call: call.data.startswith('orders'))
@user_handler
async def orders_button(call, user, *args, **kwargs):
    start = max(0, int(call.data.split()[1]))

    if start >= database.orders.count_documents({}):
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no more orders.")
        )
        return

    await orders_list(call.message.chat.id, start)


@private_handler(commands=['buy'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4bb')
)
async def handle_buy(message, user, *args, **kwargs):
    if database.orders.count_documents({}) == 0:
        await bot.send_message(message.chat.id, _("There are no orders."))
        return
    await orders_list(message.chat.id, 0)


@private_handler(state=OrderCreation.amount)
async def choose_amount(message, user, state, **kwargs):
    try:
        amount = float(message.text)
    except ValueError:
        await bot.send_message(message.chat.id, _("Send decimal number or /cancel"))
        return
    if amount <= 0:
        await bot.send_message(message.chat.id, _("Send positive number or /cancel"))
        return

    database.orders.update_one(
        {'_id': user['order']},
        {'$set': {'amount': amount}}
    )
    database.users.update_one(
        {'_id': user['_id']},
        {'$unset': {'order': True}}
    )
    await state.finish()
    await bot.send_message(message.chat.id, _('Order is set.'))


@private_handler(commands=['sell'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4b5')
)
async def handle_sell(message, user, *args, **kwargs):
    username = user.get('username')
    if not username:
        await bot.send_message(
            message.chat.id,
            _("Set Bitshares username in settings first.")
        )
        return
    doc = database.orders.insert_one({
        'amount': 0.0,
        'comission': 0.0,
        'payment_methods': user['payment_methods'],
        'date': message.date,
        'expiration_time': 0,
        'username': user['username'],
    })
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'order': doc.inserted_id}}
    )
    reply = await bot.send_message(
        message.chat.id,
        _("How many BTS are you selling?")
    )
    await OrderCreation.amount.set()


@private_handler(state='*', commands=['cancel'])
async def cancel_sell(message, user, state, **kwargs):
    database.users.update_one(
        {'_id': user['_id']},
        {'$unset': {'order': True}}
    )
    await bot.send_message(message.chat.id, _('Order is cancelled.'))


@private_handler(state=Settings.payment_methods)
async def choose_payment_methods(message, user, state, **kwargs):
    chosen_methods = None
    if message.text:
        chosen_methods = map(int, re.findall(r'(?:\b(\d+)\b)+', message.text))
    if not chosen_methods:
        await bot.send_message(
            message.chat.id,
            _('You need to send text message with space-separated numbers '
              'corresponding to payment methods.')
        )
    with open(config.METHODS_JSON, 'r') as methods_json:
        methods = json.load(methods_json)
    answer = ''
    changes = []
    pulls = []
    pushes = []
    for pivot, method_index in enumerate(sorted(chosen_methods)):
        if method_index > len(methods):
            remaining = len(chosen_methods) - pivot
            answer += _("Some numbers were ignored as they don't correspond to any payment method.") % (remaining) + '\n\n'
            break
        method = methods[method_index - 1]
        if method in user['payment_methods']:
            pulls.append(method['name'])
            changes.append(['{}. \u274c {}'.format(method_index, method['name'])])
        else:
            pushes.append(method['name'])
            changes.append(['{}. \u2714\ufe0f {}'.format(method_index, method['name'])])
    database.users.update_one(
        {'_id': user['_id']},
        {'$pull': {'payment_methods': {'$in': pulls}},
         '$push': {'payment_methods': {'$each': pushes}}}
    )
    answer += _('Preference of these payment methods were changed:') + '\n' + '\n'.join(changes)
    await state.finish()
    await bot.send_message(message.chat.id, answer)


@dp.callback_query_handler(lambda call: call.data == 'payment method')
@user_handler
async def settings_payment_methods(call, user, *args, **kwargs):
    with open(config.METHODS_JSON, 'r') as methods_json:
        methods = json.load(methods_json)
    user = database.users.find_one({'id': call.from_user.id})
    method_list = ['{}. {} {}'.format(
        i + 1,
        '\u2714\ufe0f' if method['name'] in user['payment_methods'] else '\u274c',
        method['name']
    ) for i, method in enumerate(methods)]
    reply = await bot.send_message(
        call.chat.id,
        _('Send space-separated numbers corresponding to payment methods from list:') +
        '\n\n' + '\n'.join(method_list)
    )
    await Settings.payment_methods.set()


@private_handler(state=Settings.username)
async def set_username(message, user, state, **kwargs):
    username = message.text
    if not username:
        await bot.send_message(message.chat.id, 'This is not a valid username.')
        return
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'username': username}}
    )
    await state.finish()
    await bot.send_message(message.chat.id, 'Username set.')


@dp.callback_query_handler(lambda call: call.data == 'bitshares username')
@user_handler
async def settings_username(call, user, *args, **kwargs):
    reply = await bot.send_message(
        call.message.chat.id,
        'Send your Bitshares username.'
    )
    await Settings.username.set()


@dp.callback_query_handler(lambda call: call.data == 'order creation ui')
@user_handler
async def settings_order_creation_ui(call, user, *args, **kwargs):
    order_ui = 1 - user['order_creation_id']
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'order_creation_ui': order_ui}}
    )
    await bot.send_message(
        call.chat.id,
        _('Your order creation UI is now set to') + ' ' +
        _('visual') if order_ui else _('conversational') + '.'
    )


@private_handler(commands=['settings'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\u2699\\ufe0f')
)
async def handle_settings(message, user, *args, **kwargs):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        *[types.InlineKeyboardButton(text=_(setting['name']), callback_data=setting['name'].lower())
          for setting in SETTINGS]
    )
    user_info = []
    for setting in SETTINGS:
        option = user.get(setting['field'])
        if option is None:
            option = '\U0001f6ab'
        user_info.append('{}: {}'.format(_(setting['name']), option))
    await bot.send_message(
        message.chat.id,
        _('Choose which option you would like to change.') + '\n\n' +
        '\n'.join(user_info),
        reply_markup=keyboard
    )


@private_handler()
async def handle_default(message, user, *args, **kwargs):
    await bot.send_message(message.chat.id, _('Unknown command.'))
