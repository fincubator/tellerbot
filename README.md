![](https://i.imgur.com/cPUUcTw.jpg)

# TellerBot
[![Documentation Status](https://readthedocs.org/projects/tellerbot/badge/?version=latest)](https://tellerbot.readthedocs.io/en/latest/?badge=latest)
[![Updates](https://pyup.io/repos/github/fincubator/tellerbot/shield.svg)](https://pyup.io/repos/github/fincubator/tellerbot)
[![GitHub license](https://img.shields.io/github/license/fincubator/tellerbot)](https://github.com/PreICO/tellerbot/blob/escrow/COPYING)
[![Telegram](https://img.shields.io/badge/Telegram-tellerchat-blue?logo=telegram)](https://t.me/tellerchat)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[@TellerBot](https://t.me/TellerBot) is an asynchronous Telegram Bot written in Python to help you meet people that you can swap money with.


## Requirements
* [Python](https://www.python.org/downloads) >= 3.8
* [MongoDB](https://docs.mongodb.com/manual/installation/)
* [Motor](https://github.com/mongodb/motor) - asynchronous Python driver for MongoDB
* [AIOgram](https://github.com/aiogram/aiogram) - asynchronous Python library for Telegram Bot API
* [Emoji](https://github.com/carpedm20/emoji) - emoji for Python


## Installation and launch
### Using Docker (recommended)
1. Clone the repository:
```bash
git clone https://github.com/fincubator/tellerbot
cd tellerbot
```
2. Create environment file from example:
```bash
cp .env.example .env
```
3. Personalize settings by modifying ```.env``` with your preferable text editor.
4. Create a new Telegram bot by talking to [@BotFather](https://t.me/BotFather) and get its API token.
5. Create a file containing Telegram bot's API token with filename specified in ```TOKEN_FILENAME``` from ```.env```.
6. Install [Docker Compose](https://docs.docker.com/compose/install/).
7. Start container:
```bash
docker-compose up
```

### Manual
1. Clone the repository:
```bash
git clone https://github.com/fincubator/tellerbot
cd tellerbot
```
2. Install Python version no less than 3.8.
3. Install requirements:
```bash
pip install -r requirements.txt
```
4. Create environment file from example:
```bash
cp .env.example .env
```
5. Personalize settings by modifying ```.env``` with your preferable text editor. Remove ```INTERNAL_HOST``` and ```DATABASE_HOST``` if you want bot and database running on localhost.
6. Create a new Telegram bot by talking to [@BotFather](https://t.me/BotFather) and get its API token.
7. Create a file containing Telegram bot's API token with filename specified in ```TOKEN_FILENAME``` from ```.env```.
8. Install and start MongoDB server.
9. Set environment variables:
```bash
export $(grep -v '^#' .env | xargs)
```
10. Launch TellerBot:
```bash
python .
```

## Contributing
You can help by working on [opened issues](https://github.com/fincubator/tellerbot/issues), fixing bugs, creating new features, improving documentation or translating bot messages to your language.

Before contributing, please read [CONTRIBUTING.md](https://github.com/fincubator/tellerbot/blob/master/CONTRIBUTING.md) first.


## License
TellerBot is released under the GNU Affero General Public License v3.0. See [COPYING](https://github.com/fincubator/tellerbot/blob/master/COPYING) for the full licensing conditions.
