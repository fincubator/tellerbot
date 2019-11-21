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
"""Handlers for escrow exchange."""
import asyncio
import typing
from decimal import Decimal
from functools import wraps
from time import time

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import any_state
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import ParseMode
from aiogram.types import User
from aiogram.utils import markdown
from bson.decimal128 import Decimal128
from bson.objectid import ObjectId
from dataclasses import replace

from src import states
from src.bot import dp
from src.bot import tg
from src.config import SUPPORT_CHAT_ID
from src.database import database
from src.escrow import get_escrow_instance
from src.escrow import SUPPORTED_BANKS
from src.escrow.escrow_offer import EscrowOffer
from src.handlers.base import private_handler
from src.handlers.base import start_keyboard
from src.i18n import _
from src.money import money
from src.money import MoneyValueError
from src.money import normalize


async def get_card_number(
    text: str, chat_id: int
) -> typing.Optional[typing.Tuple[str, str]]:
    """Parse first and last 4 digits from card number in ``text``.

    If parsing is unsuccessful, send warning to ``chat_id`` and return
    None. Otherwise return tuple of first and last 4 digits of card number.
    """
    if len(text) < 8:
        await tg.send_message(chat_id, _("You should send at least 8 digits."))
        return None
    first = text[:4]
    last = text[-4:]
    if not first.isdigit() or not last.isdigit():
        await tg.send_message(chat_id, _("Can't get digits from message."))
        return None
    return (first, last)


@dp.async_task
async def call_later(delay: float, callback: typing.Callable, *args, **kwargs):
    """Call ``callback(*args, **kwargs)`` asynchronously after ``delay`` seconds."""
    await asyncio.sleep(delay)
    return await callback(*args, **kwargs)


def escrow_callback_handler(*args, state=any_state, **kwargs):
    """Simplify handling callback queries during escrow exchange.

    Add offer of ``EscrowOffer`` to arguments of decorated callback query handler.
    """

    def decorator(
        handler: typing.Callable[[types.CallbackQuery, EscrowOffer], typing.Any]
    ):
        @wraps(handler)
        @dp.callback_query_handler(*args, state=state, **kwargs)
        async def wrapper(call: types.CallbackQuery):
            offer_id = call.data.split()[1]
            offer = await database.escrow.find_one({"_id": ObjectId(offer_id)})
            if not offer:
                await call.answer(_("Offer is not active."))
                return

            return await handler(call, EscrowOffer(**offer))

        return wrapper

    return decorator


def escrow_message_handler(*args, **kwargs):
    """Simplify handling messages during escrow exchange.

    Add offer of ``EscrowOffer`` to arguments of decorated private message handler.
    """

    def decorator(
        handler: typing.Callable[[types.Message, FSMContext, EscrowOffer], typing.Any]
    ):
        @wraps(handler)
        @private_handler(*args, **kwargs)
        async def wrapper(message: types.Message, state: FSMContext):
            offer = await database.escrow.find_one(
                {"pending_input_from": message.from_user.id}
            )
            if not offer:
                await tg.send_message(message.chat.id, _("Offer is not active."))
                return

            return await handler(message, state, EscrowOffer(**offer))

        return wrapper

    return decorator


async def get_insurance(offer: EscrowOffer) -> Decimal:
    """Get insurance of escrow asset in ``offer`` taking limits into account."""
    offer_sum = offer[f"sum_{offer.type}"]
    asset = offer[offer.type]
    limits = await get_escrow_instance(asset).get_limits(asset)
    if not limits:
        return offer_sum
    insured = min(offer_sum, limits.single)
    cursor = database.escrow.aggregate(
        [{"$group": {"_id": 0, "insured_total": {"$sum": "$insured"}}}]
    )
    if await cursor.fetch_next:
        insured_total = cursor.next_object()["insured_total"].to_decimal()
        total_difference = limits.total - insured_total - insured
        if total_difference < 0:
            insured += total_difference
    return normalize(insured)


@escrow_message_handler(state=states.Escrow.amount)
async def set_escrow_sum(message: types.Message, state: FSMContext, offer: EscrowOffer):
    """Set sum and ask for fee payment agreement."""
    try:
        offer_sum = money(message.text)
    except MoneyValueError as exception:
        await tg.send_message(message.chat.id, str(exception))
        return

    order = await database.orders.find_one({"_id": offer.order})
    order_sum = order.get(offer.sum_currency)
    if order_sum and offer_sum > order_sum.to_decimal():
        await tg.send_message(
            message.chat.id, _("Send number not exceeding order's sum.")
        )
        return

    update_dict = {offer.sum_currency: Decimal128(offer_sum)}
    new_currency = "sell" if offer.sum_currency == "sum_buy" else "buy"
    update_dict[f"sum_{new_currency}"] = Decimal128(
        normalize(offer_sum * order[f"price_{new_currency}"].to_decimal())
    )
    escrow_sum = update_dict[f"sum_{offer.type}"]
    update_dict["sum_fee_up"] = Decimal128(
        normalize(escrow_sum.to_decimal() * Decimal("1.05"))
    )
    update_dict["sum_fee_down"] = Decimal128(
        normalize(escrow_sum.to_decimal() * Decimal("0.95"))
    )
    offer = replace(offer, **update_dict)  # type: ignore

    if offer.sum_currency == offer.type:
        insured = await get_insurance(offer)
        update_dict["insured"] = Decimal128(insured)
        if offer_sum > insured:
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton(
                    _("Continue"), callback_data=f"accept_insurance {offer._id}"
                ),
                InlineKeyboardButton(
                    _("Cancel"), callback_data=f"init_cancel {offer._id}"
                ),
            )
            answer = _(
                "Escrow asset sum exceeds maximum amount to be insured. If you "
                "continue, only {} {} will be protected and refunded in "
                "case of unexpected events during the exchange."
            )
            answer = answer.format(insured, offer[offer.type])
            answer += "\n" + _(
                "You can send a smaller number, continue with partial "
                "insurance or cancel offer."
            )
            await tg.send_message(message.chat.id, answer, reply_markup=keyboard)
    else:
        await ask_fee(message.from_user.id, message.chat.id, offer)

    await offer.update_document({"$set": update_dict, "$unset": {"sum_currency": True}})


async def ask_fee(user_id: int, chat_id: int, offer: EscrowOffer):
    """Ask fee of any party."""
    answer = _("Do you agree to pay a fee of 5%?") + " "
    if (user_id == offer.init["id"]) == (offer.type == "buy"):
        answer += _("(You'll pay {} {})")
        sum_fee_field = "sum_fee_up"
    else:
        answer += _("(You'll get {} {})")
        sum_fee_field = "sum_fee_down"
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(_("Yes"), callback_data=f"accept_fee {offer._id}"),
        InlineKeyboardButton(_("No"), callback_data=f"decline_fee {offer._id}"),
    )
    answer = answer.format(offer[sum_fee_field], offer[offer.type])
    await tg.send_message(chat_id, answer, reply_markup=keyboard)
    await states.Escrow.fee.set()


@escrow_callback_handler(
    lambda call: call.data.startswith("accept_insurance "), state=states.Escrow.amount
)
async def accept_insurance(
    call: types.CallbackQuery, state: FSMContext, offer: EscrowOffer
):
    """Ask for fee payment agreement after accepting partial insurance."""
    await ask_fee(call.from_user.id, call.message.chat.id, offer)


@escrow_callback_handler(
    lambda call: call.data.startswith("init_cancel "), state=states.Escrow.amount
)
async def init_cancel(call: types.CallbackQuery, state: FSMContext, offer: EscrowOffer):
    """Cancel offer on initiator's request."""
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        call.message.chat.id, _("Escrow was cancelled."), reply_markup=start_keyboard()
    )
    await state.finish()


async def full_card_number_request(chat_id: int, offer: EscrowOffer):
    """Ask to send full card number."""
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(_("Sent"), callback_data=f"card_sent {offer._id}")
    )
    if offer.type == "buy":
        user = offer.counter
        currency = offer.sell
    else:
        user = offer.init
        currency = offer.buy
    mention = markdown.link(user["mention"], User(id=user["id"]).url)
    await tg.send_message(
        chat_id,
        _("Send your full {currency} card number to {user}.").format(
            currency=currency, user=mention
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    await states.Escrow.full_card.set()


async def ask_credentials(
    call: types.CallbackQuery, offer: EscrowOffer,
):
    """Update offer with ``update_dict`` and start asking transfer information.

    Ask to choose bank if user is initiator and there is a fiat
    currency. Otherwise ask receive address.
    """
    await call.answer()
    is_user_init = call.from_user.id == offer.init["id"]
    has_fiat_currency = "RUB" in {offer.buy, offer.sell}
    if has_fiat_currency:
        if is_user_init:
            keyboard = InlineKeyboardMarkup()
            for bank in SUPPORTED_BANKS:
                keyboard.row(
                    InlineKeyboardButton(bank, callback_data=f"bank {offer._id} {bank}")
                )
            await tg.send_message(
                call.message.chat.id, _("Choose bank."), reply_markup=keyboard
            )
            await states.Escrow.bank.set()
        elif offer.type == "sell":
            await full_card_number_request(call.message.chat.id, offer)
        else:
            init = offer.init
            await full_card_number_request(init["id"], offer)
            await tg.send_message(
                call.message.chat.id,
                _("I asked {} to send you their full card number.").format(
                    markdown.link(init["mention"], User(id=init["id"]).url)
                ),
            )
        return

    await tg.send_message(
        call.message.chat.id,
        _("Send your {} address.").format(offer.sell if is_user_init else offer.buy),
    )
    await offer.update_document({"$set": {"pending_input_from": call.from_user.id}})
    await states.Escrow.receive_address.set()


@escrow_callback_handler(
    lambda call: call.data.startswith("accept_fee "), state=states.Escrow.fee
)
async def pay_fee(call: types.CallbackQuery, offer: EscrowOffer):
    """Accept fee and start asking transfer information."""
    await ask_credentials(call, offer)


@escrow_callback_handler(
    lambda call: call.data.startswith("decline_fee "), state=states.Escrow.fee
)
async def decline_fee(call: types.CallbackQuery, offer: EscrowOffer):
    """Decline fee and start asking transfer information."""
    if (call.from_user.id == offer.init["id"]) == (offer.type == "buy"):
        sum_fee_field = "sum_fee_up"
    else:
        sum_fee_field = "sum_fee_down"
    await offer.update_document({"$set": {sum_fee_field: offer[f"sum_{offer.type}"]}})
    await ask_credentials(call, offer)


@escrow_callback_handler(
    lambda call: call.data.startswith("bank "), state=states.Escrow.bank
)
async def choose_bank(call: types.CallbackQuery, offer: EscrowOffer):
    """Set chosen bank and continue.

    Because bank is chosen by initiator, ask for receive address if
    they receive escrow asset.
    """
    bank = call.data.split()[2]
    if bank not in SUPPORTED_BANKS:
        await call.answer(_("This bank is not supported."))
        return

    update_dict = {"bank": bank}
    await call.answer()
    update_dict["pending_input_from"] = call.from_user.id
    await offer.update_document({"$set": update_dict})
    if offer.sell == "RUB":
        await tg.send_message(
            call.message.chat.id,
            _("Send first and last 4 digits of your {} card number.").format(
                offer.sell
            ),
        )
        await states.Escrow.receive_card_number.set()
    else:
        await tg.send_message(
            call.message.chat.id, _("Send your {} address.").format(offer.sell)
        )
        await states.Escrow.receive_address.set()


@escrow_message_handler(state=states.Escrow.full_card)
async def full_card_number_message(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """React to sent message while sending full card number to fiat sender."""
    if message.from_user.id == offer.init["id"]:
        user = offer.counter
    else:
        user = offer.init
    mention = markdown.link(user["mention"], User(id=user["id"]).url)
    await tg.send_message(
        message.chat.id,
        _("You should send it to {}, not me!").format(mention),
        parse_mode=ParseMode.MARKDOWN,
    )


@escrow_callback_handler(
    lambda call: call.data.startswith("card_sent "), state=states.Escrow.full_card
)
async def full_card_number_sent(call: types.CallbackQuery, offer: EscrowOffer):
    """Confirm that full card number is sent and ask for first and last 4 digits."""
    await offer.update_document({"$set": {"pending_input_from": call.from_user.id}})
    await call.answer()
    if call.from_user.id == offer.init["id"]:
        counter = offer.counter
        await tg.send_message(
            counter["id"], _("Send your {} address.").format(offer.buy)
        )
        await tg.send_message(
            call.message.chat.id,
            _("I continued the exchange with {}.").format(
                markdown.link(counter["mention"], User(id=counter["id"]).url)
            ),
        )
        await offer.update_document({"$set": {"pending_input_from": counter["id"]}})
        counter_state = FSMContext(dp.storage, counter["id"], counter["id"])
        await counter_state.set_state(states.Escrow.receive_address.state)
        await states.Escrow.receive_card_number.set()
    else:
        await tg.send_message(
            call.message.chat.id,
            _("Send first and last 4 digits of your {} card number.").format(
                offer.sell if offer.type == "buy" else offer.buy
            ),
        )
        await states.Escrow.receive_card_number.set()


@escrow_message_handler(state=states.Escrow.receive_card_number)
async def set_receive_card_number(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Create address from first and last 4 digits of card number and ask send address.

    First and last 4 digits of card number are sent by fiat receiver,
    so their send address is escrow asset address.
    """
    card_number = await get_card_number(message.text, message.chat.id)
    if not card_number:
        return

    if message.from_user.id == offer.init["id"]:
        user_field = "init"
    else:
        user_field = "counter"

    await offer.update_document(
        {"$set": {f"{user_field}.receive_address": ("*" * 8).join(card_number)}}
    )
    await tg.send_message(
        message.chat.id, _("Send your {} address.").format(offer[offer.type])
    )
    await states.Escrow.send_address.set()


@escrow_message_handler(state=states.Escrow.receive_address)
async def set_receive_address(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Set escrow asset receiver's address and ask for sender's information.

    If there is a fiat currency, which is indicated by existing
    ``bank`` field, and user is a fiat sender, ask their name on card.
    Otherwise ask escrow asset sender's address.
    """
    if len(message.text) >= 150:
        await tg.send_message(
            message.chat.id,
            _(
                "This value should contain less than {} characters "
                "(you sent {} characters)."
            ).format(150, len(message.text)),
        )
        return

    if message.from_user.id == offer.init["id"]:
        user_field = "init"
        send_currency = offer.buy
        ask_name = offer.bank and offer.type == "sell"
    else:
        user_field = "counter"
        send_currency = offer.sell
        ask_name = offer.bank and offer.type == "buy"

    await offer.update_document(
        {"$set": {f"{user_field}.receive_address": message.text}}
    )
    if ask_name:
        await tg.send_message(
            message.chat.id,
            _(
                "Send your name, patronymic and first letter of surname "
                "separated by spaces."
            ),
        )
        await states.Escrow.name.set()
    else:
        await tg.send_message(
            message.chat.id, _("Send your {} address.").format(send_currency)
        )
        await states.Escrow.send_address.set()


@escrow_message_handler(state=states.Escrow.send_address)
async def set_send_address(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Set send address of any party."""
    if len(message.text) >= 150:
        await tg.send_message(
            message.chat.id,
            _(
                "This value should contain less than {} characters "
                "(you sent {} characters)."
            ).format(150, len(message.text)),
        )
        return

    if message.from_user.id == offer.init["id"]:
        await set_init_send_address(message.text, message, state, offer)
    else:
        await set_counter_send_address(message.text, message, state, offer)


@escrow_message_handler(state=states.Escrow.name)
async def set_name(message: types.Message, state: FSMContext, offer: EscrowOffer):
    """Set fiat sender's name on card and ask for first and last 4 digits."""
    name = message.text.split()
    if len(name) != 3:
        await tg.send_message(
            message.chat.id,
            _("You should send {} words separated by spaces.").format(3),
        )
        return
    name[2] = name[2][0] + "."  # Leaving the first letter of surname with dot

    if offer.type == "buy":
        user_field = "counter"
        currency = offer.sell
    else:
        user_field = "init"
        currency = offer.buy

    await offer.update_document(
        {"$set": {f"{user_field}.name": " ".join(name).upper()}}
    )
    await tg.send_message(
        message.chat.id,
        _("Send first and last 4 digits of your {} card number.").format(currency),
    )
    await states.Escrow.send_card_number.set()


@escrow_message_handler(state=states.Escrow.send_card_number)
async def set_send_card_number(
    message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Set first and last 4 digits of any party."""
    card_number = await get_card_number(message.text, message.chat.id)
    if not card_number:
        return

    address = ("*" * 8).join(card_number)
    if message.from_user.id == offer.init["id"]:
        await set_init_send_address(address, message, state, offer)
    else:
        await set_counter_send_address(address, message, state, offer)


async def set_init_send_address(
    address: str, message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Set ``address`` as sender's address of initiator.

    Send offer to counteragent.
    """
    locale = offer.counter["locale"]
    buy_keyboard = InlineKeyboardMarkup()
    buy_keyboard.row(
        InlineKeyboardButton(
            _("Show order", locale=locale), callback_data=f"get_order {offer.order}"
        )
    )
    buy_keyboard.add(
        InlineKeyboardButton(
            _("Accept", locale=locale), callback_data=f"accept {offer._id}"
        ),
        InlineKeyboardButton(
            _("Decline", locale=locale), callback_data=f"decline {offer._id}"
        ),
    )
    mention = markdown.link(offer.init["mention"], User(id=offer.init["id"]).url)
    answer = _("You got an escrow offer from {} to sell {} {} for {} {}", locale=locale)
    answer = answer.format(
        mention, offer.sum_sell, offer.sell, offer.sum_buy, offer.buy
    )
    if offer.bank:
        answer += " " + _("using {}").format(offer.bank)
    answer += "."
    update_dict = {"init.send_address": address}
    if offer.type == "sell":
        insured = await get_insurance(offer)
        update_dict["insured"] = Decimal128(insured)
        if offer[f"sum_{offer.type}"] > insured:
            answer += "\n" + _(
                "Escrow asset sum exceeds maximum amount to be insured. If you "
                "continue, only {} {} will be protected and refunded in "
                "case of unexpected events during the exchange."
            )
            answer = answer.format(insured, offer[offer.type])
    await offer.update_document(
        {"$set": update_dict, "$unset": {"pending_input_from": True}}
    )
    await tg.send_message(offer.counter["id"], answer, reply_markup=buy_keyboard)
    sell_keyboard = InlineKeyboardMarkup()
    sell_keyboard.add(
        InlineKeyboardButton(_("Cancel"), callback_data=f"escrow_cancel {offer._id}")
    )
    await tg.send_message(
        message.from_user.id, _("Offer sent."), reply_markup=sell_keyboard
    )
    await state.finish()


@escrow_callback_handler(lambda call: call.data.startswith("accept "))
async def accept_offer(call: types.CallbackQuery, offer: EscrowOffer):
    """React to counteragent accepting offer by asking for fee payment agreement."""
    await offer.update_document(
        {"$set": {"pending_input_from": call.message.chat.id, "react_time": time()}}
    )
    await call.answer()
    await ask_fee(call.from_user.id, call.message.chat.id, offer)


@escrow_callback_handler(lambda call: call.data.startswith("decline "))
async def decline_offer(call: types.CallbackQuery, offer: EscrowOffer):
    """React to counteragent declining offer."""
    offer.react_time = time()
    await offer.delete_document()
    await tg.send_message(
        offer.init["id"],
        _("Your escrow offer was declined.", locale=offer.init["locale"]),
    )
    await call.answer()
    await tg.send_message(call.message.chat.id, _("Offer was declined."))


async def set_counter_send_address(
    address: str, message: types.Message, state: FSMContext, offer: EscrowOffer
):
    """Set ``address`` as sender's address of counteragent.

    Ask for escrow asset transfer.
    """
    template = (
        "to {escrow_receive_address} "
        "for {not_escrow_amount} {not_escrow_currency} "
        "from {not_escrow_send_address} to {not_escrow_receive_address} "
        "via escrow service on https://t.me/TellerBot"
    )
    if offer.type == "buy":
        memo = template.format(
            **{
                "escrow_receive_address": offer.counter["receive_address"],
                "not_escrow_amount": offer.sum_sell,
                "not_escrow_currency": offer.sell,
                "not_escrow_send_address": address,
                "not_escrow_receive_address": offer.init["receive_address"],
            }
        )
        escrow_user = offer.init
        send_reply = True
    elif offer.type == "sell":
        memo = template.format(
            **{
                "escrow_receive_address": offer.init["receive_address"],
                "not_escrow_amount": offer.sum_buy,
                "not_escrow_currency": offer.buy,
                "not_escrow_send_address": offer.init["send_address"],
                "not_escrow_receive_address": offer.counter["receive_address"],
            }
        )
        escrow_user = offer.counter
        send_reply = False

    update = {
        "counter.send_address": address,
        "transaction_time": time(),
        "memo": memo,
    }
    await offer.update_document(
        {"$set": update, "$unset": {"pending_input_from": True}}
    )
    offer = replace(offer, **update)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _("Cancel", locale=escrow_user["locale"]),
            callback_data=f"escrow_cancel {offer._id}",
        )
    )
    escrow_address = markdown.bold(get_escrow_instance(offer[offer.type]).address)
    await state.finish()
    await get_escrow_instance(offer[offer.type]).check_transaction(
        offer._id,
        escrow_user["send_address"],
        offer["sum_fee_up"].to_decimal(),
        offer[f"sum_{offer.type}"].to_decimal(),
        offer[offer.type],
        offer.memo,
    )
    answer = _("Send {} {} to address {}", locale=escrow_user["locale"]).format(
        offer.sum_fee_up, offer[offer.type], escrow_address
    )
    answer += " " + _("with memo", locale=escrow_user["locale"])
    answer += ":\n" + markdown.code(memo)
    await tg.send_message(
        escrow_user["id"], answer, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
    if send_reply:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                _("Cancel"), callback_data=f"escrow_cancel {offer._id}"
            )
        )
        await tg.send_message(
            message.chat.id,
            _("Transfer information sent.")
            + " "
            + _("I'll notify you when transaction is complete."),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )


@escrow_callback_handler(lambda call: call.data.startswith("escrow_cancel "))
async def cancel_offer(call: types.CallbackQuery, offer: EscrowOffer):
    """React to offer cancellation.

    While first party is transferring, second party can't cancel offer,
    because we can't be sure that first party hasn't already completed
    transfer before confirming.
    """
    if offer.trx_id:
        return await call.answer(_("You can't cancel offer after transfer to escrow."))
    if offer.memo:
        if offer.type == "buy":
            escrow_user = offer.init
        elif offer.type == "sell":
            escrow_user = offer.counter
        if call.from_user.id != escrow_user["id"]:
            return await call.answer(
                _("You can't cancel this offer until transaction will be verified.")
            )
        get_escrow_instance(offer[offer.type]).remove_from_queue(offer._id)

    sell_answer = _("Escrow was cancelled.", locale=offer.init["locale"])
    buy_answer = _("Escrow was cancelled.", locale=offer.counter["locale"])
    offer.cancel_time = time()
    await offer.delete_document()
    await call.answer()
    await tg.send_message(offer.init["id"], sell_answer, reply_markup=start_keyboard())
    await tg.send_message(
        offer.counter["id"], buy_answer, reply_markup=start_keyboard()
    )
    sell_state = FSMContext(dp.storage, offer.init["id"], offer.init["id"])
    buy_state = FSMContext(dp.storage, offer.counter["id"], offer.counter["id"])
    await sell_state.finish()
    await buy_state.finish()


async def edit_keyboard(
    offer_id: ObjectId, chat_id: int, message_id: int, keyboard: InlineKeyboardMarkup
):
    """Edit inline keyboard markup of message.

    :param offer_id: Primary key value of offer document connected with message.
    :param chat_id: Telegram chat ID of message.
    :param message_id: Telegram ID of message.
    :param keyboard: New inline keyboard markup.
    """
    offer_document = await database.escrow.find_one({"_id": offer_id})
    if offer_document:
        await tg.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)


@escrow_callback_handler(lambda call: call.data.startswith("tokens_sent "))
async def final_offer_confirmation(call: types.CallbackQuery, offer: EscrowOffer):
    """Ask not escrow asset receiver to confirm transfer."""
    if offer.type == "buy":
        confirm_user = offer.init
        other_user = offer.counter
        new_currency = "sell"
    elif offer.type == "sell":
        confirm_user = offer.counter
        other_user = offer.init
        new_currency = "buy"

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            _("Yes", locale=confirm_user["locale"]),
            callback_data=f"escrow_complete {offer._id}",
        )
    )
    reply = await tg.send_message(
        confirm_user["id"],
        _("Did you get {} from {}?", locale=confirm_user["locale"]).format(
            offer[new_currency], other_user["send_address"]
        ),
        reply_markup=keyboard,
    )
    keyboard.add(
        InlineKeyboardButton(
            _("No", locale=confirm_user["locale"]),
            callback_data=f"escrow_validate {offer._id}",
        )
    )
    await call_later(
        60 * 10,
        edit_keyboard,
        offer._id,
        confirm_user["id"],
        reply.message_id,
        keyboard,
    )
    await call.answer()
    await tg.send_message(
        other_user["id"],
        _(
            "When your transfer is confirmed, I'll complete escrow.",
            locale=other_user["locale"],
        ),
        reply_markup=start_keyboard(),
    )


@escrow_callback_handler(lambda call: call.data.startswith("escrow_complete "))
@dp.async_task
async def complete_offer(call: types.CallbackQuery, offer: EscrowOffer):
    """Release escrow asset and finish exchange."""
    if offer.type == "buy":
        recipient_user = offer.counter
        other_user = offer.init
    elif offer.type == "sell":
        recipient_user = offer.init
        other_user = offer.counter

    await call.answer(_("Escrow is being completed, just one moment."))
    escrow_instance = get_escrow_instance(offer[offer.type])
    trx_url = await escrow_instance.transfer(
        recipient_user["receive_address"],
        offer.sum_fee_down.to_decimal(),  # type: ignore
        offer[offer.type],
    )
    answer = _("Escrow is completed!", locale=other_user["locale"])
    recipient_answer = _("Escrow is completed!", locale=recipient_user["locale"])
    recipient_answer += " " + markdown.link(
        _("I sent you {} {}.", locale=recipient_user["locale"]).format(
            offer.sum_fee_down, offer[offer.type]
        ),
        trx_url,
    )
    await offer.delete_document()
    await tg.send_message(
        recipient_user["id"],
        recipient_answer,
        reply_markup=start_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    await tg.send_message(other_user["id"], answer, reply_markup=start_keyboard())


@escrow_callback_handler(lambda call: call.data.startswith("escrow_validate "))
async def validate_offer(call: types.CallbackQuery, offer: EscrowOffer):
    """Ask support for manual verification of exchange."""
    escrow_instance = get_escrow_instance(offer[offer.type])
    await tg.send_message(
        SUPPORT_CHAT_ID,
        "Unconfirmed escrow.\nTransaction: {}\nMemo: {}".format(
            escrow_instance.trx_url(offer.trx_id), markdown.code(offer.memo),
        ),
    )
    await offer.delete_document()
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _("We'll manually validate your request and decide on the return."),
        reply_markup=start_keyboard(),
    )
