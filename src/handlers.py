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


import math
from string import ascii_letters

from babel import Locale
from bson.objectid import ObjectId
from pymongo.collection import ReturnDocument

from aiogram import types
from aiogram.dispatcher.filters.state import State, StatesGroup, any_state
from aiogram.utils.emoji import emojize
from aiogram.utils.exceptions import MessageNotModified

import config
from .bot import bot, dp, private_handler
from .database import database
from .i18n import i18n


dp.middleware.setup(i18n)
_ = i18n.gettext


class OrderCreation(StatesGroup):
    crypto = State()
    fiat = State()
    sum = State()
    price = State()
    payment_type = State()
    payment_method = State()
    location = State()
    duration = State()
    comments = State()


payment_method_cashless = State(group_name='OrderCreation')
state_handlers = {}


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
            types.InlineKeyboardButton(text=_('Back'), callback_data='back')
        )
    if not no_next:
        row.append(
            types.InlineKeyboardButton(text=_('Next'), callback_data='next')
        )
    if row:
        buttons.append(row)

    if not no_cancel:
        buttons.append([
            types.InlineKeyboardButton(text=_('Cancel'), callback_data='cancel')
        ])

    return buttons


def start_keyboard():
    keyboard = types.ReplyKeyboardMarkup(row_width=2)
    keyboard.add(
        types.KeyboardButton(emojize(':computer: ') + _('Buy')),
        types.KeyboardButton(emojize(':dollar: ') + _('Sell')),
        types.KeyboardButton(emojize(':bust_in_silhouette: ') + _('My orders')),
        types.KeyboardButton(emojize(':closed_book: ') + _('Order book')),
        types.KeyboardButton(emojize(':abcd: ') + _('Choose language'))
    )
    return keyboard


@private_handler(commands=['help'])
async def handle_help_command(message):
    await bot.send_message(
        message.chat.id, help_message(),
        reply_markup=start_keyboard()
    )


@private_handler(commands=['start'])
async def handle_start_command(message):
    user = {'id': message.from_user.id}
    result = await database.users.update_one(
        user, {'$setOnInsert': user}, upsert=True
    )

    if not result.matched_count:
        keyboard = types.InlineKeyboardMarkup()
        for language in i18n.available_locales:
            keyboard.row(
                types.InlineKeyboardButton(
                    text=Locale(language).display_name,
                    callback_data='locale {}'.format(language)
                )
            )
        await bot.send_message(
            message.chat.id,
            _('Please, choose your language.'),
            reply_markup=keyboard
        )
        return

    await bot.send_message(
        message.chat.id,
        _("Hello, I'm BailsBot.") + ' ' + help_message(),
        reply_markup=start_keyboard()
    )


@private_handler(commands=['locale'])
@private_handler(lambda msg: msg.text.startswith(emojize(':abcd:')))
async def choose_locale(message):
    keyboard = types.InlineKeyboardMarkup()
    for language in i18n.available_locales:
        keyboard.row(
            types.InlineKeyboardButton(
                text=Locale(language).display_name,
                callback_data='locale {}'.format(language)
            )
        )
    await bot.send_message(
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
    await bot.answer_callback_query(callback_query_id=call.id)
    await bot.send_message(
        call.message.chat.id,
        _("Hello, I'm BailsBot.") + ' ' + help_message(),
        reply_markup=start_keyboard()
    )


async def orders_list(query, chat_id, start, quantity, buttons_data, message_id=None):
    keyboard = types.InlineKeyboardMarkup(row_width=5)

    inline_orders_buttons = (
        types.InlineKeyboardButton(
            text='\u2b05\ufe0f',
            callback_data='{} {}'.format(buttons_data, start - config.ORDERS_COUNT)
        ),
        types.InlineKeyboardButton(
            text='\u27a1\ufe0f',
            callback_data='{} {}'.format(buttons_data, start + config.ORDERS_COUNT)
        )
    )

    if quantity == 0:
        keyboard.row(*inline_orders_buttons)
        text = _('There are no orders.')
        if message_id is None:
            await bot.send_message(chat_id, text, reply_markup=keyboard)
        else:
            await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        return

    all_orders = await database.orders.find(query).to_list(length=start + config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    for i, order in enumerate(orders):
        line = f'{i + 1}. '
        price = order.get('price')
        if order['type']:
            if price:
                line += '1 {} → {:.2f} {}'.format(order['crypto'], price, order['fiat'])
            else:
                line += '{} → {}'.format(order['crypto'], order['fiat'])
        else:
            if price:
                line += '{:.2f} {} → 1 {}'.format(price, order['fiat'], order['crypto'])
            else:
                line += '{} → {}'.format(order['fiat'], order['crypto'])
        line += ' ({})'.format(order['username'])
        lines.append(line)
        buttons.append(
            types.InlineKeyboardButton(
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
        await bot.send_message(
            chat_id, text, reply_markup=keyboard, parse_mode='Markdown'
        )
    else:
        await bot.edit_message_text(
            text, chat_id, message_id, reply_markup=keyboard, parse_mode='Markdown'
        )


async def show_orders(call, query, start, buttons_data):
    quantity = await database.orders.count_documents(query)

    if start >= quantity > 0:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no more orders.")
        )
        return

    try:
        await bot.answer_callback_query(callback_query_id=call.id)
        await orders_list(
            query, call.message.chat.id, start, quantity, buttons_data,
            message_id=call.message.message_id
        )
    except MessageNotModified:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no previous orders.")
        )


@dp.callback_query_handler(lambda call: call.data.startswith('orders'), state=any_state)
async def orders_button(call):
    start = max(0, int(call.data.split()[1]))
    await show_orders(call, {'user_id': {'$ne': call.from_user.id}}, start, 'orders')


@dp.callback_query_handler(lambda call: call.data.startswith('my_orders'), state=any_state)
async def my_orders_button(call):
    start = max(0, int(call.data.split()[1]))
    await show_orders(call, {'user_id': call.from_user.id}, start, 'my_orders')


def order_handler(handler):
    async def decorator(call):
        order_id = call.data.split()[1]
        order = await database.orders.find_one({'_id': ObjectId(order_id)})

        if not order:
            await bot.answer_callback_query(
                callback_query_id=call.id,
                text=_('Order is not found.')
            )
            return

        return await handler(call, order)
    return decorator


async def show_order(order, chat_id, user_id, can_hide):
    keyboard = types.InlineKeyboardMarkup()

    if order['user_id'] == user_id:
        keyboard.row(
            types.InlineKeyboardButton(
                text=_('Delete'),
                callback_data='delete {}'.format(order['_id'])
            )
        )

    if order.get('latitude') is not None and order.get('longitude') is not None:
        location_message = await bot.send_location(
            chat_id, order['latitude'], order['longitude']
        )
        location_message_id = location_message.message_id
    else:
        location_message_id = -1

    if can_hide:
        keyboard.row(
            types.InlineKeyboardButton(
                text=_('Hide'),
                callback_data='hide {}'.format(location_message_id)
            )
        )

    lines = [
        '{}{} {} {} for {}\n'.format(
            'ID: {}\n'.format(order['_id']) if can_hide else '',
            order['username'],
            _('sells') if order['type'] else _('buys'),
            order['crypto'],
            order['fiat']
        )
    ]
    if order.get('sum'):
        if order['sum_currency'] == 'fiat':
            lines.append(
                _('Transaction sum:') + ' {:.2f} {}'.format(order['sum'], order['fiat'])
            )
        elif order['sum_currency'] == 'crypto':
            lines.append(
                _('Transaction sum:') + ' {:.8g} {}'.format(order['sum'], order['crypto'])
            )
    if order.get('price'):
        lines.append(
            _('Price:') + ' {:.2f} {}'.format(order['price'], order['fiat'])
        )
    if order.get('payment_method'):
        lines.append(
            _('Payment method:') + ' ' + order['payment_method']
        )
    if order.get('duration'):
        lines.append(
            _('Duration: {} days').format(order['duration'])
        )
    if order.get('comments'):
        lines.append(
            _('Comments:') + ' «{}»'.format(order['comments'])
        )
    await bot.send_message(
        chat_id, '\n'.join(lines), reply_markup=keyboard, parse_mode='Markdown'
    )


@dp.callback_query_handler(lambda call: call.data.startswith('get_order'), state=any_state)
@order_handler
async def get_order_button(call, order):
    await show_order(order, call.message.chat.id, call.from_user.id, True)
    await bot.answer_callback_query(callback_query_id=call.id)


@private_handler(commands=['id'])
@private_handler(regexp='ID: [a-f0-9]{24}')
async def get_order_command(message):
    try:
        order_id = message.text.split()[1]
    except IndexError:
        await bot.send_message(message.chat.id, _("Send order's ID as an argument."))
        return

    order = await database.orders.find_one({'_id': ObjectId(order_id)})
    if not order:
        await bot.send_message(message.chat.id, _('Order is not found.'))
        return
    await show_order(order, message.chat.id, message.from_user.id, False)


@dp.callback_query_handler(lambda call: call.data.startswith('delete'), state=any_state)
@order_handler
async def delete_button(call, order):
    delete_result = await database.orders.delete_one({'_id': order['_id'], 'user_id': call.from_user.id})
    await bot.answer_callback_query(
        callback_query_id=call.id,
        text=_('Order was deleted.') if delete_result.deleted_count > 0 else
        _("Couldn't delete order.")
    )


@dp.callback_query_handler(lambda call: call.data.startswith('hide'), state=any_state)
async def hide_button(call):
    await bot.delete_message(call.message.chat.id, call.message.message_id)
    location_message_id = call.data.split()[1]
    if location_message_id != '-1':
        await bot.delete_message(call.message.chat.id, location_message_id)


def state_handler(state):
    def decorator(handler):
        state_handlers[state.state] = handler
        return handler
    return decorator


@dp.callback_query_handler(lambda call: call.data == 'back', state=any_state)
async def previous_state(call, state):
    state_name = await state.get_state()
    if state_name in OrderCreation:
        new_state = await OrderCreation.previous()
        handler = state_handlers.get(new_state)
        if handler:
            error = await handler(call)
            if not error:
                return
        await state.set_state(state_name)
    return await bot.answer_callback_query(
        callback_query_id=call.id,
        text=_('You are not creating order.')
    )


@dp.callback_query_handler(lambda call: call.data == 'next', state=any_state)
async def next_state(call, state):
    state_name = await state.get_state()
    if state_name in OrderCreation:
        new_state = await OrderCreation.next()
        handler = state_handlers.get(new_state)
        if handler:
            error = await handler(call)
            if not error:
                return
        await state.set_state(state_name)
    return await bot.answer_callback_query(
        callback_query_id=call.id,
        text=_('You are not creating order.')
    )


async def create_order(message, order_type):
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
        'type': order_type
    })
    await OrderCreation.first()
    if order_type:
        answer = _('What currency do you want to sell?')
    else:
        answer = _('What currency do you want to buy?')

    await bot.send_message(
        message.chat.id, answer,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True, no_next=True)
        )
    )


@state_handler(OrderCreation.crypto)
async def create_order_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    if order['type']:
        answer = _('What currency do you want to sell?')
    else:
        answer = _('What currency do you want to buy?')

    await bot.edit_message_text(
        answer, call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_back=True)
        )
    )


@private_handler(commands=['buy'])
@private_handler(
    lambda msg: msg.text.startswith(emojize(':computer:'))
)
async def handle_buy(message):
    await create_order(message, order_type=0)


@private_handler(commands=['sell'])
@private_handler(
    lambda msg: msg.text.startswith(emojize(':dollar:'))
)
async def handle_sell(message):
    await create_order(message, order_type=1)


@private_handler(commands=['my'])
@private_handler(
    lambda msg: msg.text.startswith(emojize(':bust_in_silhouette:'))
)
async def handle_my_orders(message):
    query = {'user_id': message.from_user.id}
    quantity = await database.orders.count_documents(query)
    await orders_list(query, message.chat.id, 0, quantity, 'my_orders')


@private_handler(commands=['book'])
@private_handler(
    lambda msg: msg.text.startswith(emojize(':closed_book:'))
)
async def handle_book(message):
    query = {'user_id': {'$ne': message.from_user.id}}
    quantity = await database.orders.count_documents(query)
    await orders_list(query, message.chat.id, 0, quantity, 'orders')


@dp.callback_query_handler(lambda call: call.data == 'cancel', state=any_state)
async def cancel_order_creation(call, state):
    order = await database.creation.delete_one({'user_id': call.from_user.id})

    if not order.deleted_count:
        await bot.send_message(
            call.message.chat.id,
            _('You are not creating order.'),
            reply_markup=start_keyboard()
        )
        return True

    await state.finish()
    await bot.answer_callback_query(callback_query_id=call.id)
    await bot.send_message(
        call.message.chat.id,
        _('Order is cancelled.'),
        reply_markup=start_keyboard()
    )


@private_handler(state=OrderCreation.crypto)
async def choose_crypto(message, state):
    if not all(ch in ascii_letters for ch in message.text):
        return _('Currency may only contain letters.')

    currency = message.text.upper()

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {'$set': {'crypto': currency}},
        return_document=ReturnDocument.AFTER
    )

    await OrderCreation.fiat.set()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add('USD', 'EUR', 'RUB')

    if order['type']:
        answer = _('What currency do you want to buy?')
    else:
        answer = _('What currency do you want to sell?')

    await bot.send_message(
        message.chat.id, answer,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons(no_next=True)
        )
    )


@state_handler(OrderCreation.fiat)
async def choose_crypto_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    if order['type']:
        answer = _('What currency do you want to buy?')
    else:
        answer = _('What currency do you want to sell?')

    await bot.edit_message_text(
        answer, call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=inline_control_buttons()
        )
    )


@private_handler(state=OrderCreation.fiat)
async def choose_fiat(message, state):
    if not all(ch in ascii_letters for ch in message.text):
        return _('Currency may only contain letters.')

    currency = message.text.upper()

    order = await database.creation.find_one_and_update(
        {'user_id': message.from_user.id},
        {'$set': {'fiat': currency}},
        return_document=ReturnDocument.AFTER
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            text=order['crypto'],
            callback_data='sum crypto'
        ),
        types.InlineKeyboardButton(
            text=order['fiat'],
            callback_data='sum fiat'
        )
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await OrderCreation.sum.set()
    await bot.send_message(
        message.chat.id,
        _('Choose currency of order sum.'),
        reply_markup=keyboard
    )


@state_handler(OrderCreation.sum)
async def sum_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            text=order['crypto'],
            callback_data='sum crypto'
        ),
        types.InlineKeyboardButton(
            text=order['fiat'],
            callback_data='sum fiat'
        )
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await OrderCreation.sum.set()
    await bot.edit_message_text(
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
    await bot.answer_callback_query(callback_query_id=call.id)
    await bot.send_message(
        call.message.chat.id,
        _('Currency of order sum set. Send order sum in the next message.')
    )


async def validate_money(data, chat_id):
    try:
        money = float(data)
    except ValueError:
        await bot.send_message(chat_id, _('Send decimal number.'))
        return
    if money <= 0:
        await bot.send_message(chat_id, _('Send positive number.'))
        return

    return money


@state_handler(OrderCreation.price)
async def price_handler(call):
    order = await database.creation.find_one({'user_id': call.from_user.id})

    if not order:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_('You are not creating order.')
        )
        return True

    if 'sum_currency' in order and not 'sum' not in order:
        order = await database.creation.find_one_and_update(
            {'_id': order['_id']},
            {'$unset': {'sum_currency': True}},
            return_document=ReturnDocument.AFTER
        )

    await bot.edit_message_text(
        _('At what price do you want to sell?') if order['type'] else
        _('At what price do you want to buy?'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.sum)
async def choose_sum(message, state):
    transaction_sum = await validate_money(message.text, message.chat.id)
    if not transaction_sum:
        return

    order = await database.creation.find_one_and_update(
        {
            'user_id': message.from_user.id,
            'sum_currency': {'$exists': True}
        },
        {'$set': {'sum': transaction_sum}},
        return_document=ReturnDocument.AFTER
    )
    if not order:
        await bot.send_message(message.chat.id, _('Choose currency of sum with buttons.'))

    await OrderCreation.price.set()
    await bot.send_message(
        message.chat.id,
        _('At what price do you want to sell?') if order['type'] else
        _('At what price do you want to buy?'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@state_handler(OrderCreation.payment_type)
async def payment_type_handler(call):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(text=_('Cash'), callback_data='cash type'),
        types.InlineKeyboardButton(text=_('Cashless'), callback_data='cashless type')
    )
    for row in inline_control_buttons():
        keyboard.row(*row)

    await bot.edit_message_text(
        _('Choose payment type.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=keyboard
    )


@private_handler(state=OrderCreation.price)
async def choose_price(message, state):
    price = await validate_money(message.text, message.chat.id)
    if not price:
        return
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'price': price}}
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(text=_('Cash'), callback_data='cash type'),
        types.InlineKeyboardButton(text=_('Cashless'), callback_data='cashless type')
    )
    for row in inline_control_buttons():
        keyboard.row(*row)
    await OrderCreation.payment_type.set()
    await bot.send_message(
        message.chat.id,
        _('Choose payment type.'),
        reply_markup=keyboard
    )


@state_handler(OrderCreation.payment_method)
async def payment_method_handler(call):
    await bot.edit_message_text(
        _('Send payment method.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.payment_type)
async def message_in_payment_type(message, state):
    await bot.send_message(
        message.chat.id,
        _('Press on one of the buttons to choose payment type.')
    )


@dp.callback_query_handler(lambda call: call.data == 'cash type', state=OrderCreation.payment_type)
async def cash_payment_type(call):
    await OrderCreation.location.set()
    await bot.edit_message_text(
        _('Send location of a preferred meeting point.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.location, content_types=types.ContentType.TEXT)
async def wrong_location(message, state):
    await bot.send_message(
        message.chat.id,
        _('Send location object with point on the map.'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@state_handler(OrderCreation.duration)
async def duration(call):
    await bot.edit_message_text(
        _('Send duration of order in days.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.location, content_types=types.ContentType.LOCATION)
async def choose_location(message, state):
    location = message.location
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'latitude': location.latitude, 'longitude': location.longitude}}
    )
    await OrderCreation.duration.set()
    await bot.send_message(
        message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'cashless type', state=OrderCreation.payment_type)
@dp.callback_query_handler(lambda call: call.data == 'back', state=payment_method_cashless)
async def cashless_payment_type(call):
    await payment_method_cashless.set()
    await bot.edit_message_text(
        _('Send payment method.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@state_handler(OrderCreation.location)
async def location_handler(call):
    await bot.edit_message_text(
        _('Send location of a preferred meeting point.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.payment_method)
async def choose_payment_method(message, state):
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_method': message.text}}
    )
    await OrderCreation.duration.set()
    await bot.send_message(
        message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@dp.callback_query_handler(lambda call: call.data == 'next', state=payment_method_cashless)
@state_handler(OrderCreation.duration)
async def duration_handler(call):
    await bot.edit_message_text(
        _('Send duration of order in days.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=payment_method_cashless)
async def choose_payment_method_cashless(message, state):
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'payment_method': message.text}},
        return_document=ReturnDocument.AFTER
    )
    await OrderCreation.duration.set()
    await bot.send_message(
        message.chat.id,
        _('Send duration of order in days.'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@state_handler(OrderCreation.comments)
async def comment_handler(call):
    await bot.edit_message_text(
        _('Add any additional comments.'),
        call.message.chat.id, call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@private_handler(state=OrderCreation.duration)
async def choose_duration(message, state):
    try:
        duration = int(message.text)
        if duration <= 0:
            raise ValueError
    except ValueError:
        await bot.send_message(message.chat.id, _('Send integer.'))
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'duration': duration}}
    )

    await OrderCreation.comments.set()
    await bot.send_message(
        message.chat.id,
        _('Add any additional comments.'),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=inline_control_buttons())
    )


@state_handler(OrderCreation.comments)
async def choose_comments_handler(call):
    order = await database.creation.find_one_and_delete(
        {'user_id': call.from_user.id}
    )
    await bot.answer_callback_query(callback_query_id=call.id)
    if order:
        inserted_order = await database.orders.insert_one(order)
        await bot.send_message(
            call.message.chat.id,
            _('Order is set.') + '\nID: {}'.format(inserted_order.inserted_id),
            reply_markup=start_keyboard()
        )
    await dp.get_current().current_state().finish()


@private_handler(state=OrderCreation.comments)
async def choose_comments(message, state):
    comments = message.text
    if len(comments) > 150:
        await bot.send_message(
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
        await bot.send_message(
            message.chat.id,
            _('Order is set.') + '\nID: {}'.format(inserted_order.inserted_id),
            reply_markup=start_keyboard()
        )
    await state.finish()


@private_handler()
async def handle_default(message):
    await bot.send_message(message.chat.id, _('Unknown command.'))
