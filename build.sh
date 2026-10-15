#!/usr/bin/env bash
# Render Build Script for PathLab OS (FastAPI + Node.js WhatsApp Microservice)
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "=========================================================="
echo "  [1/4] Installing Python dependencies from requirements.txt"
echo "=========================================================="
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "=========================================================="
echo "  [2/4] Verifying Node.js & npm availability for WhatsApp"
echo "=========================================================="
if command -v node &> /dev/null; then
    echo "  [OK] System Node.js found: $(node -v)"
    echo "  [OK] System npm found: $(npm -v)"
else
    echo "  [WARN] System Node.js not found. Installing Node.js via nodeenv..."
    python -m nodeenv -p --node=20.12.0
    echo "  [OK] Node.js installed into Python environment: $(node -v)"
fi

echo "=========================================================="
echo "  [3/4] Installing WhatsApp Microservice dependencies"
echo "=========================================================="
cd WHATSAPP/service
npm install --omit=dev
cd ../..

echo "=========================================================="
echo "  [4/4] Setting up session directory & permissions"
echo "=========================================================="
mkdir -p WHATSAPP/session
chmod +x start.sh || true

echo "=========================================================="
echo "  [SUCCESS] All Python & Node.js dependencies installed!"
echo "=========================================================="
