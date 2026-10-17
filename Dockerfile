# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set environment variables to prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

# Set working directory
WORKDIR /app

# Install system dependencies required for WeasyPrint, ReportLab, PostgreSQL client/healthcheck, and Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libjpeg-dev \
    libopenjp2-7-dev \
    shared-mime-info \
    libgobject-2.0-0 \
    libglib2.0-0 \
    fonts-liberation \
    fonts-dejavu-core \
    fontconfig \
    postgresql-client \
    ca-certificates \
    tzdata \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install official Node.js 20 LTS for internal WhatsApp Baileys microservice
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker cache
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install WhatsApp microservice Node dependencies
WORKDIR /app/WHATSAPP/service
COPY WHATSAPP/service/package*.json ./
RUN npm install --omit=dev

# Return to main app directory
WORKDIR /app

# Copy the rest of the application code
COPY . /app/

# Ensure session directory exists
RUN mkdir -p /app/WHATSAPP/session

# Expose the API port
EXPOSE 8000

# Run the single entry point bootstrap script directly
CMD ["python", "main.py"]

