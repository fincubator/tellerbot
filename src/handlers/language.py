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


from aiogram.types import CallbackQuery
from aiogram.dispatcher.filters.state import any_state

from src.handlers import tg, dp, help_message, start_keyboard
from src.database import database
from src.i18n import i18n


@dp.callback_query_handler(lambda call: call.data.startswith('locale '), state=any_state)
async def locale_button(call: CallbackQuery):
    locale = call.data.split()[1]
    await database.users.update_one(
        {'id': call.from_user.id},
        {'$set': {'locale': locale}}
    )

    i18n.ctx_locale.set(locale)
    await call.answer()
    await tg.send_message(
        call.message.chat.id, help_message(),
        reply_markup=start_keyboard()
    )
