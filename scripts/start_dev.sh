#!/usr/bin/env bash

set -e

PROJECT_ROOT="/workspace"

cd "$PROJECT_ROOT"

echo "================================="
echo " Start Recommendation Dev Env"
echo "================================="


#################################
# Python environment
#################################

echo "[1/5] Checking Python"

if ! command -v python3 >/dev/null 2>&1
then
    echo "Installing Python..."

    apt-get update

    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 \
        python3-pip \
        python3-venv
fi


echo "Python:"
python3 --version


#################################
# Backend venv
#################################

echo "[2/5] Checking backend environment"


if [ ! -d ".venv" ]
then
    echo "Creating virtual environment..."

    python3 -m venv .venv
fi


source .venv/bin/activate


echo "Installing backend dependencies..."

python -m pip install --upgrade pip

python -m pip install -r requirements.txt


#################################
# Frontend
#################################

echo "[3/5] Checking frontend"


cd "$PROJECT_ROOT/frontend"


if [ ! -d "node_modules" ]
then
    echo "Installing frontend dependencies..."

    npm ci
fi


echo "Building frontend..."

npm run build


#################################
# Backend start
#################################

echo "[4/5] Starting backend"

cd "$PROJECT_ROOT"

source .venv/bin/activate


nohup python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    > backend.log 2>&1 &


echo "Backend started:"
echo "http://localhost:8000"


#################################
# Frontend dev server
#################################

echo "[5/5] Starting frontend dev server"


cd "$PROJECT_ROOT/frontend"


nohup npm run dev -- \
    --host 0.0.0.0 \
    > "$PROJECT_ROOT/frontend/dev.log" 2>&1 &


echo ""
echo "================================="
echo " Environment Ready"
echo "================================="
echo ""
echo "Backend:"
echo "  http://localhost:8000"
echo ""
echo "Frontend:"
echo "  http://localhost:8890"
echo ""
echo "Logs:"
echo "  backend.log"
echo "  frontend/dev.log"
echo ""
