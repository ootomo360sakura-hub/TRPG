FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/recruit.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py render.py store.py ui.py ./

CMD ["python", "bot.py"]
