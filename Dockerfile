# Portable image for the Resume <-> JD Tailor service.
# Works on Hugging Face Spaces (Docker SDK, port 7860) and Google Cloud Run
# (which injects $PORT). Run locally with:  docker run -p 7860:7860 --env-file .env <image>
FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching. pypdf is pure-Python, so no
# system packages are needed beyond the slim base.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run overrides PORT at runtime; Hugging Face Spaces uses 7860.
ENV PORT=7860
EXPOSE 7860

# GOOGLE_API_KEY / GOOGLE_GENAI_USE_VERTEXAI are provided at runtime as secrets
# (Space secrets, Cloud Run env vars, or --env-file locally) — never baked in.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
