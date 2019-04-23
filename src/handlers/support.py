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


from aiogram.utils.emoji import emojize

import config
from . import tg, dp, private_handler, start_keyboard
from ..i18n import _
from ..states import asking_support


@dp.callback_query_handler(lambda call: call.data.startswith('unhelp'), state=asking_support)
async def unhelp_button(call, state):
    await state.finish()
    await call.answer()
    await tg.send_message(
        call.message.chat.id,
        _('Your request is cancelled.'),
        reply_markup=start_keyboard()
    )


async def send_message_to_support(message):
    await tg.send_message(
        config.SUPPORT_CHAT_ID,
        emojize(f':envelope: #chat_{message.chat.id} {message.message_id}\n') + message.text
    )
    await tg.send_message(
        message.chat.id,
        _('Your message was forwarded to the support. '
          "When you get a reply, I'll send it to you."),
        reply_markup=start_keyboard()
    )


@private_handler(state=asking_support)
async def contact_support(message, state):
    await send_message_to_support(message)
    await state.finish()


@private_handler(
    lambda msg:
    msg.reply_to_message is not None and
    msg.reply_to_message.text.startswith(emojize(':speech_balloon:'))
)
async def handle_reply(message):
    me = await tg.me
    if message.reply_to_message.from_user.id == me.id:
        await send_message_to_support(message)


@dp.message_handler(
    lambda msg:
    msg.chat.id == config.SUPPORT_CHAT_ID and
    msg.reply_to_message is not None and
    msg.reply_to_message.text.startswith(emojize(':envelope: '))
)
async def answer_support_ticket(message):
    me = await tg.me
    if message.reply_to_message.from_user.id == me.id:
        args = message.reply_to_message.text.splitlines()[0].split()
        chat_id = int(args[1].split('_')[1])
        reply_to_message_id = int(args[2])

        await tg.send_message(
            chat_id, emojize(':speech_balloon:') + message.text,
            reply_to_message_id=reply_to_message_id
        )
        await tg.send_message(message.chat.id, _('Reply is sent.'))
