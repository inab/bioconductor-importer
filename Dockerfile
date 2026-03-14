FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    r-base \
    r-base-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN git --version && python --version && R --version

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py", "-l=DEBUG"]