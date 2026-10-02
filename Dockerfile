# Reproducible run of a book. Paper (dry run) by default; real orders need ROOSTOO_DRY_RUN=0 and keys.
#   docker build -t roostoo-bot .
#   docker run --rm --env-file .env roostoo-bot                                   # competition rule, paper
#   docker run --rm --env-file .env -e ROOSTOO_DRY_RUN=0 roostoo-bot config/competition.yaml
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 ROOSTOO_DRY_RUN=1 TZ=UTC
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY signals ./signals
COPY venue ./venue
COPY data ./data
COPY core ./core
COPY costs ./costs
COPY portfolio ./portfolio
COPY gates ./gates
COPY config ./config
RUN mkdir -p live run
ENTRYPOINT ["python", "-m", "bot.contenders_run"]
CMD ["config/momentum_top3_30m.yaml"]
