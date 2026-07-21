# Образ backend.
#
# Многоступенчатая сборка не используется намеренно: зависимости ставятся
# колёсами из PyPI, компиляции нет, и второй этап сэкономил бы десятки
# мегабайт ценой заметно более сложного файла.

FROM python:3.12-slim

# Не писать .pyc и не буферизовать вывод: в контейнере логи должны появляться
# сразу, а не после заполнения буфера.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости ставятся до копирования кода: слой с ними переиспользуется,
# пока не изменится сам список, и пересборка после правки кода занимает
# секунды вместо минут.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# Непривилегированный пользователь: процесс в контейнере не должен иметь
# прав, которых ему не требуется.
RUN useradd --create-home --uid 10001 riskmap && chown -R riskmap:riskmap /app
USER riskmap

EXPOSE 8000

# Проверка живости обращается к `/health`, а не к `/ready`: готовность
# зависит от базы, и контейнер приложения не должен перезапускаться из-за
# того, что база ещё поднимается.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
