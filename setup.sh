#!/bin/bash
# KDP Automation Setup Script
# Run once to install everything: bash setup.sh

set -e

echo ""
echo "======================================"
echo "  KDP Automation System — Setup"
echo "======================================"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required."
    echo "Download it from: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python $PYTHON_VERSION detected"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip --quiet

# Install dependencies
echo "Installing Python packages..."
pip install -r requirements.txt --quiet
echo "Packages installed."

# Install Playwright browser
echo ""
echo "Installing browser for web automation (Chromium)..."
playwright install chromium
echo "Browser installed."

# Create output directory
mkdir -p output
mkdir -p output/research
mkdir -p output/products
mkdir -p output/reports

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "======================================"
    echo "  ACTION REQUIRED:"
    echo "======================================"
    echo "  Edit the .env file and add your API keys:"
    echo "  ANTHROPIC_API_KEY=sk-ant-..."
    echo "  (Optional) OPENAI_API_KEY=sk-..."
    echo ""
    echo "  Get your Anthropic key at: console.anthropic.com"
    echo "======================================"
else
    echo ".env file already exists."
fi

echo ""
echo "======================================"
echo "  Setup complete!"
echo ""
echo "  To start the app:"
echo "  source venv/bin/activate"
echo "  streamlit run app.py"
echo "======================================"
echo ""
