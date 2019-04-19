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
from . import bot, states
from .bot import tg, dp
from .database import database, STATE_KEY
from .i18n import i18n
from .states import OrderCreation
from .utils import normalize_money, exp, MoneyValidationError


dp.middleware.setup(i18n)
_ = i18n.gettext


async def validate_money(data, chat_id):
    try:
        money = decimal.Decimal(data)
    except decimal.InvalidOperation:
        raise MoneyValidationError(_('Send decimal number.'))
    if money <= 0:
        raise MoneyValidationError(_('Send positive number.'))

    normalized = normalize_money(money)
    if normalized.is_zero():
        raise MoneyValidationError(_('Send number greater than') + f' {exp:.8f}')

    return normalized


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
            InlineKeyboardButton(text=_('Skip'), callback_data='next')
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

        if 'price_sell' in order:
            line += ' ({} {}/{})'.format(order['price_sell'], order['sell'], order['buy'])

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


def get_order_field_names():
    return {
        'sum_buy': _('Amount of buying:'),
        'sum_sell': _('Amount of selling:'),
        'price': _('Price:'),
        'payment_system': _('Payment system:'),
        'duration': _('Duration:'),
        'comments': _('Comments:')
    }


async def show_order(
    order, chat_id, user_id,
    message_id=None, location_message_id=None,
    show_id=False, invert=False, edit=False
):
    if location_message_id is None:
        if order.get('lat') is not None and order.get('lon') is not None:
            location_message = await tg.send_location(
                chat_id, order['lat'], order['lon']
            )
            location_message_id = location_message.message_id
        else:
            location_message_id = -1

    header = ''
    if show_id:
        header += 'ID: {}\n'.format(order['_id'])
    header += order['username'] + ' '
    if invert:
        header += _('sells {} for {}').format(order['sell'], order['buy'])
    else:
        header += _('buys {} for {}').format(order['buy'], order['sell'])
    header += '\n'

    lines = [header]
    field_names = get_order_field_names()
    lines_format = {k: None for k in field_names}

    if 'sum_buy' in order:
        lines_format['sum_buy'] = '{} {}'.format(order['sum_buy'], order['buy'])
    if 'sum_sell' in order:
        lines_format['sum_sell'] = '{} {}'.format(order['sum_sell'], order['sell'])
    if 'price_sell' in order:
        if invert:
            lines_format['price'] = '{} {}/{}'.format(
                order['price_buy'], order['buy'], order['sell']
            )
        else:
            lines_format['price'] = '{} {}/{}'.format(
                order['price_sell'], order['sell'], order['buy']
            )
    if 'payment_system' in order:
        lines_format['payment_system'] = order['payment_system']
    if 'duration' in order:
        lines_format['duration'] = '{} - {}'.format(
            datetime.utcfromtimestamp(order['start_time']).strftime('%d.%m.%Y'),
            datetime.utcfromtimestamp(order['expiration_time']).strftime('%d.%m.%Y'),
        )
    if 'comments' in order:
        lines_format['comments'] = '«{}»'.format(order['comments'])

    keyboard = InlineKeyboardMarkup(row_width=6)

    keyboard.row(
        InlineKeyboardButton(
            text=_('Invert'), callback_data='{} {} {} {}'.format(
                'revert' if invert else 'invert',
                order['_id'], location_message_id, int(edit)
            )
        )
    )

    if edit:
        buttons = []
        for i, (field, value) in enumerate(lines_format.items()):
            if value is not None:
                lines.append(f'{i + 1}. {field_names[field]} {value}')
            elif edit:
                lines.append(f'{i + 1}. {field_names[field]} -')
            buttons.append(
                InlineKeyboardButton(
                    text=f'{i + 1}', callback_data='edit {} {} {} {}'.format(
                        order['_id'], field, location_message_id, int(invert)
                    )
                )
            )

        keyboard.add(*buttons)
        keyboard.row(
            InlineKeyboardButton(
                text=_('Finish'), callback_data='{} {} {} 0'.format(
                    'invert' if invert else 'revert',
                    order['_id'], location_message_id
                )
            )
        )

    else:
        for field, value in lines_format.items():
            if value is not None:
                lines.append(field_names[field] + ' ' + value)

        if order['user_id'] == user_id:
            keyboard.row(
                InlineKeyboardButton(
                    text=_('Edit'), callback_data='{} {} {} 1'.format(
                        'invert' if invert else 'revert',
                        order['_id'], location_message_id
                    )
                )
            )
            keyboard.row(
                InlineKeyboardButton(
                    text=_('Delete'), callback_data='delete {}'.format(order['_id'])
                )
            )
        keyboard.row(
            InlineKeyboardButton(
                text=_('Hide'), callback_data='hide {}'.format(location_message_id)
            )
        )

    answer = '\n'.join(lines)

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


@dp.callback_query_handler(lambda call: call.data.startswith('get_order'), state=any_state)
@order_handler
async def get_order_button(call, order):
    await tg.answer_callback_query(callback_query_id=call.id)
    await show_order(order, call.message.chat.id, call.from_user.id, show_id=True)


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
    await show_order(order, message.chat.id, message.from_user.id)


@dp.callback_query_handler(lambda call: call.data.startswith(('invert', 'revert')), state=any_state)
@order_handler
async def invert_button(call, order):
    args = call.data.split()

    invert = args[0] == 'invert'
    location_message_id = int(args[2])
    edit = bool(int(args[3]))
    show_id = call.message.text.startswith('ID')

    await tg.answer_callback_query(callback_query_id=call.id)
    await show_order(
        order, call.message.chat.id, call.from_user.id,
        message_id=call.message.message_id,
        location_message_id=location_message_id, show_id=show_id,
        invert=invert, edit=edit
    )


@dp.callback_query_handler(lambda call: call.data.startswith('edit'), state=any_state)
@order_handler
async def edit_button(call, order):
    args = call.data.split()
    field = args[2]

    if field == 'sum_buy':
        answer = _('Send new amount of buying.')
    elif field == 'sum_sell':
        answer = _('Send new amount of selling.')
    elif field == 'price':
        answer = _('Send new price.')
    elif field == 'payment_system':
        answer = _('Send new payment system.')
    elif field == 'duration':
        answer = _('Send new duration.')
    elif field == 'comments':
        answer = _('Send new comments.')
    else:
        answer = None

    await tg.answer_callback_query(callback_query_id=call.id)
    if answer:
        result = await tg.send_message(call.message.chat.id, answer)
        await database.users.update_one(
            {'id': call.from_user.id},
            {'$set': {
                'edit.order_message_id': call.message.message_id,
                'edit.message_id': result.message_id,
                'edit.order_id': order['_id'],
                'edit.field': field,
                'edit.location_message_id': int(args[3]),
                'edit.invert': bool(int(args[4])),
                'edit.show_id': call.message.text.startswith('ID')
            }}
        )
        await states.field_editing.set()


@bot.private_handler(state=states.field_editing)
async def edit_field(message, state):
    user = await database.users.find_one({'id': message.from_user.id})
    edit = user['edit']
    field = edit['field']
    invert = edit['invert']
    update_dict = {}
    error = None

    if field == 'sum_buy':
        try:
            transaction_sum = await validate_money(message.text, message.chat.id)
        except MoneyValidationError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({'_id': edit['order_id']})
            update_dict['sum_buy'] = Decimal128(transaction_sum)
            if order['price_sell']:
                update_dict['sum_sell'] = Decimal128(normalize_money(
                    transaction_sum * order['price_sell'].to_decimal()
                ))

    elif field == 'sum_sell':
        try:
            transaction_sum = await validate_money(message.text, message.chat.id)
        except MoneyValidationError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({'_id': edit['order_id']})
            update_dict['sum_sell'] = Decimal128(transaction_sum)
            if order['price_buy']:
                update_dict['sum_buy'] = Decimal128(normalize_money(
                    transaction_sum * order['price_buy'].to_decimal()
                ))

    elif field == 'price':
        try:
            price = await validate_money(message.text, message.chat.id)
        except MoneyValidationError as exception:
            error = str(exception)
        else:
            order = await database.orders.find_one({'_id': edit['order_id']})

            if invert:
                update_dict['price_buy'] = Decimal128(price)
                update_dict['price_sell'] = Decimal128(normalize_money(decimal.Decimal(1) / price))
                if 'sum_sell' in order:
                    update_dict['sum_buy'] = Decimal128(normalize_money(
                        order['sum_sell'].to_decimal() * price
                    ))
            else:
                update_dict['price_buy'] = Decimal128(normalize_money(decimal.Decimal(1) / price))
                update_dict['price_sell'] = Decimal128(price)
                if 'sum_buy' in order:
                    update_dict['sum_sell'] = Decimal128(normalize_money(
                        order['sum_buy'].to_decimal() * price
                    ))

    elif field == 'payment_system':
        payment_system = message.text.replace('\n', ' ')
        if len(payment_system) > 150:
            await tg.send_message(
                message.chat.id,
                _('This value should contain less than 150 characters '
                  '(you sent {} characters).').format(len(payment_system))
            )
            return
        update_dict['payment_system'] = payment_system

    elif field == 'duration':
        try:
            duration = int(message.text)
            if duration <= 0:
                raise ValueError
        except ValueError:
            error = _('Send natural number.')
        else:
            order = await database.orders.find_one({'_id': edit['order_id']})
            update_dict['duration'] = duration
            update_dict['expiration_time'] = order['start_time'] + duration * 24 * 60 * 60

    elif field == 'comments':
        comments = message.text
        if len(comments) > 150:
            await tg.send_message(
                message.chat.id,
                _('This value should contain less than 150 characters '
                  '(you sent {} characters).').format(len(comments))
            )
            return
        update_dict['comments'] = comments

    if update_dict:
        result = await database.orders.update_one(
            {'_id': edit['order_id']},
            {'$set': update_dict}
        )
        if result.modified_count:
            order = await database.orders.find_one({'_id': edit['order_id']})
            await show_order(
                order, message.chat.id, message.from_user.id,
                message_id=edit['order_message_id'], location_message_id=edit['location_message_id'],
                show_id=edit['show_id'], invert=edit['invert'], edit=True
            )
        await database.users.update_one(
            {'id': message.from_user.id},
            {'$unset': {'edit': True, STATE_KEY: True}}
        )
        await tg.delete_message(message.chat.id, message.message_id)
        await tg.delete_message(message.chat.id, edit['message_id'])
    elif error:
        await tg.delete_message(message.chat.id, message.message_id)
        await tg.edit_message_text(error, message.chat.id, edit['message_id'])


@dp.callback_query_handler(lambda call: call.data.startswith('delete'), state=any_state)
@order_handler
async def delete_button(call, order):
    delete_result = await database.orders.delete_one({
        '_id': order['_id'], 'user_id': call.from_user.id
    })
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
        text=_("Couldn't go back.")
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
        text=_("Couldn't go next.")
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
async def create_order_handler(call, order=None):
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
            _('Currency may only contain latin characters.')
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
            _('Currency may only contain latin characters.')
        )
        return

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {'$set': {
            'sell': message.text,
            'price_currency': 'sell'
        }},
        return_document=ReturnDocument.AFTER
    )

    buttons = inline_control_buttons()
    buttons.insert(0, [InlineKeyboardButton(text=_('Invert'), callback_data='price buy')])

    await OrderCreation.price.set()
    await tg.send_message(
        message.chat.id,
        _('At what price (in {}/{}) do you want to buy?').format(order['sell'], order['buy']),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


async def price_ask(call, order, price_currency):
    if price_currency == 'sell':
        answer = _('At what price (in {}/{}) do you want to buy?').format(
            order['sell'], order['buy']
        )
        callback_command = 'buy'
    else:
        answer = _('At what price (in {}/{}) do you want to sell?').format(
            order['buy'], order['sell']
        )
        callback_command = 'sell'

    buttons = inline_control_buttons()
    buttons.insert(0, [InlineKeyboardButton(
        text=_('Invert'), callback_data='price {}'.format(callback_command)
    )])
    await tg.edit_message_text(
        answer, call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@bot.state_handler(OrderCreation.price)
async def price_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})
    price_currency = order.get('price_currency')
    if not price_currency:
        price_currency = 'sell'
        await database.creation.update_one(
            {'_id': order['_id']},
            {'$set': {'price_currency': price_currency}}
        )
    await price_ask(call, order, price_currency)


@dp.callback_query_handler(lambda call: call.data.startswith('price'), state=OrderCreation.price)
async def invert_price(call):
    price_currency = call.data.split()[1]
    order = await database.creation.find_one_and_update(
        {'user_id': call.from_user.id},
        {'$set': {'price_currency': price_currency}}
    )
    await price_ask(call, order, price_currency)


@bot.private_handler(state=OrderCreation.price)
async def choose_price(message, state):
    try:
        price = await validate_money(message.text, message.chat.id)
    except MoneyValidationError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.creation.find_one({'user_id': message.from_user.id})
    if order['price_currency'] == 'sell':
        update_dict = {
            'price_sell': Decimal128(price),
            'price_buy': Decimal128(normalize_money(decimal.Decimal(1) / price))
        }
    else:
        update_dict = {
            'price_buy': Decimal128(price),
            'price_sell': Decimal128(normalize_money(decimal.Decimal(1) / price))
        }

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {
            '$set': update_dict,
            '$unset': {'price_currency': True}
        },
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
    try:
        transaction_sum = await validate_money(message.text, message.chat.id)
    except MoneyValidationError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.creation.find_one({
        'user_id': message.from_user.id,
        'sum_currency': {'$exists': True}
    })
    if not order:
        await tg.send_message(message.chat.id, _('Choose currency of sum with buttons.'))
        return

    update_dict = {'sum_' + order['sum_currency']: Decimal128(transaction_sum)}

    new_sum_currency = 'sell' if order['sum_currency'] == 'buy' else 'buy'
    price_field = 'price_' + new_sum_currency

    if price_field in order:
        update_dict['sum_' + new_sum_currency] = Decimal128(normalize_money(
            transaction_sum * order[price_field].to_decimal()
        ))
        await database.creation.update_one(
            {'_id': order['_id']},
            {'$set': update_dict, '$unset': {'sum_currency': True}}
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
    else:
        update_dict['sum_currency'] = new_sum_currency
        await database.creation.update_one(
            {'_id': order['_id']},
            {'$set': update_dict}
        )
        await tg.send_message(
            message.chat.id,
            _('Send order sum in {}.').format(order[update_dict['sum_currency']]),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=inline_control_buttons(no_back=True, no_cancel=True)
            )
        )


@bot.state_handler(OrderCreation.sum)
async def sum_handler(call):
    order = await database.creation.find_one_and_update(
        {'user_id': call.from_user.id},
        {'$unset': {'price_currency': True}}
    )

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

    await tg.edit_message_text(
        _('Choose currency of order sum.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda call: call.data.startswith('sum'), state=OrderCreation.sum)
async def choose_sum_currency(call):
    sum_currency = call.data.split()[1]
    order = await database.creation.find_one_and_update(
        {'user_id': call.from_user.id},
        {'$set': {'sum_currency': sum_currency}}
    )
    await tg.answer_callback_query(callback_query_id=call.id)
    await tg.send_message(
        call.message.chat.id,
        _('Send order sum in {}.').format(order[sum_currency])
    )


@bot.state_handler(OrderCreation.payment_type)
async def payment_type_handler(call):
    order = await database.creation.update_one(
        {'user_id': call.from_user.id},
        {'$unset': {'sum_currency': True}}
    )

    if not order.matched_count:
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
@dp.callback_query_handler(lambda call: call.data == 'back', state=states.payment_system_cashless)
async def cashless_payment_type(call):
    await states.payment_system_cashless.set()
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
    payment_system = message.text.replace('\n', ' ')
    if len(payment_system) > 150:
        await tg.send_message(
            message.chat.id,
            _('This value should contain less than 150 characters '
              '(you sent {} characters).').format(len(payment_system))
        )
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_system': payment_system}}
    )
    await OrderCreation.location.set()
    await tg.send_message(
        message.chat.id,
        _('Send location of a preferred meeting point.'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'next', state=states.payment_system_cashless)
@bot.state_handler(OrderCreation.duration)
async def duration_handler(call):
    await tg.edit_message_text(
        _('Send duration of order in days.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@bot.private_handler(state=states.payment_system_cashless)
async def choose_payment_system_cashless(message, state):
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_system': message.text.replace('\n', ' ')}}
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
        await tg.send_message(message.chat.id, _('Send natural number.'))
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


async def set_order(order, chat_id):
    order['start_time'] = time()
    if 'duration' in order:
        order['expiration_time'] = time() + order['duration'] * 24 * 60 * 60
    if 'price_sell' not in order and 'sum_buy' in order and 'sum_sell' in order:
        order['price_sell'] = Decimal128(normalize_money(
            order['sum_sell'].to_decimal() / order['sum_buy'].to_decimal()
        ))
        order['price_buy'] = Decimal128(normalize_money(
            order['sum_buy'].to_decimal() / order['sum_sell'].to_decimal()
        ))
    inserted_order = await database.orders.insert_one(order)
    order['_id'] = inserted_order.inserted_id
    await tg.send_message(chat_id, _('Order is set.'), reply_markup=start_keyboard())
    await show_order(order, chat_id, order['user_id'], show_id=True)


@bot.state_handler(OrderCreation.set_order)
async def choose_comments_handler(call):
    order = await database.creation.find_one_and_delete(
        {'user_id': call.from_user.id}
    )
    await tg.answer_callback_query(callback_query_id=call.id)
    if order:
        await set_order(order, call.message.chat.id)
    await dp.get_current().current_state().finish()


@bot.private_handler(state=OrderCreation.comments)
async def choose_comments(message, state):
    comments = message.text
    if len(comments) > 150:
        await tg.send_message(
            message.chat.id,
            _('This value should contain less than 150 characters '
              '(you sent {} characters).').format(len(comments))
        )
        return

    order = await database.creation.find_one_and_delete(
        {'user_id': message.from_user.id}
    )
    if order:
        order['comments'] = comments
        await set_order(order, message.chat.id)
    await state.finish()


@bot.private_handler()
async def handle_default(message):
    await tg.send_message(message.chat.id, _('Unknown command.'))
