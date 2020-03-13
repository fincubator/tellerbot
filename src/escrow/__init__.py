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
from src.config import config


if config.ESCROW_ENABLED:
    from src.escrow.blockchain.golos_blockchain import GolosBlockchain

    SUPPORTED_BLOCKCHAINS = [GolosBlockchain()]
else:
    SUPPORTED_BLOCKCHAINS = []


SUPPORTED_BANKS = ("Alfa-Bank", "Rocketbank", "Sberbank", "Tinkoff")


def get_escrow_instance(asset: str):
    """Find blockchain instance which supports ``asset``."""
    for bc in SUPPORTED_BLOCKCHAINS:
        if asset in bc.assets:
            return bc


async def connect_to_blockchains():
    """Run ``connect()`` method on every blockchain instance."""
    for bc in SUPPORTED_BLOCKCHAINS:
        await bc.connect()
