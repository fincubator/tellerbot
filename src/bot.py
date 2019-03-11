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
from .database import database, MongoStorage

import re
import math
import json
import asyncio

from pymongo.collection import ReturnDocument
from bson.objectid import ObjectId

from aiogram import Bot, executor, types
from aiogram.dispatcher import Dispatcher
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.middlewares.i18n import I18nMiddleware
from aiogram.utils.exceptions import MessageNotModified


SETTINGS = [
    {'name': 'BitShares username', 'field': 'username', 'default': None}
]

CURRENCIES = ['USD', 'EUR', 'RUB']


bot = Bot(token=config.TOKEN, loop=asyncio.get_event_loop())
storage = MongoStorage()
dp = Dispatcher(bot, storage=storage)


i18n = I18nMiddleware('bot', config.LOCALES_DIR)
dp.middleware.setup(i18n)
_ = i18n.gettext


def user_handler(handler):
    async def decorator(obj, *args, **kwargs):
        user = await database.users.find_one({'id': obj.from_user.id})
        return await handler(obj, user, *args, **kwargs)
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
    await database.users.update_one(
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


async def orders_list(chat_id, start, quantity, message_id=None):
    keyboard = types.InlineKeyboardMarkup(row_width=5)

    inline_orders_buttons = (
        types.InlineKeyboardButton(
            text='\u2b05\ufe0f', callback_data='orders {}'.format(start - config.ORDERS_COUNT)
        ),
        types.InlineKeyboardButton(
            text='\u27a1\ufe0f', callback_data='orders {}'.format(start + config.ORDERS_COUNT)
        )
    )

    if quantity == 0:
        keyboard.row(*inline_orders_buttons)
        text = _("There are no orders.")
        if message_id is None:
            await bot.send_message(chat_id, text, reply_markup=keyboard)
        else:
            await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        return

    all_orders = await database.orders.find().to_list(length=start + config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    for i, order in enumerate(orders):
        line = '{}. {} - {:.2f} {}/BTS'.format(
            i + 1, order['username'], order['price'], order['currency'],
        )
        if order['min_limit'] or order['max_limit']:
            line += ' ({:.2f}'.format(order['min_limit'])
            if order['max_limit']:
                line += ' - {:.2f}'.format(order['max_limit'])
            line += ')'
        lines.append(line)
        buttons.append(
            types.InlineKeyboardButton(text='{}'.format(i + 1), callback_data='get_order {}'.format(order['_id']))
        )

    keyboard.add(*buttons)
    keyboard.row(*inline_orders_buttons)

    text = _('[Page {} of {}]\n').format(
        math.ceil(start / config.ORDERS_COUNT) + 1,
        math.ceil(quantity / config.ORDERS_COUNT)
    ) + '\n'.join(lines)

    if message_id is None:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    else:
        await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)


@dp.callback_query_handler(lambda call: call.data.startswith('orders'))
@user_handler
async def orders_button(call, user, *args, **kwargs):
    start = max(0, int(call.data.split()[1]))

    quantity = await database.orders.count_documents({})

    if start >= quantity > 0:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no more orders.")
        )
        return

    try:
        await bot.answer_callback_query(callback_query_id=call.id)
        await orders_list(call.message.chat.id, start, quantity, message_id=call.message.message_id)
    except MessageNotModified:
        await bot.answer_callback_query(
            callback_query_id=call.id,
            text=_("There are no previous orders.")
        )


def order_handler(handler):
    async def decorator(call, *args, **kwargs):
        order_id = call.data.split()[1]
        order = await database.orders.find_one({'_id': ObjectId(order_id)})

        if not order:
            await bot.answer_callback_query(
                callback_query_id=call.id,
                text=_("Order is not found.")
            )
            return

        new_handler = user_handler(handler)
        return await new_handler(call, order, *args, **kwargs)
    return decorator


@dp.callback_query_handler(lambda call: call.data.startswith('get_order'))
@order_handler
async def get_order_button(call, user, order, *args, **kwargs):
    keyboard = types.InlineKeyboardMarkup()

    if order['user_id'] == user['id']:
        keyboard.row(
            types.InlineKeyboardButton(text=_('Delete'), callback_data='delete {}'.format(order['_id']))
        )
    else:
        keyboard.row(
            types.InlineKeyboardButton(text=_('Accept'), callback_data='accept {}'.format(order['_id']))
        )

    location_message = await bot.send_location(call.message.chat.id, order['latitude'], order['longitude'])

    keyboard.row(
        types.InlineKeyboardButton(text=_('Hide'), callback_data='hide {}'.format(location_message.message_id))
    )

    lines = [
        _('Username: {username}'),
        _('Price: {price:.2f} {currency}/BTS'),
        _('Minimum limit: {min_limit:.2f}')
    ]
    if order['max_limit']:
        lines.append(
            _('Maximum limit: {max_limit:.2f}')
        )
    lines.append(
        _('Possible distance: {radius:.2f}')
    )
    if order['comments']:
        lines.append(
            _('Comments: «{comments}»')
        )

    await bot.answer_callback_query(callback_query_id=call.id)
    await bot.send_message(
        call.message.chat.id,
        '\n'.join(lines).format(
            username=order['username'],
            price=order['price'],
            currency=order['currency'],
            min_limit=order['min_limit'],
            max_limit=order['max_limit'],
            radius=order['radius'],
            comments=order['comments']
        ),
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda call: call.data.startswith('delete'))
@order_handler
async def delete_button(call, user, order, *args, **kwargs):
    delete_result = await database.orders.delete_one({'_id': order['_id'], 'user_id': call.from_user.id})
    await bot.answer_callback_query(
        callback_query_id=call.id,
        text=_('Order was deleted.') if delete_result.deleted_count > 0 else _("Couldn't delete order.")
    )


@dp.callback_query_handler(lambda call: call.data.startswith('accept'))
@order_handler
async def accept_button(call, user, order, *args, **kwargs):
    await database.users.update_one({'_id': user['_id']}, {'$set': {'order_chat_id': order['user_id']}})
    await storage.set_state(call.from_user.id, 'message_for_seller')
    await bot.answer_callback_query(callback_query_id=call.id)
    await bot.send_message(
        call.message.chat.id,
        text=_("Send your message for the seller and I will forward it.")
    )


@private_handler(state='message_for_seller')
async def forward_to_seller(message, user, state, *args, **kwargs):
    result = await bot.forward_message(
        chat_id=user['order_chat_id'],
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )
    await database.users.update_one({'_id': user['_id']}, {'$unset': {'order_chat_id': True}})

    await bot.send_message(
        message.chat.id,
        _("Your message was forwarded to the seller.") if result else
        _("Couldn't forward your message to the seller.")
    )
    await state.finish()


@dp.callback_query_handler(lambda call: call.data.startswith('hide'))
@user_handler
async def hide_button(call, user, *args, **kwargs):
    location_message_id = call.data.split()[1]
    await bot.delete_message(call.message.chat.id, call.message.message_id)
    await bot.delete_message(call.message.chat.id, location_message_id)


@private_handler(commands=['buy'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4bb')
)
async def handle_buy(message, user, *args, **kwargs):
    quantity = await database.orders.count_documents({})
    await orders_list(message.chat.id, 0, quantity)


async def start_order(message, user):
    await database.creation.insert_one({
        'user_id': message.from_user.id,
        'username': user['username']
    })

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*CURRENCIES)

    await bot.send_message(
        message.chat.id,
        _('What currency do you want to buy?'),
        reply_markup=markup
    )
    await storage.set_state(message.from_user.id, 'currency')


@private_handler(commands=['sell'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\U0001f4b5')
)
async def handle_sell(message, user, *args, **kwargs):
    username = user.get('username')
    if not username:
        await bot.send_message(
            message.chat.id,
            _('Send your Bitshares username.')
        )
        await storage.set_state(user['id'], 'order_username')
        return

    await start_order(message, user)


@private_handler(state='*', commands=['cancel'])
async def cancel_sell(message, user, state, *args, **kwargs):
    await state.finish()
    await bot.send_message(message.chat.id, _('Order is cancelled.'))


@private_handler(state='currency')
async def choose_currency(message, user, state, *args, **kwargs):
    currency = message.text.upper()
    if currency not in CURRENCIES:
        await bot.send_message(message.chat.id, _("Choose from the options on reply keyboard."))
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'currency': currency}}
    )
    await state.set_state('price')
    await bot.send_message(
        message.chat.id,
        _('At what price do you want to sell BTS?'),
        reply_markup=types.ReplyKeyboardRemove()
    )


async def validate_money(data, chat_id):
    try:
        money = float(data)
    except ValueError:
        await bot.send_message(
            chat_id,
            _("Send decimal number or /cancel")
        )
        return
    if money <= 0:
        await bot.send_message(
            chat_id,
            _("Send positive number or /cancel")
        )
        return

    return money


@private_handler(state='price')
async def choose_price(message, user, state, *args, **kwargs):
    price = await validate_money(message.text, message.chat.id)
    if not price:
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'price': price}}
    )
    await state.set_state('min_limit')
    await bot.send_message(
        message.chat.id,
        _('Would you like to have minimum amount limit? (Send "No" to skip)'),
        reply_markup=types.ReplyKeyboardRemove()
    )


@private_handler(state='min_limit')
async def choose_min(message, user, state, *args, **kwargs):
    if message.text.lower() == 'no':
        min_limit = 0
    else:
        min_limit = await validate_money(message.text, message.chat.id)
        if not min_limit:
            return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'min_limit': min_limit}}
    )
    await state.set_state('max_limit')
    await bot.send_message(
        message.chat.id,
        _('Would you like to have maximum amount limit? (Send "No" to skip)'),
        reply_markup=types.ReplyKeyboardRemove()
    )


@private_handler(state='max_limit')
async def choose_max(message, user, state, *args, **kwargs):
    if message.text.lower() == 'no':
        max_limit = None
    else:
        max_limit = await validate_money(message.text, message.chat.id)
        if not max_limit:
            return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'max_limit': max_limit}}
    )
    await state.set_state('location')
    await bot.send_message(
        message.chat.id,
        _('Send location of a preferred meeting point.'),
        reply_markup=types.ReplyKeyboardRemove()
    )


@private_handler(state='location', content_types=types.ContentType.TEXT)
async def wrong_location(message, user, state, *args, **kwargs):
    await bot.send_message(message.chat.id, _("Send location object with point on the map in message."))


@private_handler(state='location', content_types=types.ContentType.LOCATION)
async def choose_location(message, user, state, *args, **kwargs):
    location = message.location
    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'latitude': location.latitude, 'longitude': location.longitude}}
    )
    await state.set_state('radius')
    await bot.send_message(
        message.chat.id,
        _('Send a distance you are ready to pass.'),
        reply_markup=types.ReplyKeyboardRemove()
    )


@private_handler(state='radius', content_types=types.ContentType.LOCATION)
async def choose_radius(message, user, state, *args, **kwargs):
    radius = await validate_money(message.text, message.chat.id)
    if not radius:
        return

    await database.creation.update_one(
        {'user_id': message.from_user.id},
        {'$set': {'radius': radius}}
    )
    await state.set_state('comments')
    await bot.send_message(
        message.chat.id,
        _('Add any additional comments. (Send "No" to skip)'),
        reply_markup=types.ReplyKeyboardRemove()
    )


@private_handler(state='comments')
async def choose_comments(message, user, state, *args, **kwargs):
    comments = message.text
    if len(comments) > 150:
        await bot.send_message(message.chat.id, _("Comment should have less than 150 characters (your comment has {} characters).").format(len(comments)))
        return

    if comments.lower() == "no":
        comments = None

    order = await database.creation.find_one_and_delete({'user_id': message.from_user.id})
    order['comments'] = comments
    await database.orders.insert_one(order)

    await bot.send_message(message.chat.id, _('Order is set.'))
    await state.finish()


async def update_username(message, user):
    username = message.text
    if not username:
        await bot.send_message(message.chat.id, 'This is not a valid username.')
        return

    result = await database.users.find_one_and_update(
        {'_id': user['_id']},
        {'$set': {'username': username}},
        return_document=ReturnDocument.AFTER
    )
    return result


@private_handler(state='username')
async def set_username(message, user, state, *args, **kwargs):
    user = await update_username(message, user)
    if user is not None:
        await state.finish()
        await bot.send_message(message.chat.id, 'Username set.')


@private_handler(state='order_username')
async def order_username(message, user, state, *args, **kwargs):
    user = await update_username(message, user)
    if user is not None:
        await start_order(message, user)


@dp.callback_query_handler(lambda call: call.data == 'bitshares username')
@user_handler
async def settings_username(call, user, *args, **kwargs):
    await bot.answer_callback_query(callback_query_id=call.id)
    reply = await bot.send_message(
        call.message.chat.id,
        'Send your Bitshares username.'
    )
    await storage.set_state(call.from_user.id, 'username')


@private_handler(commands=['settings'])
@private_handler(
    lambda msg: msg.text.encode('unicode-escape').startswith(b'\\u2699\\ufe0f')
)
async def handle_settings(message, user, *args, **kwargs):
    user_info = []
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for setting in SETTINGS:
        option = user.get(setting['field'])
        if option is None:
            option = '\U0001f6ab'
        user_info.append('{}: {}'.format(_(setting['name']), option))
        keyboard.add(
            types.InlineKeyboardButton(
                text=_(setting['name']),
                callback_data=setting['name'].lower()
            )
        )
    await bot.send_message(
        message.chat.id,
        _('Choose which option you would like to change.') + '\n\n' +
        '\n'.join(user_info),
        reply_markup=keyboard
    )


@private_handler()
async def handle_default(message, user, *args, **kwargs):
    await bot.send_message(message.chat.id, _('Unknown command.'))
