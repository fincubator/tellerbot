# Copyright (C) 2019  alfred richardsn
#
# This file is part of BailsBot.
#
# BailsBot is free software: you can redistribute it and/or modify
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
# along with BailsBot.  If not, see <https://www.gnu.org/licenses/>.


import config
from .database import database
from .locale import translations

import telebot


bot = telebot.TeleBot(config.TOKEN)


def translate_handler(handler):
    def decorator(message):
        user = database.users.find_one({'id': message.chat.id})
        domain = user['language'] if user else 'us'
        _ = lambda text: text if domain == 'us' else translations[domain].get(text, text)
        return handler(message, user, _)
    return decorator


def private_only(message):
    return message.chat.type == 'private'


def message_handler(func=None, **kwargs):
    def decorator(handler):
        conjuction = private_only if func is None else lambda message: private_only and func()
        handler_dict = bot._build_handler_dict(handler, func=conjuction, **kwargs)
        bot.add_message_handler(handler_dict)
        return translate_handler(handler)
    return decorator


@message_handler(func=private_only, commands=['start', 'help'])
def handle_start_command(message, user, _):
    language_code = message.from_user.language_code
    if language_code is None:
        language_code = 'us'
    new_user = {
        'language': language_code
    }
    database.users.update_one(
        {'id': message.from_user.id},
        {'$setOnInsert': new_user},
        upsert=True
    )


@message_handler()
def handle_default(message, user, _):
    bot.send_message(message.chat.id, _('Unknown command.'))
