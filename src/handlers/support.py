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
"""Handlers for interacting with support."""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.utils import markdown
from aiogram.utils.emoji import emojize

from src import config
from src.bot import dp
from src.handlers.base import private_handler
from src.handlers.base import start_keyboard
from src.handlers.base import tg
from src.i18n import _
from src.states import asking_support


@dp.callback_query_handler(
    lambda call: call.data.startswith("unhelp"), state=asking_support
)
async def unhelp_button(call: types.CallbackQuery, state: FSMContext):
    """Cancel request to support."""
    await state.finish()
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _("Your request is cancelled."),
        reply_markup=start_keyboard(),
    )


async def send_message_to_support(message: types.Message):
    """Format message and send it to support.

    Envelope emoji at the beginning is the mark of support ticket.
    """
    if message.from_user.username:
        username = "@" + message.from_user.username
    else:
        username = markdown.link(message.from_user.full_name, message.from_user.url)

    await tg.send_message(
        config.SUPPORT_CHAT_ID,
        emojize(f":envelope:")
        + f" #chat_{message.chat.id} {message.message_id}\n{username}:\n"
        + message.text,
    )
    await tg.send_message(
        message.chat.id,
        _("Your message was forwarded. We'll respond to you within 24 hours."),
        reply_markup=start_keyboard(),
    )


@private_handler(state=asking_support)
async def contact_support(message: types.Message, state: FSMContext):
    """Send message to support after request in start manu."""
    await send_message_to_support(message)
    await state.finish()


@private_handler(
    lambda msg: msg.reply_to_message is not None
    and msg.reply_to_message.text.startswith(emojize(":speech_balloon:"))
)
async def handle_reply(message: types.Message):
    """Answer support's reply to ticket."""
    me = await tg.me
    if message.reply_to_message.from_user.id == me.id:
        await send_message_to_support(message)


@dp.message_handler(
    lambda msg: msg.chat.id == config.SUPPORT_CHAT_ID
    and msg.reply_to_message is not None
    and msg.reply_to_message.text.startswith(emojize(":envelope: "))
)
async def answer_support_ticket(message: types.Message):
    """Answer support ticket.

    Speech balloon emoji at the beginning is the mark of support's
    reply to ticket.
    """
    me = await tg.me
    if message.reply_to_message.from_user.id == me.id:
        args = message.reply_to_message.text.splitlines()[0].split()
        chat_id = int(args[1].split("_")[1])
        reply_to_message_id = int(args[2])

        await tg.send_message(
            chat_id,
            emojize(":speech_balloon:") + message.text,
            reply_to_message_id=reply_to_message_id,
        )
        await tg.send_message(message.chat.id, _("Reply is sent."))


@dp.message_handler(
    lambda msg: msg.chat.id == config.SUPPORT_CHAT_ID, commands=["toggle_escrow"]
)
async def toggle_escrow(message: types.Message):
    """Toggle escrow availability.

    This command makes creation of new escrow offers unavailable if
    escrow is enabled, and makes it available if it's disabled.
    """
    config.ESCROW_ENABLED = not config.ESCROW_ENABLED
    if config.ESCROW_ENABLED:
        await tg.send_message(message.chat.id, _("Escrow was enabled."))
    else:
        await tg.send_message(message.chat.id, _("Escrow was disabled."))
