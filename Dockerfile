FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir requests curl_cffi

COPY codex_register/ codex_register/
COPY gui.py .
COPY main.py .
COPY VERSION .
COPY scripts/ scripts/

ENV HOST=0.0.0.0
ENV PORT=8765

EXPOSE 8765

CMD ["python", "/app/gui.py", "--mode", "browser", "--no-auto-open", "--host", "0.0.0.0", "--port", "8765"]
