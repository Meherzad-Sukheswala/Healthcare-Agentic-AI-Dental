FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No secrets baked into the image. LLM_PROVIDER defaults to the offline sandbox
# model — real API keys, if you ever want live responses, are supplied at
# container-run time as environment variables by whatever host runs this image
# (Render/Railway/Fly all have an "Environment Variables" panel for exactly this),
# never written into the image or the repo.
ENV LLM_PROVIDER=sandbox \
    ENVIRONMENT=production \
    LOG_JSON=true

EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
