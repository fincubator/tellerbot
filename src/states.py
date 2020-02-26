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
from aiogram.dispatcher.filters.state import State
from aiogram.dispatcher.filters.state import StatesGroup


class OrderCreation(StatesGroup):
    """Steps of order creation.

    States represent values user is required to send. They are in order
    and skippable unless otherwise specified.
    """

    #: Currency user wants to buy (unskippable).
    buy = State()
    #: Gateway of buy currency (unskippable).
    buy_gateway = State()
    #: Currency user wants to sell (unskippable).
    sell = State()
    #: Gateway of sell currency (unskippable).
    sell_gateway = State()
    #: Price in one of the currencies.
    price = State()
    #: Sum in any of the currencies.
    amount = State()
    #: Cashless payment system.
    payment_system = State()
    #: Location object or location name.
    location = State()
    #: Duration in days.
    duration = State()
    #: Any additional comments.
    comments = State()
    #: Finish order creation by skipping comments state.
    set_order = State()


class Escrow(StatesGroup):
    """States of user during escrow exchange.

    States are uncontrollable by users and are only used to determine
    what action user is required to perform. Because there are two
    parties in escrow exchange and steps are dependant on which
    currencies are used, states do not define full steps of exchange.
    """

    #: Send sum in any of the currencies.
    amount = State()
    #: Agree or disagree to pay fee.
    fee = State()
    #: Choose escrow initiator's bank from listed.
    bank = State()
    #: Send fiat sender's name on card.
    #: Required to verify fiat transfer.
    name = State()
    #: Send fiat receiver's full card number to fiat sender.
    full_card = State()
    #: Send escrow asset receiver's address in blockchain.
    receive_address = State()
    #: Send first and last 4 digits of fiat receiver's card number.
    receive_card_number = State()
    #: Escrow asset sender's address in blockchain.
    send_address = State()
    #: Send first and last 4 digits of fiat sender's card number.
    send_card_number = State()


#: Ask support a question.
asking_support = State("asking_support")
#: Send new value of chosen order's field during editing.
field_editing = State("field_editing")
