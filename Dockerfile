FROM python:3.11

WORKDIR /opt/app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY . .
RUN pip install --no-cache-dir .

ENV PORT=8000
EXPOSE 8000

CMD uvicorn fhir_backend_auth.app:create_app --factory --host 0.0.0.0 --port ${PORT}
