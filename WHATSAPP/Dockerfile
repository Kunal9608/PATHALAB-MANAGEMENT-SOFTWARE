FROM node:20-slim

WORKDIR /app

# Install curl for healthchecks and certificates
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy package definition first for better Docker layer caching
COPY WHATSAPP/service/package*.json ./WHATSAPP/service/

# Install dependencies inside WHATSAPP/service
WORKDIR /app/WHATSAPP/service
RUN npm install --omit=dev

# Copy application source code
WORKDIR /app
COPY WHATSAPP/service ./WHATSAPP/service

# Ensure session directory exists
RUN mkdir -p /app/WHATSAPP/session

EXPOSE 3001

# Run the WhatsApp microservice
CMD ["node", "WHATSAPP/service/src/server.js"]
