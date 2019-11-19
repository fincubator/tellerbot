FROM python:3.8-slim-buster

LABEL mantainer="alfred richardsn <rchrdsn@protonmail.ch>"

ARG USER=tellerbot
ARG GROUP=tellerbot

ENV HOME /home/$USER

RUN groupadd -g 999 $GROUP \
 && useradd -g $GROUP -u 999 -l -s /sbin/nologin -m -d $HOME $USER
WORKDIR $HOME
USER $USER:$GROUP

COPY --chown=$USER:$GROUP requirements.txt .
ENV PATH $PATH:$HOME/.local/bin
RUN pip install --user --no-cache-dir --requirement requirements.txt

COPY --chown=$USER:$GROUP locale/ locale/
RUN pybabel compile --directory=locale/ --domain=bot

COPY --chown=$USER:$GROUP . .

ENTRYPOINT ["python", "."]
