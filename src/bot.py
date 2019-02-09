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
from .locale import translations

import re
import json

import telebot
from telebot.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, InlineKeyboardButton, KeyboardButton, Message, CallbackQuery


bot = telebot.TeleBot(config.TOKEN)


SETTINGS = [
    {'name': 'Payment methods', 'field': 'payment_methods', 'default': None},
    {'name': 'BitShares username', 'field': 'bitshares_username', 'default': None},
    # {'name': 'Order creation UI', 'field': 'order_creation_ui', 'default': 0}
]


def translate_handler(handler):
    def lang_handler(obj):
        user = None
        domain = 'en'
        _ = lambda text: text

        if isinstance(obj, Message):
            user = database.users.find_one({'id': obj.chat.id})
        elif isinstance(obj, CallbackQuery) and obj.message:
            user = database.users.find_one({'id': obj.message.chat.id})

        if user:
            domain = user['language']

        if domain != 'us' and domain in translations:
            _ = lambda text: translations[domain].get(text, text)

        return handler(message, user, _)
    return lang_handler


def private_only(message):
    return message.chat.type == 'private'


def message_handler(func=None, **kwargs):
    def decorator(handler):
        conjuction = private_only if func is None else lambda message: private_only(message) and func(message)
        lang_handler = translate_handler(handler)
        handler_dict = bot._build_handler_dict(lang_handler, func=conjuction, **kwargs)
        bot.add_message_handler(handler_dict)
        return lang_handler
    return decorator


@message_handler(commands=['start', 'help'])
def handle_start_command(message, user, _):
    language_code = message.from_user.language_code
    if language_code is None:
        language_code = 'us'
    new_user = {
        'language': language_code
    }
    for setting in SETTINGS:
        new_user[setting['field']] = setting['default']
    database.users.update_one(
        {'id': message.from_user.id},
        {'$setOnInsert': new_user},
        upsert=True
    )
    keyboard = ReplyKeyboardMarkup(row_width=2)
    keyboard.add(
        KeyboardButton('\U0001f4bb ' + _('Buy')),
        KeyboardButton('\U0001f4b5 ' + _('Sell')),
        KeyboardButton('\u2699\ufe0f ' + _('Settings'))
    )
    bot.send_message(
        message.chat.id,
        _("Hello, I'm BailsBot and I can help you meet with people that you "
          "can swap money with.\n\nChoose one of the options on your keyboard."),
        reply_markup=keyboard
    )


def orders_list(start, count=10):
    orders = database.orders.find()[start:start + count]
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton(text='\u2b05\ufe0f', callback_data='orders {}'.format(start - count)),
        InlineKeyboardButton(text='\u27a1\ufe0f', callback_data='orders {}'.format(start + count))
    )
    bot.send_message(
        message.chat.id,
        '\n'.join(['{}. {} - {}'.format(start + i + 1, order['username']) for i, order in enumerate(orders)]),
        reply_markup=keyboard
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('orders'))
@translate_handler
def orders_button(call, user, _):
    start = int(call.data.split()[1])

    if start < 0:
        start = 0

    if start >= database.orders.count_documents({}):
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no more orders.")
        )
        return

    orders_list(cursor, start)


@message_handler(commands=['buy'])
@message_handler(
    func=lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4bb')
)
def handle_buy(message, user, _):
    if database.orders.count_documents({}) == 0:
        bot.send_message(message.chat.id, _("There are no orders."))
        return
    orders_list(0)


@translate_handler
def choose_amount(message, user, _):
    try:
        amount = float(message.text)
    except ValueError:
        bot.send_message(message.chat.id, _("Send decimal number or /cancel"))
        bot.register_next_step_handler(reply, choose_amount)
        return
    if amount <= 0:
        bot.send_message(message.chat.id, _("Send positive number or /cancel"))
        bot.register_next_step_handler(reply, choose_amount)
        return
    database.orders.update_one(
        {'_id': user['order']},
        {'$set': {'amount': amount}}
    )
    database.users.update_one(
        {'_id': user['_id']},
        {'$unset': {'order': True}}
    )
    bot.send_message(message.chat.id, _('Order is set.'))


@message_handler(commands=['sell'])
@message_handler(
    func=lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4b5')
)
def handle_sell(message, user, _):
    username = user.get('username')
    if not username:
        bot.send_message(
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
        'username': user.get('username'),
    })
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'order': doc.inserted_id}}
    )
    reply = bot.send_message(
        message.chat.id,
        _("How many BTS are you selling?")
    )
    bot.register_next_step_handler(reply, choose_amount)


@message_handler(commands=['cancel'])
def cancel_sell(message, user, _):
    database.users.update_one(
        {'_id': user['_id']},
        {'$unset': {'order': True}}
    )
    bot.send_message(message.chat.id, _('Order is cancelled.'))


@translate_handler
def choose_payment_methods(message, user, _):
    chosen_methods = None
    if message.text:
        chosen_methods = map(int, re.findall(r'(?:\b(\d+)\b)+', message.text))
    if not chosen_methods:
        bot.send_message(
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
            answer += _("%d %s ignored as they don't correspond to any payment method.") % (
                remaining,
                _('number was') if remaining == 1 else _('number were')
            ) + '\n\n'
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
    bot.send_message(message.chat.id, answer)


@bot.callback_query_handler(func=lambda call: call.data == 'payment method')
@translate_handler
def settings_payment_methods(call, user, _):
    with open(config.METHODS_JSON, 'r') as methods_json:
        methods = json.load(methods_json)
    user = database.users.find_one({'id': call.from_user.id})
    method_list = ['{}. {} {}'.format(
        i + 1,
        '\u2714\ufe0f' if method['name'] in user['payment_methods'] else '\u274c',
        method['name']
    ) for i, method in enumerate(methods)]
    reply = bot.send_message(
        call.chat.id,
        _('Send space-separated numbers corresponding to payment methods from list:') +
        '\n\n' + '\n'.join(method_list)
    )
    bot.register_next_step_handler(reply, choose_payment_methods)


@bot.callback_query_handler(func=lambda call: call.data == 'language')
@translate_handler
def settings_language(call, user, _):
    pass


@translate_handler
def set_username(message, user, _):
    username = message.text
    if not username:
        bot.send_message(message.chat.id, 'This is not a valid username.')
        return
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'username': username}}
    )
    bot.send_message(message.chat.id, 'Username set.')


@bot.callback_query_handler(func=lambda call: call.data == 'bitshares username')
@translate_handler
def settings_username(call, user, _):
    reply = bot.send_message(
        call.chat.id,
        'Send your Bitshares username.'
    )
    bot.register_next_step_handler(reply, set_username)


@bot.callback_query_handler(func=lambda call: call.data == 'order creation ui')
@translate_handler
def settings_order_creation_ui(call, user, _):
    order_ui = 1 - user['order_creation_id']
    database.users.update_one(
        {'_id': user['_id']},
        {'$set': {'order_creation_ui': order_ui}}
    )
    bot.send_message(
        call.chat.id,
        _('Your order creation UI is now set to') + ' ' +
        _('visual') if order_ui else _('conversational') + '.'
    )


@message_handler(commands=['settings'])
@message_handler(
    func=lambda msg: msg.text.encode('unicode-escape').startswith(b'\\u2699\\ufe0f')
)
def handle_settings(message, user, _):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        *[InlineKeyboardButton(text=_(setting['name']), callback_data=setting['name'].lower())
          for setting in SETTINGS]
    )
    user_info = []
    for setting in SETTINGS:
        option = user.get(setting['field'])
        if option is None:
            option = '\U0001f6ab'
        user_info.append('{}: {}'.format(_(setting['name']), option))
    bot.send_message(
        message.chat.id,
        _('Choose which option you would like to change.') + '\n\n' +
        '\n'.join(user_info),
        reply_markup=keyboard
    )


@message_handler()
def handle_default(message, user, _):
    bot.send_message(message.chat.id, _('Unknown command.'))
