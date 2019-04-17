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


from aiogram.dispatcher.filters.state import State, StatesGroup


class OrderCreation(StatesGroup):
    buy = State()
    sell = State()
    price = State()
    sum = State()
    payment_type = State()
    payment_system = State()
    location = State()
    duration = State()
    comments = State()
    set_order = State()


payment_system_cashless = State(group_name='OrderCreation')
