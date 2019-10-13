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


from abc import ABC, abstractmethod
from decimal import Decimal


class BaseBlockchain(ABC):
    assets = []
    address = None
    explorer = ''

    def trx_url(self, trx_id):
        return self.explorer.format(trx_id)

    @abstractmethod
    async def transfer(self, to: str, amount: Decimal, asset: str):
        pass

    @abstractmethod
    async def get_transaction(self, amount: Decimal, asset: str, memo: str, time_start: float):
        pass


class BlockchainConnectionError(Exception):
    pass
