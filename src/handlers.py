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


from datetime import datetime
import decimal
import math
from string import ascii_letters
from time import time

from babel import Locale
from bson.decimal128 import Decimal128
from bson.objectid import ObjectId
from pymongo.collection import ReturnDocument
import requests

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ContentType, ParseMode
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils.emoji import emojize
from aiogram.utils.exceptions import MessageNotModified

import config
from . import bot
from .bot import tg, dp
from .database import database
from .i18n import i18n
from .states import OrderCreation, payment_system_cashless
from .utils import normalize_money, exp


dp.middleware.setup(i18n)
_ = i18n.gettext


def help_message():
    return _(
        'I can help you meet with people that you can swap money with.\n\n'
        'Choose one of the options on your keyboard.'
    )


def inline_control_buttons(no_back=False, no_next=False, no_cancel=False):
    buttons = []

    row = []
    if not no_back:
        row.append(
            InlineKeyboardButton(text=_('Back'), callback_data='back')
        )
    if not no_next:
        row.append(
            InlineKeyboardButton(text=_('Next'), callback_data='next')
        )
    if row:
        buttons.append(row)

    if not no_cancel:
        buttons.append([
            InlineKeyboardButton(text=_('Cancel'), callback_data='cancel')
        ])

    return buttons


def start_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton(emojize(':heavy_plus_sign: ') + _('Create order')),
        KeyboardButton(emojize(':bust_in_silhouette: ') + _('My orders')),
        KeyboardButton(emojize(':closed_book: ') + _('Order book')),
        KeyboardButton(emojize(':abcd: ') + _('Language'))
    )
    return keyboard


@bot.private_handler(commands=['help'])
async def handle_help_command(message):
    await tg.send_message(
        message.chat.id, help_message(),
        reply_markup=start_keyboard()
    )


@bot.private_handler(commands=['start'], state=any_state)
async def handle_start_command(message, state):
    user = {'id': message.from_user.id}
    result = await database.users.update_one(
        user, {'$setOnInsert': user}, upsert=True
    )

    if not result.matched_count:
        keyboard = InlineKeyboardMarkup()
        for language in i18n.available_locales:
            keyboard.row(
                InlineKeyboardButton(
                    text=Locale(language).display_name,
                    callback_data='locale {}'.format(language)
                )
            )
        await tg.send_message(
            message.chat.id,
            _('Please, choose your language.'),
            reply_markup=keyboard
        )
        return

    await state.finish()
    await tg.send_message(
        message.chat.id,
        _("Hello, I'm TellerBot.") + ' ' + help_message(),
        reply_markup=start_keyboard()
    )


@bot.private_handler(commands=['locale'])
@bot.private_handler(lambda msg: msg.text.startswith(emojize(':abcd:')))
async def choose_locale(message):
    keyboard = InlineKeyboardMarkup()
    for language in i18n.available_locales:
        keyboard.row(
            InlineKeyboardButton(
                text=Locale(language).display_name,
                callback_data='locale {}'.format(language)
            )
        )
    await tg.send_message(
        message.chat.id,
        _('Choose your language.'),
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda call: call.data.startswith('locale'), state=any_state)
async def locale_button(call):
    locale = call.data.split()[1]
    await database.users.update_one(
        {'id': call.from_user.id},
        {'$set': {'locale': locale}}
    )

    i18n.ctx_locale.set(locale)
    await tg.answer_callback_query(callback_query_id=call.id)
    await tg.send_message(
        call.message.chat.id,
        _("Hello, I'm TellerBot.") + ' ' + help_message(),
        reply_markup=start_keyboard()
    )


async def orders_list(query, chat_id, start, quantity, buttons_data, message_id=None):
    keyboard = InlineKeyboardMarkup(row_width=5)

    inline_orders_buttons = (
        InlineKeyboardButton(
            text=emojize(':arrow_left:'),
            callback_data='{} {}'.format(buttons_data, start - config.ORDERS_COUNT)
        ),
        InlineKeyboardButton(
            text=emojize(':arrow_right:'),
            callback_data='{} {}'.format(buttons_data, start + config.ORDERS_COUNT)
        )
    )

    if quantity == 0:
        keyboard.row(*inline_orders_buttons)
        text = _('There are no orders.')
        if message_id is None:
            await tg.send_message(chat_id, text, reply_markup=keyboard)
        else:
            await tg.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        return

    all_orders = await database.orders.find(query).to_list(length=start + config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    for i, order in enumerate(orders):
        line = f'{i + 1}. '
        if 'sum_sell' in order:
            line += '{} '.format(order['sum_sell'])
        line += '{} → '.format(order['sell'])

        if 'sum_buy' in order:
            line += '{} '.format(order['sum_buy'])
        line += order['buy']

        if 'price' in order:
            line += ' ({} {}/{})'.format(order['price'], order['sell'], order['buy'])

        lines.append(line)
        buttons.append(
            InlineKeyboardButton(
                text='{}'.format(i + 1),
                callback_data='get_order {}'.format(order['_id'])
            )
        )

    keyboard.add(*buttons)
    keyboard.row(*inline_orders_buttons)

    text = '\\[' + _('Page {} of {}').format(
        math.ceil(start / config.ORDERS_COUNT) + 1,
        math.ceil(quantity / config.ORDERS_COUNT)
    ) + ']\n' + '\n'.join(lines)

    if message_id is None:
        await tg.send_message(
            chat_id, text,
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await tg.edit_message_text(
            text, chat_id, message_id,
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )


async def show_orders(call, query, start, buttons_data):
    quantity = await database.orders.count_documents(query)

    if start >= quantity > 0:
        await tg.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no more orders.")
        )
        return

    try:
        await tg.answer_callback_query(callback_query_id=call.id)
        await orders_list(
            query, call.message.chat.id, start, quantity, buttons_data,
            message_id=call.message.message_id
        )
    except MessageNotModified:
        await tg.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no previous orders.")
        )


@dp.callback_query_handler(lambda call: call.data.startswith('orders'), state=any_state)
async def orders_button(call):
    start = max(0, int(call.data.split()[1]))
    await show_orders(call, {
        'user_id': {'$ne': call.from_user.id},
        '$or': [
            {'expiration_time': {'$exists': False}},
            {'expiration_time': {'$gt': time()}}
        ]
    }, start, 'orders')


@dp.callback_query_handler(lambda call: call.data.startswith('my_orders'), state=any_state)
async def my_orders_button(call):
    start = max(0, int(call.data.split()[1]))
    await show_orders(call, {'user_id': call.from_user.id}, start, 'my_orders')


def order_handler(handler):
    async def decorator(call):
        order_id = call.data.split()[1]
        order = await database.orders.find_one({'_id': ObjectId(order_id)})

        if not order:
            await tg.answer_callback_query(
                callback_query_id=call.id,
                text=_('Order is not found.')
            )
            return

        return await handler(call, order)
    return decorator


async def show_order(
    order, chat_id, user_id, show_id,
    location_message_id=None, message_id=None, invert=False
):
    keyboard = InlineKeyboardMarkup()

    header = ''
    if show_id:
        header += 'ID: {}\n'.format(order['_id'])
    header += order['username'] + ' '
    if invert:
        callback_command = 'revert'
        header += _('sells {} for {}').format(order['sell'], order['buy'])
    else:
        callback_command = 'invert'
        header += _('buys {} for {}').format(order['buy'], order['sell'])
    header += '\n'

    lines = [header]
    if 'sum_buy' in order:
        lines.append(
            _('Amount of buying:') + ' {} {}'.format(
                order['sum_buy'], order['buy']
            )
        )
    if 'sum_sell' in order:
        lines.append(
            _('Amount of selling:') + ' {} {}'.format(
                order['sum_sell'], order['sell']
            )
        )
    if 'price' in order:
        if invert:
            price = ' {} {}/{}'.format(
                normalize_money(decimal.Decimal(1) / order['price'].to_decimal()),
                order['buy'], order['sell']
            )
        else:
            price = ' {} {}/{}'.format(order['price'], order['sell'], order['buy'])
        lines.append(_('Price:') + price)
    if 'payment_system' in order:
        lines.append(
            _('Payment system:') + ' ' + order['payment_system']
        )
    if 'duration' in order:
        lines.append(
            _('Duration: {} days').format(order['duration'])
        )
    if 'comments' in order:
        lines.append(
            _('Comments:') + ' «{}»'.format(order['comments'])
        )

    answer = '\n'.join(lines)

    if order['user_id'] == user_id:
        keyboard.row(
            InlineKeyboardButton(
                text=_('Delete'), callback_data='delete {}'.format(order['_id'])
            )
        )

    if location_message_id is None:
        if order.get('lat') is not None and order.get('lon') is not None:
            location_message = await tg.send_location(
                chat_id, order['lat'], order['lon']
            )
            location_message_id = location_message.message_id
        else:
            location_message_id = -1

    keyboard.row(
        InlineKeyboardButton(
            text=_('Invert'), callback_data='{} {} {} {}'.format(
                callback_command, order['_id'], int(show_id), location_message_id
            )
        )
    )
    keyboard.row(
        InlineKeyboardButton(
            text=_('Hide'), callback_data='hide {}'.format(location_message_id)
        )
    )

    if message_id is not None:
        await tg.edit_message_text(
            answer, chat_id, message_id,
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await tg.send_message(
            chat_id, answer,
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )


@dp.callback_query_handler(lambda call: call.data.startswith('get_order'), state=any_state)
@order_handler
async def get_order_button(call, order):
    await show_order(order, call.message.chat.id, call.from_user.id, show_id=True)
    await tg.answer_callback_query(callback_query_id=call.id)


@bot.private_handler(commands=['id'])
@bot.private_handler(regexp='ID: [a-f0-9]{24}')
async def get_order_command(message):
    try:
        order_id = message.text.split()[1]
    except IndexError:
        await tg.send_message(message.chat.id, _("Send order's ID as an argument."))
        return

    order = await database.orders.find_one({'_id': ObjectId(order_id)})
    if not order:
        await tg.send_message(message.chat.id, _('Order is not found.'))
        return
    await show_order(order, message.chat.id, message.from_user.id, show_id=False)


@dp.callback_query_handler(lambda call: call.data.startswith(('invert', 'revert')), state=any_state)
@order_handler
async def invert_button(call, order):
    args = call.data.split()
    invert = args[0] == 'invert'
    show_id = bool(int(args[2]))
    location_message_id = int(args[3])

    await tg.answer_callback_query(callback_query_id=call.id)
    await show_order(
        order, call.message.chat.id, call.from_user.id, show_id=show_id,
        message_id=call.message.message_id, location_message_id=location_message_id, invert=invert
    )


@dp.callback_query_handler(lambda call: call.data.startswith('delete'), state=any_state)
@order_handler
async def delete_button(call, order):
    delete_result = await database.orders.delete_one({'_id': order['_id'], 'user_id': call.from_user.id})
    await tg.answer_callback_query(
        callback_query_id=call.id,
        text=_('Order was deleted.') if delete_result.deleted_count > 0 else
        _("Couldn't delete order.")
    )


@dp.callback_query_handler(lambda call: call.data.startswith('hide'), state=any_state)
async def hide_button(call):
    await tg.delete_message(call.message.chat.id, call.message.message_id)
    location_message_id = call.data.split()[1]
    if location_message_id != '-1':
        await tg.delete_message(call.message.chat.id, location_message_id)


@dp.callback_query_handler(lambda call: call.data == 'back', state=any_state)
async def previous_state(call, state):
    state_name = await state.get_state()
    if state_name in OrderCreation:
        new_state = await OrderCreation.previous()
        handler = bot.state_handlers.get(new_state)
        if handler:
            error = await handler(call)
            if not error:
                return
        await state.set_state(state_name)
    return await tg.answer_callback_query(
        callback_query_id=call.id,
        text=_('You are not creating order.')
    )


@dp.callback_query_handler(lambda call: call.data == 'next', state=any_state)
async def next_state(call, state):
    state_name = await state.get_state()
    if state_name in OrderCreation:
        new_state = await OrderCreation.next()
        handler = bot.state_handlers.get(new_state)
        if handler:
            error = await handler(call)
            if not error:
                return
        await state.set_state(state_name)
    return await tg.answer_callback_query(
        callback_query_id=call.id,
        text=_('You are not creating order.')
    )


@bot.private_handler(commands=['create'])
@bot.private_handler(
    lambda msg: msg.text.startswith(emojize(':heavy_plus_sign:'))
)
async def handle_create(message):
    if message.from_user.username:
        username = '@' + message.from_user.username
    else:
        username = '[' + message.from_user.first_name
        if message.from_user.last_name:
            username += ' ' + message.from_user.last_name
        username += f'](tg://user?id={message.from_user.id})'

    await database.creation.insert_one({
        'user_id': message.from_user.id,
        'username': username,
    })
    await OrderCreation.first()

    await tg.send_message(
        message.chat.id,
        _('What currency do you want to buy?'),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True, no_next=True)
        )
    )


@bot.state_handler(OrderCreation.buy)
async def create_order_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await tg.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    await tg.edit_message_text(
        _('What currency do you want to buy?'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True)
        )
    )


@bot.private_handler(commands=['my'])
@bot.private_handler(
    lambda msg: msg.text.startswith(emojize(':bust_in_silhouette:'))
)
async def handle_my_orders(message):
    query = {'user_id': message.from_user.id}
    quantity = await database.orders.count_documents(query)
    await orders_list(query, message.chat.id, 0, quantity, 'my_orders')


@bot.private_handler(commands=['book'])
@bot.private_handler(
    lambda msg: msg.text.startswith(emojize(':closed_book:'))
)
async def handle_book(message):
    query = {
        'user_id': {'$ne': message.from_user.id},
        '$or': [
            {'expiration_time': {'$exists': False}},
            {'expiration_time': {'$gt': time()}}
        ]
    }
    quantity = await database.orders.count_documents(query)
    await orders_list(query, message.chat.id, 0, quantity, 'orders')


@dp.callback_query_handler(lambda call: call.data == 'cancel', state=any_state)
async def cancel_order_creation(call, state):
    await state.finish()
    await tg.answer_callback_query(callback_query_id=call.id)

    order = await database.creation.delete_one({'user_id': call.from_user.id})
    if not order.deleted_count:
        await tg.send_message(
            call.message.chat.id,
            _('You are not creating order.'),
            reply_markup=start_keyboard()
        )
        return True

    await tg.send_message(
        call.message.chat.id,
        _('Order is cancelled.'),
        reply_markup=start_keyboard()
    )


@bot.private_handler(state=OrderCreation.buy)
async def choose_buy(message, state):
    if not all(ch in ascii_letters for ch in message.text):
        await tg.send_message(
            message.chat.id,
            _('Currency may only contain latin characters.'),
        )
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'buy': message.text}}
    )
    await OrderCreation.sell.set()
    await tg.send_message(
        message.chat.id,
        _('What currency do you want to sell?'),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_next=True)
        )
    )


@bot.state_handler(OrderCreation.sell)
async def choose_buy_handler(call):
    await tg.edit_message_text(
        _('What currency do you want to sell?'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons()
        )
    )


@bot.private_handler(state=OrderCreation.sell)
async def choose_sell(message, state):
    if not all(ch in ascii_letters for ch in message.text):
        await tg.send_message(
            message.chat.id,
            _('Currency may only contain latin characters.'),
        )
        return

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {'$set': {'sell': message.text}},
        return_document=ReturnDocument.AFTER
    )
    await OrderCreation.price.set()
    await tg.send_message(
        message.chat.id,
        _('At what price (in {}/{}) do you want to buy?').format(
            order['sell'], order['buy']
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.state_handler(OrderCreation.price)
async def price_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})
    await tg.edit_message_text(
        _('At what price (in {}/{}) do you want to buy?').format(
            order['sell'], order['buy']
        ),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


async def validate_money(data, chat_id):
    try:
        money = decimal.Decimal(data)
    except decimal.InvalidOperation:
        await tg.send_message(chat_id, _('Send decimal number.'))
        return
    if money <= 0:
        await tg.send_message(chat_id, _('Send positive number.'))
        return

    normalized = normalize_money(money)
    if normalized.is_zero():
        await tg.send_message(
            chat_id,
            _('Send number greater than') + f' {exp:.8f}'
        )
        return

    return normalized


@bot.private_handler(state=OrderCreation.price)
async def choose_price(message, state):
    price = await validate_money(message.text, message.chat.id)
    if not price:
        return

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {'$set': {'price': Decimal128(price)}},
        return_document=ReturnDocument.AFTER
    )

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            text=order['buy'],
            callback_data='sum buy'
        ),
        InlineKeyboardButton(
            text=order['sell'],
            callback_data='sum sell'
        )
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await OrderCreation.sum.set()
    await tg.send_message(
        message.chat.id,
        _('Choose currency of order sum.'),
        reply_markup=keyboard
    )


@bot.private_handler(state=OrderCreation.sum)
async def choose_sum(message, state):
    transaction_sum = await validate_money(message.text, message.chat.id)
    if not transaction_sum:
        return

    order = await database.creation.find_one_and_update(
        {
            'user_id': message.from_user.id,
            'sum_currency': {'$exists': True}
        },
        {'$unset': {'sum_currency': True}}
    )
    if not order:
        await tg.send_message(message.chat.id, _('Choose currency of sum with buttons.'))
        return

    update_dict = {}
    price = order.get('price')
    if order['sum_currency'] == 'buy':
        update_dict['sum_buy'] = Decimal128(transaction_sum)
        if price:
            update_dict['sum_sell'] = Decimal128(normalize_money(transaction_sum * price.to_decimal()))
    else:
        update_dict['sum_sell'] = Decimal128(transaction_sum)
        if price:
            update_dict['sum_buy'] = Decimal128(normalize_money(transaction_sum / price.to_decimal()))

    await database.creation.update_one(
        {'_id': order['_id']},
        {'$set': update_dict}
    )

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(text=_('Cash'), callback_data='cash type'),
        InlineKeyboardButton(text=_('Cashless'), callback_data='cashless type')
    )
    for row in inline_control_buttons():
        keyboard.row(*row)
    await OrderCreation.payment_type.set()
    await tg.send_message(
        message.chat.id,
        _('Choose payment type.'),
        reply_markup=keyboard
    )


@bot.state_handler(OrderCreation.sum)
async def sum_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await tg.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            text=order['buy'],
            callback_data='sum buy'
        ),
        InlineKeyboardButton(
            text=order['sell'],
            callback_data='sum sell'
        )
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await OrderCreation.sum.set()
    await tg.edit_message_text(
        _('Choose currency of order sum.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda call: call.data.startswith('sum'), state=OrderCreation.sum)
async def choose_sum_currency(call):
    sum_currency = call.data.split()[1]
    await database.creation.update_one(
        {'user_id': call.from_user.id},
        {'$set': {'sum_currency': sum_currency}}
    )
    await tg.answer_callback_query(callback_query_id=call.id)
    await tg.send_message(
        call.message.chat.id,
        _('Currency of order sum set. Send order sum in the next message.')
    )


@bot.state_handler(OrderCreation.payment_type)
async def payment_type_handler(call):
    result = await database.creation.update_one(
        {'user_id': call.from_user.id},
        {'$unset': {'sum_currency': True}}
    )

    if not result.matched_count:
        await tg.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(text=_('Cash'), callback_data='cash type'),
        InlineKeyboardButton(text=_('Cashless'), callback_data='cashless type')
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await tg.edit_message_text(
        _('Choose payment type.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboard
    )


@bot.state_handler(OrderCreation.payment_system)
async def payment_system_handler(call):
    await tg.edit_message_text(
        _('Send payment system.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=OrderCreation.payment_type)
async def message_in_payment_type(message, state):
    await tg.send_message(
        message.chat.id,
        _('Send payment system.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'cash type', state=OrderCreation.payment_type)
async def cash_payment_type(call):
    await OrderCreation.location.set()
    await tg.edit_message_text(
        _('Send location of a preferred meeting point.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=OrderCreation.location, content_types=ContentType.TEXT)
async def text_location(message, state):
    query = message.text

    language = await i18n.get_user_locale()
    location_cache = await database.locations.find_one(
        {'q': query, 'lang': language}
    )

    if location_cache:
        results = location_cache['results']
    else:
        params = {
            'q': query,
            'format': 'json',
            'accept-language': language
        }
        request = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params=params, headers={'User-Agent': 'TellerBot'}
        )

        results = [{
            'display_name': result['display_name'],
            'lat': result['lat'],
            'lon': result['lon']
        } for result in request.json()[:10]]

        await database.locations.insert_one({
            'q': query, 'lang': language, 'results': results,
            'date': datetime.utcnow()
        })

    if not results:
        await tg.send_message(message.chat.id, _('Location is not found.'))
        return

    if len(results) == 1:
        location = results[0]
        await database.creation.update_one(
            {'user_id': message.from_user.id},
            {'$set': {
                'lat': float(location['lat']), 'lon': float(location['lon'])
            }}
        )
        await OrderCreation.duration.set()
        await tg.send_message(
            message.chat.id,
            _('Send duration of order in days.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
        )
        return

    keyboard = InlineKeyboardMarkup(row_width=5)

    answer = _('Choose one of these locations:') + '\n\n'
    buttons = []
    for i, result in enumerate(results):
        answer += '{}. {}\n'.format(i + 1, result['display_name'])
        buttons.append(
            InlineKeyboardButton(
                text=f'{i + 1}',
                callback_data='location {} {}'.format(result['lat'], result['lon'])
            )
        )
    keyboard.add(*buttons)

    await tg.send_message(message.chat.id, answer, reply_markup=keyboard)


@dp.callback_query_handler(lambda call: call.data.startswith('location'), state=OrderCreation.location)
async def geocoded_location(call):
    latitude, longitude = call.data.split()[1:]
    await database.creation.update_one(
        {'user_id': call.from_user.id},
        {'$set': {'lat': float(latitude), 'lon': float(longitude)}}
    )
    await OrderCreation.duration.set()
    await tg.send_message(
        call.message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=OrderCreation.location, content_types=ContentType.LOCATION)
async def choose_location(message, state):
    location = message.location
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'lat': location.latitude, 'lon': location.longitude}}
    )
    await OrderCreation.duration.set()
    await tg.send_message(
        message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'cashless type', state=OrderCreation.payment_type)
@dp.callback_query_handler(lambda call: call.data == 'back', state=payment_system_cashless)
async def cashless_payment_type(call):
    await payment_system_cashless.set()
    await tg.edit_message_text(
        _('Send payment system.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.state_handler(OrderCreation.location)
async def location_handler(call):
    await tg.edit_message_text(
        _('Send location of a preferred meeting point.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=OrderCreation.payment_system)
async def choose_payment_system(message, state):
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_system': message.text}}
    )
    await OrderCreation.location.set()
    await tg.send_message(
        message.chat.id,
        _('Send location of a preferred meeting point.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'next', state=payment_system_cashless)
@bot.state_handler(OrderCreation.duration)
async def duration_handler(call):
    await tg.edit_message_text(
        _('Send duration of order in days.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=payment_system_cashless)
async def choose_payment_system_cashless(message, state):
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_system': message.text}}
    )
    await OrderCreation.duration.set()
    await tg.send_message(
        message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.state_handler(OrderCreation.comments)
async def comment_handler(call):
    await tg.edit_message_text(
        _('Add any additional comments.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=OrderCreation.duration)
async def choose_duration(message, state):
    try:
        duration = int(message.text)
        if duration <= 0:
            raise ValueError
    except ValueError:
        await tg.send_message(message.chat.id, _('Send integer.'))
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'duration': duration}}
    )

    await OrderCreation.comments.set()
    await tg.send_message(
        message.chat.id,
        _('Add any additional comments.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.state_handler(OrderCreation.set_order)
async def choose_comments_handler(call):
    order = await database.creation.find_one_and_delete(
        {'user_id': call.from_user.id}
    )
    await tg.answer_callback_query(callback_query_id=call.id)
    if order:
        order['start_time'] = time()
        if 'duration' in order:
            order['expiration_time'] = time() + order['duration'] * 24 * 60 * 60
        inserted_order = await database.orders.insert_one(order)
        await tg.send_message(
            call.message.chat.id,
            _('Order is set.') + '\nID: {}'.format(inserted_order.inserted_id),
            reply_markup=start_keyboard()
        )
    await dp.get_current().current_state().finish()


@bot.private_handler(state=OrderCreation.comments)
async def choose_comments(message, state):
    comments = message.text
    if len(comments) > 150:
        await tg.send_message(
            message.chat.id,
            _('Comment should have less than 150 characters '
              '(your comment has {} characters).').format(len(comments))
        )
        return

    order = await database.creation.find_one_and_delete(
        {'user_id': message.from_user.id}
    )
    if order:
        order['comments'] = comments
        inserted_order = await database.orders.insert_one(order)
        await tg.send_message(
            message.chat.id,
            _('Order is set.') + '\nID: {}'.format(inserted_order.inserted_id),
            reply_markup=start_keyboard()
        )
    await state.finish()


@bot.private_handler()
async def handle_default(message):
    await tg.send_message(message.chat.id, _('Unknown command.'))
