<div align="center">
<h1>TellerBot</h1>
<img src="https://i.imgur.com/cPUUcTw.jpg">

[![Documentation Status](https://readthedocs.org/projects/tellerbot/badge/?version=latest)](https://tellerbot.readthedocs.io/en/latest/?badge=latest)
[![pre-commit](https://github.com/fincubator/tellerbot/workflows/pre-commit/badge.svg)](https://github.com/fincubator/tellerbot/actions?query=workflow%3Apre-commit)
[![Translation Status](https://hosted.weblate.org/widgets/tellerbot/-/tellerbot/svg-badge.svg)](https://hosted.weblate.org/engage/tellerbot/?utm_source=widget)
[![GitHub license](https://img.shields.io/github/license/fincubator/tellerbot)](https://github.com/PreICO/tellerbot/blob/escrow/COPYING)
[![Telegram](https://img.shields.io/badge/Telegram-tellerchat-blue?logo=telegram)](https://t.me/tellerchat)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
</div>

---


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
5. Create a file containing Telegram bot's API token with filename specified in ```TOKEN_FILENAME``` from ```.env``` (example in [secrets/tbtoken](secrets/tbtoken)).
6. *(Optional)* If you're going to support escrow, set ```ESCROW_ENABLED=true``` in ```.env``` and create a file containing JSON mapping blockchain names to bot's WIF and API nodes with filename specified in ```ESCROW_FILENAME``` from ```.env``` (example in [secrets/escrow.json](secrets/escrow.json)).
7. Create a file containing database password with filename specified in ```DATABASE_PASSWORD_FILENAME``` from ```.env``` (example in [secrets/dbpassword](secrets/dbpassword)).
8. Install [Docker Compose](https://docs.docker.com/compose/install/) version no less than 1.26.0.
9. Start container:
```bash
docker-compose up --build
```

For subsequent launches starting container is enough.

### Manual
1. Clone the repository:
```bash
git clone https://github.com/fincubator/tellerbot
cd tellerbot
```
2. Install Python version no less than 3.8 with [pip](https://pip.pypa.io/en/stable/installing/).
3. Install requirements:
```bash
pip install -r requirements.txt
pip install -r requirements-escrow.txt  # If you're going to support escrow
```
4. Compile translations:
```bash
pybabel compile -d locale/ -D bot
```
5. Create environment file from example:
```bash
cp .env.example .env
```
6. Personalize settings by modifying ```.env``` with your preferable text editor. Remove ```INTERNAL_HOST``` and ```DATABASE_HOST``` if you want bot and database running on localhost.
7. Create a new Telegram bot by talking to [@BotFather](https://t.me/BotFather) and get its API token.
8. Create a file containing Telegram bot's API token with filename specified in ```TOKEN_FILENAME``` from ```.env``` (example in [secrets/tbtoken](secrets/tbtoken)).
9. *(Optional)* If you're going to support escrow, set ```ESCROW_ENABLED=true``` in ```.env``` and create a file containing JSON mapping blockchain names to bot's WIF and API nodes with filename specified in ```ESCROW_FILENAME``` from ```.env``` (example in [secrets/escrow.json](secrets/escrow.json)).
10. Create a file containing database password with filename specified in ```DATABASE_PASSWORD_FILENAME``` from ```.env``` (example in [secrets/dbpassword](secrets/dbpassword)).
11. Install and start [MongoDB server](https://docs.mongodb.com/manual/installation/).
12. Set environment variables:
```bash
export $(sed 's/#.*//' .env | xargs)
```
13. Create database user:
```bash
./mongo-init.sh
```
14. Restart MongoDB server with [access control enabled](https://docs.mongodb.com/manual/tutorial/enable-authentication/#re-start-the-mongodb-instance-with-access-control).
15. Launch TellerBot:
```bash
python .
```

For subsequent launches setting enviroment variables and launching TellerBot is enough.

## Contributing
You can help by working on [opened issues](https://github.com/fincubator/tellerbot/issues), fixing bugs, creating new features, improving documentation or [translating bot messages to your language](https://hosted.weblate.org/engage/tellerbot/).

Before contributing, please read [CONTRIBUTING.md](CONTRIBUTING.md) first.


## License
TellerBot is released under the GNU Affero General Public License v3.0. See [COPYING](COPYING) for the full licensing conditions.
