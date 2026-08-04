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
# CLINIC_TIMEZONE is set here rather than left to the container's clock: this image runs
# in UTC on every host that matters, and appointment slots must be generated in the
# PRACTICE's timezone. Without it the scheduler offered 9:30am UTC, which a patient in US
# Eastern read as 5:30am. Change it to the practice's real timezone (IANA name, so
# daylight saving is handled), or override it per-deploy in the host's env panel.
ENV LLM_PROVIDER=sandbox \
    ENVIRONMENT=production \
    LOG_JSON=true \
    CLINIC_TIMEZONE=America/Los_Angeles

EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
