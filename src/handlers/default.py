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


from aiogram.types import Message, CallbackQuery
from aiogram.dispatcher.filters.state import any_state

from . import tg, dp, private_handler, start_keyboard
from ..i18n import _


@private_handler(state=any_state)
async def default_message(message: Message):
    await tg.send_message(
        message.chat.id, _('Unknown command.'),
        reply_markup=start_keyboard()
    )


@dp.callback_query_handler(state=any_state)
async def default_callback_query(call: CallbackQuery):
    await call.answer(_('Unknown button.'))
