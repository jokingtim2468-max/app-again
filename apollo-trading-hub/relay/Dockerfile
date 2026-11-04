# Apollo Bot Relay - build from the repo's apollo-trading-hub folder:
#   docker build -t apollo-relay -f relay/Dockerfile .
#   docker run -d --restart unless-stopped -p 8787:8787 -v apollo-relay:/data \
#     -e RELAY_TELEGRAM_TOKEN=... -e RELAY_DISCORD_TOKEN=... -e RELAY_ACCESS_KEY=choose-a-key apollo-relay
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "httpx>=0.27" "websockets>=12.0"
COPY backend/__init__.py backend/__init__.py
COPY backend/src/__init__.py backend/src/__init__.py
COPY backend/src/bots backend/src/bots
COPY relay relay
ENV RELAY_STATE=/data/relay_state.json PORT=8787
VOLUME /data
EXPOSE 8787
CMD ["python", "relay/apollo_relay.py"]
