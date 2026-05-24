#!/bin/bash
# Setup development environment for manage_deploy

set -e

echo "=== Setting up manage_deploy development environment ==="

# Backend
echo "Setting up backend..."
cd backend

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Created virtual environment at backend/venv"
fi

source venv/bin/activate
pip install -e .
pip install pymysql aiomysql

echo "Backend dependencies installed"
deactivate

# Return to root
cd ..

echo ""
echo "=== Setup complete ==="
echo ""
echo "To activate the backend environment:"
echo "  cd backend && source venv/bin/activate"
echo ""
echo "To create the database:"
echo "  mysql -h 10.112.204.7 -u root -p'Bupt@1234' -e \"CREATE DATABASE IF NOT EXISTS task_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\""
echo ""
echo "To run the backend:"
echo "  cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000"
echo ""
echo "To run the frontend:"
echo "  cd frontend && npm install && npm run dev"