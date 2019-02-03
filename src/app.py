# Copyright (C) 2019  alfred richardsn

# This file is part of BailsBot.

# BailsBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with BailsBot.  If not, see <https://www.gnu.org/licenses/>.


import config
from .bot import bot
from .logger import logger, log_update

import flask
from telebot.types import Update


app = flask.Flask(__name__)


@app.before_request
def limit_remote_addr():
    if flask.request.remote_addr not in config.IP_RANGE:
        flask.abort(403)


@app.route('/' + config.TOKEN, methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        json_string = flask.request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        log_update(update)
        bot.process_new_updates([update])
        return ''
    else:
        flask.abort(403)


def main():
    bot.remove_webhook()
    url = 'https://{}:{}/'.format(config.SERVER_IP, config.SERVER_PORT)
    with open(config.SSL_CERT, 'r') as certificate:
        bot.set_webhook(url=url + config.TOKEN, certificate=certificate)

        logger.debug(f'Running app on {url}')
        app.run(
            host=config.SERVER_IP,
            port=config.SERVER_PORT,
            ssl_context=(config.SSL_CERT, config.SSL_PRIV),
            debug=False
        )
