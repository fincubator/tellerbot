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


import asyncio
from decimal import Decimal
from time import time

from bson.objectid import ObjectId
from bson.decimal128 import Decimal128

from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils import markdown

from config import SUPPORT_CHAT_ID
from src.handlers import tg, dp, private_handler
from src.handlers import show_order, validate_money, start_keyboard
from src.database import database
from src.escrow import SUPPORTED_BANKS, EscrowOffer
from src.escrow import get_escrow_class, get_escrow_instance
from src.i18n import _
from src import states
from src.utils import normalize_money, MoneyValidationError


def is_address_valid(address):
    return len(address) <= 64


async def call_later(delay, callback, *args, **kwargs):
    await asyncio.sleep(delay)
    return (await callback(*args, **kwargs))


def escrow_callback_handler(*args, state=any_state, **kwargs):
    def decorator(handler):
        @dp.callback_query_handler(*args, state=state, **kwargs)
        async def wrapper(call: types.CallbackQuery):
            offer_id = call.data.split()[1]
            offer = await database.escrow.find_one({
                '_id': ObjectId(offer_id)
            })
            if not offer:
                await call.answer(_('Offer is not active.'))
                return

            return await handler(call, EscrowOffer(**offer))
        return wrapper
    return decorator


def escrow_message_handler(*args, **kwargs):
    def decorator(handler):
        @private_handler(*args, **kwargs)
        async def wrapper(message: types.Message, state: FSMContext):
            offer = await database.escrow.find_one({
                'pending_input_from': message.from_user.id
            })
            if not offer:
                await tg.send_message(message.chat.id, _('Offer is not active.'))
                return

            return await handler(message, state, EscrowOffer(**offer))
        return wrapper
    return decorator


@escrow_message_handler(state=states.Escrow.sum)
async def set_escrow_sum(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    try:
        escrow_sum = await validate_money(message.text, message.chat.id)
    except MoneyValidationError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.orders.find_one({'_id': offer.order})
    order_sum = order.get(offer.sum_currency)
    if order_sum and escrow_sum > order_sum.to_decimal():
        await tg.send_message(
            message.chat.id, _("Send number not exceeding order's sum.")
        )
        return

    update_dict = {offer.sum_currency: Decimal128(escrow_sum)}
    new_currency = 'sell' if offer.sum_currency == 'sum_buy' else 'buy'
    update_dict[f'sum_{new_currency}'] = Decimal128(normalize_money(
        escrow_sum * order[f'price_{new_currency}'].to_decimal()
    ))
    escrow_sum = update_dict[f'sum_{offer.type}']
    update_dict['sum_fee_up'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('1.05')
    ))
    update_dict['sum_fee_down'] = Decimal128(normalize_money(
        escrow_sum.to_decimal() * Decimal('0.95')
    ))

    await offer.update_document({
        '$set': update_dict, '$unset': {'sum_currency': True}
    })
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    if offer.type == 'buy':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    elif offer.type == 'sell':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data=f'accept_fee {offer._id}'
        ),
        InlineKeyboardButton(
            _('No'), callback_data=f'decline_fee {offer._id}'
        )
    )
    answer = answer.format(update_dict[sum_fee_field], offer[offer.type])
    await tg.send_message(message.chat.id, answer, reply_markup=keyboard)
    await states.Escrow.fee.set()


async def ask_credentials(
    call: types.CallbackQuery, offer: EscrowOffer, update_dict: dict = {}
):
    await call.answer()
    fiat = 'RUB'
    is_user_init = call.from_user.id == offer.init['id']
    if is_user_init and fiat in {offer.buy, offer.sell}:
        keyboard = InlineKeyboardMarkup()
        for bank in SUPPORTED_BANKS:
            keyboard.row(InlineKeyboardButton(
                bank, callback_data=f'bank {offer._id} {bank}'
            ))
        await tg.send_message(
            call.message.chat.id, _('Choose bank.'), reply_markup=keyboard
        )
        await states.Escrow.bank.set()
        if update_dict:
            await offer.update_document({'$set': update_dict})
        return

    update_dict['pending_input_from'] = call.from_user.id
    await offer.update_document({'$set': update_dict})

    if is_user_init:
        receive_currency = offer.sell
    elif offer.type == 'sell':
        await tg.send_message(
            call.message.chat.id,
            _('Send first and last 4 digits of your {} card number separated '
              'by space.').format(offer.buy)
        )
        await states.Escrow.receive_card_number.set()
        return
    else:
        receive_currency = offer.buy
    await tg.send_message(
        call.message.chat.id,
        _('Send your {} address.').format(receive_currency)
    )
    await states.Escrow.receive_address.set()


@escrow_callback_handler(
    lambda call: call.data.startswith('accept_fee '),
    state=states.Escrow.fee
)
async def pay_fee(call: types.CallbackQuery, offer: EscrowOffer):
    await ask_credentials(call, offer)


@escrow_callback_handler(
    lambda call: call.data.startswith('decline_fee '),
    state=states.Escrow.fee
)
async def decline_fee(call: types.CallbackQuery, offer: EscrowOffer):
    if (call.from_user.id == offer.init['id']) == (offer.type == 'buy'):
        sum_fee_field = 'sum_fee_up'
    else:
        sum_fee_field = 'sum_fee_down'
    update_dict = {sum_fee_field: offer[f'sum_{offer.type}']}
    await ask_credentials(call, offer, update_dict)


@escrow_callback_handler(
    lambda call: call.data.startswith('bank '),
    state=states.Escrow.bank
)
async def choose_bank(call: types.CallbackQuery, offer: EscrowOffer):
    bank = call.data.split()[2]
    if bank not in SUPPORTED_BANKS:
        await call.answer(_('This bank is not supported.'))
        return

    await offer.update_document({
        '$set': {
            'bank': bank,
            'pending_input_from': call.from_user.id
        }
    })
    await call.answer()
    if offer.type == 'buy':
        await tg.send_message(
            call.message.chat.id,
            _('Send first and last 4 digits of your {} card number separated '
              'by space.').format(offer.buy)
        )
        await states.Escrow.receive_card_number.set()
    else:
        await tg.send_message(
            call.message.chat.id,
            _('Send your {} address.').format(offer.sell)
        )
        await states.Escrow.receive_address.set()


@escrow_message_handler(state=states.Escrow.receive_card_number)
async def set_receive_card_number(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    digits = message.text.split()
    if len(digits) != 2:
        await tg.send_message(
            message.chat.id,
            _('You should send {} words separated by spaces.').format(2)
        )
        return

    if message.from_user.id == offer.init['id']:
        user_field = 'init'
    else:
        user_field = 'counter'

    await offer.update_document({
        '$set': {f'{user_field}.receive_address': ('*' * 8).join(digits)}
    })
    await tg.send_message(
        message.chat.id, _('Send your {} address.').format(offer[offer.type])
    )
    await states.Escrow.send_address.set()


@escrow_message_handler(state=states.Escrow.receive_address)
async def set_receive_address(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    if message.from_user.id == offer.init['id']:
        user_field = 'init'
        send_currency = offer.buy
        ask_name = offer.bank and offer.type == 'sell'
    else:
        user_field = 'counter'
        send_currency = offer.sell
        ask_name = offer.bank and offer.type == 'buy'

    await offer.update_document({
        '$set': {f'{user_field}.receive_address': message.text}
    })
    if ask_name:
        await tg.send_message(
            message.chat.id,
            _('Send your name, patronymic and first letter of surname '
              'separated by spaces.')
        )
        await states.Escrow.name.set()
    else:
        await tg.send_message(
            message.chat.id, _('Send your {} address.').format(send_currency)
        )
        await states.Escrow.send_address.set()


@escrow_message_handler(state=states.Escrow.send_address)
async def set_send_address(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    if not is_address_valid(message.text):
        await tg.send_message(message.chat.id, _('Address is invalid.'))
        return

    if message.from_user.id == offer.init['id']:
        await set_init_send_address(message.text, message, state, offer)
    else:
        await set_counter_send_address(message.text, message, state, offer)


@escrow_message_handler(state=states.Escrow.name)
async def set_name(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    name = message.text.split()
    if len(name) != 3:
        await tg.send_message(
            message.chat.id,
            _('You should send {} words separated by spaces.').format(3)
        )
        return
    name[2] = name[2][0] + '.'  # Leaving the first letter of surname with dot

    if offer.type == 'buy':
        user_field = 'counter'
        currency = offer.sell
    else:
        user_field = 'init'
        currency = offer.buy

    await offer.update_document({
        '$set': {f'{user_field}.name': ' '.join(name).upper()}
    })
    await tg.send_message(
        message.chat.id,
        _('Send first and last 4 digits of your {} card number separated by '
          'space.').format(currency)
    )
    await states.Escrow.send_card_number.set()


@escrow_message_handler(state=states.Escrow.send_card_number)
async def set_send_card_number(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    digits = message.text.split()
    if len(digits) != 2:
        await tg.send_message(
            message.chat.id,
            _('You should send {} words separated by spaces.').format(2)
        )
        return

    address = ('*' * 8).join(digits)
    if message.from_user.id == offer.init['id']:
        await set_init_send_address(address, message, state, offer)
    else:
        await set_counter_send_address(address, message, state, offer)


async def set_init_send_address(
    address: str, message: types.Message, state: FSMContext, offer: EscrowOffer
):
    await offer.update_document({
        '$set': {'init.send_address': address},
        '$unset': {'pending_input_from': True}
    })
    order = await database.orders.find_one({'_id': offer.order})
    await show_order(
        order, offer.counter['id'], offer.counter['id'],
        show_id=True, locale=offer.counter['locale']
    )
    locale = offer.counter['locale']
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Accept', locale=locale), callback_data=f'accept {offer._id}'
        ),
        InlineKeyboardButton(
            _('Decline', locale=locale), callback_data=f'decline {offer._id}'
        )
    )
    answer = _('You got an escrow offer to sell {} {} for {} {}', locale=locale).format(
        offer.sum_sell, offer.sell, offer.sum_buy, offer.buy
    )
    if offer.bank:
        answer += ' ' + _('using {}').format(offer.bank)
    answer += '.'
    await tg.send_message(offer.counter['id'], answer, reply_markup=buy_keyboard)
    sell_keyboard = InlineKeyboardMarkup()
    sell_keyboard.add(InlineKeyboardButton(
        _('Cancel'), callback_data=f'escrow_cancel {offer._id}'
    ))
    await tg.send_message(
        message.from_user.id, _('Offer sent.'),
        reply_markup=sell_keyboard
    )
    await state.finish()


@escrow_callback_handler(lambda call: call.data.startswith('accept '))
async def accept_offer(call: types.CallbackQuery, offer: EscrowOffer):
    await offer.update_document({
        '$set': {'pending_input_from': call.message.chat.id, 'react_time': time()}
    })
    answer = _('Do you agree to pay a fee of 5%?') + ' '
    if offer.type == 'buy':
        answer += _("(You'll get {} {})")
        sum_fee_field = 'sum_fee_down'
    elif offer.type == 'sell':
        answer += _("(You'll pay {} {})")
        sum_fee_field = 'sum_fee_up'
    answer = answer.format(offer[sum_fee_field], offer[offer.type])
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.add(
        InlineKeyboardButton(
            _('Yes'), callback_data=f'accept_fee {offer._id}'
        ),
        InlineKeyboardButton(
            _('No'), callback_data=f'decline_fee {offer._id}'
        )
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, answer, reply_markup=buy_keyboard)
    await states.Escrow.fee.set()


@escrow_callback_handler(lambda call: call.data.startswith('decline '))
async def decline_offer(call: types.CallbackQuery, offer: EscrowOffer):
    offer.react_time = time()
    await offer.delete_document()
    await tg.send_message(
        offer.init['id'],
        _('Your escrow offer was declined.', locale=offer.init['locale'])
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, _('Offer was declined.'))


async def set_counter_send_address(
    address: str, message: types.Message, state: FSMContext, offer: EscrowOffer
):
    template = (
        'to {escrow_receive_address} '
        'for {not_escrow_amount} {not_escrow_currency} '
        'from {not_escrow_send_address} to {not_escrow_receive_address} '
        'via escrow service on https://t.me/TellerBot'
    )
    if offer.type == 'buy':
        memo = template.format(**{
            'escrow_receive_address': offer.counter['receive_address'],
            'not_escrow_amount': offer.sum_sell,
            'not_escrow_currency': offer.sell,
            'not_escrow_send_address': message.text,
            'not_escrow_receive_address': offer.init['receive_address']
        })
        escrow_user = offer.init
        send_reply = True
    elif offer.type == 'sell':
        memo = template.format(**{
            'escrow_receive_address': offer.init['receive_address'],
            'not_escrow_amount': offer.sum_buy,
            'not_escrow_currency': offer.buy,
            'not_escrow_send_address': offer.init['send_address'],
            'not_escrow_receive_address': offer.counter['receive_address']
        })
        escrow_user = offer.counter
        send_reply = False

    await offer.update_document({
        '$set': {
            'counter.send_address': address,
            'memo': memo,
        },
        '$unset': {
            'pending_input_from': True
        }
    })
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Cancel', locale=escrow_user['locale']),
            callback_data=f'escrow_cancel {offer._id}'
        )
    )
    escrow_address = markdown.bold(get_escrow_class(offer[offer.type]).address)
    await state.finish()
    await get_escrow_instance(offer[offer.type]).check_transaction(
        offer._id,
        escrow_user['send_address'],
        offer.sum_fee_up.to_decimal(),
        offer[offer.type],
        offer.memo,
        escrow_sent_confirmation
    )
    answer = _('Send {} {} to address {}', locale=escrow_user['locale']).format(
        offer.sum_fee_up, offer[offer.type], escrow_address
    )
    answer += ' ' + _('with memo', locale=escrow_user['locale'])
    answer += ':\n' + markdown.code(memo),
    await tg.send_message(
        escrow_user['id'], answer,
        reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    if send_reply:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(
            _('Cancel'), callback_data=f'escrow_cancel {offer._id}'
        ))
        await tg.send_message(
            message.chat.id,
            _('Transfer information sent.') + ' ' +
            _("I'll notify you when transaction is complete."),
            reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_cancel '))
async def cancel_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.trx_id:
        return await cancel_confirmed_offer(call, offer)
    if offer.memo:
        if offer.type == 'buy':
            escrow_user = offer.init
        elif offer.type == 'sell':
            escrow_user = offer.counter
        if call.from_user.id != escrow_user['id']:
            return await call.answer(
                _("You can't cancel this offer until transaction will be verified.")
            )
        get_escrow_instance(offer[offer.type]).remove_from_queue(offer._id)

    sell_answer = _('Escrow was cancelled.', locale=offer.init['locale'])
    buy_answer = _('Escrow was cancelled.', locale=offer.counter['locale'])
    offer.cancel_time = time()
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        offer.init['id'], sell_answer,
        reply_markup=start_keyboard()
    )
    await tg.send_message(
        offer.counter['id'], buy_answer,
        reply_markup=start_keyboard()
    )
    sell_state = FSMContext(dp.storage, offer.init['id'], offer.init['id'])
    buy_state = FSMContext(dp.storage, offer.counter['id'], offer.counter['id'])
    await sell_state.finish()
    await buy_state.finish()


async def escrow_sent_confirmation(offer_id: ObjectId, trx_id: str):
    offer_document = await database.escrow.find_one({'_id': ObjectId(offer_id)})
    if not offer_document:
        return
    offer = EscrowOffer(**offer_document)

    if offer.type == 'buy':
        escrow_user = offer.init
        other_user = offer.counter
        new_currency = 'sell'
    elif offer.type == 'sell':
        escrow_user = offer.counter
        other_user = offer.init
        new_currency = 'buy'

    url = markdown.link(
        _('Transaction is confirmed.', locale=other_user['locale']),
        get_escrow_instance(offer[offer.type]).trx_url(trx_id)
    )
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Sent', locale=other_user['locale']),
            callback_data=f'tokens_sent {offer._id}'
        ),
        InlineKeyboardButton(
            _('Cancel', locale=other_user['locale']),
            callback_data=f'tokens_cancel {offer._id}'
        )
    )
    await offer.update_document({
        '$set': {'trx_id': trx_id}
    })
    answer = url + '\n'
    answer += _('Send {} {} to address {}', locale=other_user['locale']).format(
        offer[f'sum_{new_currency}'],
        offer[new_currency],
        escrow_user['receive_address']
    )
    answer += '.'
    await tg.send_message(
        other_user['id'], answer,
        reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    await tg.send_message(
        escrow_user['id'],
        _('Transaction is confirmed.', locale=escrow_user['locale']) + ' ' +
        _("I'll notify should you get {}.", locale=escrow_user['locale']).format(
            offer[new_currency]
        )
    )


async def cancel_confirmed_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        return_user = offer.init
        cancel_user = offer.counter
    elif offer.type == 'sell':
        return_user = offer.counter
        cancel_user = offer.init

    escrow_instance = get_escrow_instance(offer[offer.type])
    trx_url = await escrow_instance.transfer(
        return_user['send_address'], offer.sum_fee_up.to_decimal(), offer[offer.type]
    )
    cancel_answer = _('Escrow was cancelled.', locale=cancel_user['locale'])
    return_answer = _('Escrow was cancelled.', locale=return_user['locale'])
    return_answer += ' ' + markdown.link(
        _('You got your {} {} back.', locale=return_user['locale']).format(
            offer.sum_fee_up, offer[offer.type]
        ), trx_url
    )
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        cancel_user['id'], cancel_answer,
        reply_markup=start_keyboard()
    )
    await tg.send_message(
        return_user['id'], return_answer,
        reply_markup=start_keyboard()
    )


@escrow_callback_handler(lambda call: call.data.startswith('tokens_cancel '))
async def cancel_tokens_handler(call: types.CallbackQuery, offer: EscrowOffer):
    await cancel_confirmed_offer(call, offer)


@escrow_callback_handler(lambda call: call.data.startswith('tokens_sent '))
async def final_offer_confirmation(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        confirm_user = offer.init
        other_user = offer.counter
        new_currency = 'sell'
    elif offer.type == 'sell':
        confirm_user = offer.counter
        other_user = offer.init
        new_currency = 'buy'

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _('Yes', locale=confirm_user['locale']),
            callback_data=f'escrow_complete {offer._id}'
        )
    )
    reply = await tg.send_message(
        confirm_user['id'],
        _('Did you get {} from {}?', locale=confirm_user['locale']).format(
            offer[new_currency], other_user['send_address']
        ),
        reply_markup=keyboard
    )
    keyboard.add(
        InlineKeyboardButton(
            _('No', locale=confirm_user['locale']),
            callback_data=f'escrow_validate {offer._id}'
        )
    )
    await call_later(
        60 * 10, tg.edit_message_reply_markup,
        call.message.chat.id, reply.message_id,
        reply_markup=keyboard
    )
    await call.answer()
    await tg.send_message(
        other_user['id'],
        _("When your transfer is confirmed, I'll complete escrow.",
          locale=other_user['locale']),
        reply_markup=start_keyboard()
    )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_complete '))
async def complete_offer(call: types.CallbackQuery, offer: EscrowOffer):
    if offer.type == 'buy':
        recipient_user = offer.counter
        other_user = offer.init
    elif offer.type == 'sell':
        recipient_user = offer.init
        other_user = offer.counter

    await call.answer(_('Escrow is being completed, please wait.'))
    escrow_instance = get_escrow_instance(offer[offer.type])
    trx_url = await escrow_instance.transfer(
        recipient_user['receive_address'],
        offer.sum_fee_down.to_decimal(),
        offer[offer.type]
    )
    answer = _('Escrow is completed!', locale=other_user['locale'])
    recipient_answer = _('Escrow is completed!', locale=recipient_user['locale'])
    recipient_answer += ' ' + markdown.link(
        _('I sent you {} {}.', locale=recipient_user['locale']).format(
            offer.sum_fee_down, offer[offer.type]
        ), trx_url
    )
    await offer.delete_document()
    await tg.send_message(
        recipient_user['id'], recipient_answer,
        reply_markup=start_keyboard(), parse_mode=ParseMode.MARKDOWN
    )
    await tg.send_message(
        other_user['id'], answer,
        reply_markup=start_keyboard()
    )


@escrow_callback_handler(lambda call: call.data.startswith('escrow_validate '))
async def validate_offer(call: types.CallbackQuery, offer: EscrowOffer):
    escrow_instance = get_escrow_instance(offer[offer.type])
    await tg.send_message(
        SUPPORT_CHAT_ID,
        'Unconfirmed escrow.\nTransaction: {}\nMemo: {}'.format(
            escrow_instance.trx_url(offer.trx_id),
            markdown.code(offer.memo),
        )
    )
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _("We'll manually validate your request and decide on the return."),
        reply_markup=start_keyboard()
    )
