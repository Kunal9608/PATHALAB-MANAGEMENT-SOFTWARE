#!/bin/bash
set -e

# Start internal WhatsApp Node.js microservice if enabled
if [ "$WHATSAPP_ENABLED" != "false" ]; then
    echo "[Entrypoint] Starting WhatsApp Node.js microservice on port 3001..."
    node WHATSAPP/service/src/server.js &
fi

# Start main FastAPI application
echo "[Entrypoint] Starting PathLab main application..."
exec python main.py
