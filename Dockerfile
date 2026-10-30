FROM python:3.11.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/phase1
WORKDIR /opt/phase1

RUN apt-get update \
    && apt-get install --no-install-recommends -y make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.lock
COPY . .

CMD ["make", "test"]
