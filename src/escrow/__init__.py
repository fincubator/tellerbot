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


from src.escrow.escrow_offer import EscrowOffer

from src.escrow.blockchain.golos_blockchain import GolosBlockchain


def get_escrow_class(asset: str):
    if asset in GolosBlockchain.assets:
        return GolosBlockchain


def get_escrow_instance(asset: str):
    escrow_class = get_escrow_class(asset)
    return escrow_class()
