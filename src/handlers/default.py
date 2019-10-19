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


import traceback
import logging

from aiogram.types import Message, CallbackQuery, ParseMode
from aiogram.dispatcher.filters.state import any_state
from aiogram.utils import markdown
from aiogram.utils.exceptions import MessageNotModified

from config import EXCEPTIONS_CHAT_ID
from src.handlers import tg, dp, private_handler, start_keyboard
from src.i18n import _


log = logging.getLogger(__name__)


@private_handler(state=any_state)
async def default_message(message: Message):
    await tg.send_message(
        message.chat.id, _('Unknown command.'),
        reply_markup=start_keyboard()
    )


@dp.callback_query_handler(state=any_state)
async def default_callback_query(call: CallbackQuery):
    await call.answer(_('Unknown button.'))


@dp.errors_handler(exception=MessageNotModified)
async def message_not_modified_handler(update, exception):
    return True


@dp.errors_handler()
async def errors_handler(update, exception):
    log.error('Error handling request {}'.format(update.update_id), exc_info=True)

    chat_id = None
    if update.message:
        update_type = 'message'
        from_user = update.message.from_user
        chat_id = update.message.chat.id
    if update.callback_query:
        update_type = 'callback query'
        from_user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat.id

    if chat_id is not None:
        await tg.send_message(
            EXCEPTIONS_CHAT_ID,
            'Error handling {} {} from {} ({}) in chat {}\n{}'.format(
                update_type,
                update.update_id,
                markdown.link(from_user.mention, from_user.url),
                from_user.id,
                chat_id,
                markdown.escape_md(traceback.format_exc(limit=-3))
            ), parse_mode=ParseMode.MARKDOWN
        )
        await tg.send_message(
            chat_id, _(
                'There was an unexpected error when handling your request. '
                "We're already notified and will fix it as soon as possible!"
            ), reply_markup=start_keyboard()
        )

    return True
