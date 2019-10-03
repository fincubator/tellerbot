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
from time import time

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ParseMode
from aiogram.utils.emoji import emojize
from aiogram.utils.exceptions import MessageNotModified

import config
from ..bot import tg, dp, private_handler, state_handler, state_handlers
from ..i18n import _
from ..utils import normalize_money, LOW_EXP, HIGH_EXP, MoneyValidationError


def help_message():
    return _(
        "Hello, I'm TellerBot. "
        'I can help you meet with people that you can swap money with.\n\n'
        'Choose one of the options on your keyboard.'
    )


def start_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton(emojize(':heavy_plus_sign: ') + _('Create order')),
        KeyboardButton(emojize(':bust_in_silhouette: ') + _('My orders')),
        KeyboardButton(emojize(':closed_book: ') + _('Order book')),
        KeyboardButton(emojize(':abcd: ') + _('Language')),
        KeyboardButton(emojize(':question: ') + _('Support'))
    )
    return keyboard


def inline_control_buttons(no_back=False, no_next=False):
    buttons = []
    row = []
    if not no_back:
        row.append(InlineKeyboardButton(_('Back'), callback_data='state back'))
    if not no_next:
        row.append(InlineKeyboardButton(_('Skip'), callback_data='state next'))
    if row:
        buttons.append(row)
    return buttons


async def validate_money(data, chat_id):
    try:
        money = decimal.Decimal(data)
    except decimal.InvalidOperation:
        raise MoneyValidationError(_('Send decimal number.'))
    if money <= 0:
        raise MoneyValidationError(_('Send positive number.'))
    if money >= HIGH_EXP:
        raise MoneyValidationError(_('Send number less than') + f' {HIGH_EXP:,f}')

    normalized = normalize_money(money)
    if normalized.is_zero():
        raise MoneyValidationError(_('Send number greater than') + f' {LOW_EXP:.8f}')
    return normalized


async def orders_list(
    cursor, chat_id, start, quantity, buttons_data,
    user_id=None, message_id=None, invert=False
):
    keyboard = InlineKeyboardMarkup(row_width=min(config.ORDERS_COUNT // 2, 8))

    inline_orders_buttons = (
        InlineKeyboardButton(
            emojize(':arrow_left:'), callback_data='{} {} {}'.format(
                buttons_data, start - config.ORDERS_COUNT, int(invert)
            )
        ),
        InlineKeyboardButton(
            emojize(':arrow_right:'), callback_data='{} {} {}'.format(
                buttons_data, start + config.ORDERS_COUNT, int(invert)
            )
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

    all_orders = await cursor.to_list(length=start + config.ORDERS_COUNT)
    orders = all_orders[start:]

    lines = []
    buttons = []
    current_time = time()
    for i, order in enumerate(orders):
        line = ''

        if user_id is None:
            if 'expiration_time' not in order or order['expiration_time'] > current_time:
                line += emojize(':arrow_forward: ')
            else:
                line += emojize(':pause_button: ')

        if 'sum_sell' in order:
            line += '{:,.5f} '.format(order['sum_sell'].to_decimal())
        line += '{} → '.format(order['sell'])

        if 'sum_buy' in order:
            line += '{:,.5f} '.format(order['sum_buy'].to_decimal())
        line += order['buy']

        if 'price_sell' in order:
            if invert:
                line += ' ({:,.5f} {}/{})'.format(
                    order['price_buy'].to_decimal(), order['buy'], order['sell']
                )
            else:
                line += ' ({:,.5f} {}/{})'.format(
                    order['price_sell'].to_decimal(), order['sell'], order['buy']
                )

        if user_id is not None and order['user_id'] == user_id:
            line = f'*{line}*'

        lines.append(f'{i + 1}. {line}')
        buttons.append(InlineKeyboardButton(
            '{}'.format(i + 1), callback_data='get_order {}'.format(order['_id'])
        ))

    keyboard.row(InlineKeyboardButton(
        _('Invert'), callback_data='{} {} {}'.format(
            buttons_data, start - config.ORDERS_COUNT, int(not invert)
        )
    ))
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


async def show_orders(call, cursor, start, quantity, buttons_data, invert, user_id=None):
    if start >= quantity > 0:
        await call.answer(_('There are no more orders.'))
        return

    try:
        await call.answer()
        await orders_list(
            cursor, call.message.chat.id, start, quantity, buttons_data,
            user_id=user_id, message_id=call.message.message_id, invert=invert
        )
    except MessageNotModified:
        await call.answer(_('There are no previous orders.'))


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

    keyboard.row(InlineKeyboardButton(
        _('Invert'), callback_data='{} {} {} {}'.format(
            'revert' if invert else 'invert',
            order['_id'], location_message_id, int(edit)
        )
    ))

    if edit:
        buttons = []
        for i, (field, value) in enumerate(lines_format.items()):
            if value is not None:
                lines.append(f'{i + 1}. {field_names[field]} {value}')
            elif edit:
                lines.append(f'{i + 1}. {field_names[field]} -')
            buttons.append(InlineKeyboardButton(
                f'{i + 1}', callback_data='edit {} {} {} {}'.format(
                    order['_id'], field, location_message_id, int(invert)
                )
            ))

        keyboard.add(*buttons)
        keyboard.row(InlineKeyboardButton(
            _('Finish'), callback_data='{} {} {} 0'.format(
                'invert' if invert else 'revert',
                order['_id'], location_message_id
            )
        ))

    else:
        for field, value in lines_format.items():
            if value is not None:
                lines.append(field_names[field] + ' ' + value)

        keyboard.row(
            InlineKeyboardButton(
                _('Similar'), callback_data='similar {}'.format(order['_id'])
            ),
            InlineKeyboardButton(
                _('Match'), callback_data='match {}'.format(order['_id'])
            )
        )

        if order['user_id'] == user_id:
            keyboard.row(
                InlineKeyboardButton(
                    _('Edit'), callback_data='{} {} {} 1'.format(
                        'invert' if invert else 'revert',
                        order['_id'], location_message_id
                    )
                ),
                InlineKeyboardButton(
                    _('Delete'), callback_data='delete {} {}'.format(
                        order['_id'], location_message_id
                    )
                )
            )

        keyboard.row(InlineKeyboardButton(
            _('Hide'), callback_data='hide {}'.format(location_message_id)
        ))

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
