#!/bin/bash
echo "=== Запуск АКМ — Аналитическая Карта Алматинской Области ==="

# Backend
cd /Users/nuraiaitbazar/Desktop/mapping/backend
source venv/bin/activate
python manage.py runserver 8000 &
DJANGO_PID=$!

# Frontend
cd /Users/nuraiaitbazar/Desktop/mapping/frontend
npm start &
REACT_PID=$!

echo ""
echo "Система запущена:"
echo "   Frontend:  http://localhost:3000"
echo "   Backend:   http://localhost:8000/api/v1/"
echo "   Admin:     http://localhost:8000/admin  (admin / admin123)"
echo ""
echo "Ctrl+C — остановить оба сервера"
trap "kill $DJANGO_PID $REACT_PID 2>/dev/null" EXIT
wait
