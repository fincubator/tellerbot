FROM python:3.8-slim-buster

LABEL mantainer="alfred richardsn <rchrdsn@protonmail.ch>"

ARG ESCROW_ENABLED

RUN if test "$ESCROW_ENABLED" = true; then \
    apt-get update && apt-get install --yes --no-install-recommends git; \
    else exit 0; fi

ARG USER=tellerbot
ARG GROUP=tellerbot

ENV HOME /home/$USER

RUN groupadd -g 999 $GROUP \
 && useradd -g $GROUP -u 999 -l -s /sbin/nologin -m -d $HOME $USER
WORKDIR $HOME
USER $USER:$GROUP

COPY --chown=999:999 requirements.txt requirements-escrow.txt ./
ENV PATH $PATH:$HOME/.local/bin
RUN pip install --user --no-cache-dir --requirement requirements.txt \
 && if test "$ESCROW_ENABLED" = true; then \
    pip install --user --no-cache-dir --requirement requirements-escrow.txt; \
    else exit 0; fi

COPY --chown=999:999 locale/ locale/
RUN pybabel compile --directory=locale/ --domain=bot

COPY --chown=999:999 . .

ENTRYPOINT ["python", "."]
