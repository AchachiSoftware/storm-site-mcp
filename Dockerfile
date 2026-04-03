FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# These directories are volume-mounted at runtime:
#   config/ → persistent endpoint registry (endpoints.json)
#   har/    → drop .har files here for import_har tool
RUN mkdir -p config har

CMD ["python", "server.py"]
