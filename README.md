![](https://i.imgur.com/cPUUcTw.jpg)

# TellerBot
[![Documentation Status](https://readthedocs.org/projects/tellerbot/badge/?version=latest)](https://tellerbot.readthedocs.io/en/latest/?badge=latest)
[![GitHub license](https://img.shields.io/github/license/preico/tellerbot)](https://github.com/PreICO/tellerbot/blob/escrow/COPYING)
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
1. Create a new Telegram bot by talking to [@BotFather](https://t.me/BotFather) and get its API Token.
2. Install and start MongoDB server
3. Install Python version no less than 3.8
4. Clone the repository:
```bash
git clone https://github.com/PreICO/tellerbot
cd tellerbot
```
5. Install requirements:
```bash
pip install -r requirements.txt
```
6. Create config file from template:
```bash
cp config.py.sample src/config.py
```
7. Personalize settings by modifying ```config.py``` with your preferable text editor.
8. Launch TellerBot:
```bash
cd ..
python tellerbot
```

## Contributing
You can help by working on [opened issues](https://github.com/preico/tellerbot/issues), fixing bugs, creating new features, improving documentation or translating bot messages to your language.

Before contributing, please read [CONTRIBUTING.md](https://github.com/PreICO/tellerbot/blob/master/CONTRIBUTING.md) first.


## License
TellerBot is released under the GNU Affero General Public License v3.0. See [COPYING](https://github.com/PreICO/tellerbot/blob/master/COPYING) for the full licensing conditions.
