FROM python:3.11-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/srv

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.6.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
CMD ["python", "-m", "app.worker"]
