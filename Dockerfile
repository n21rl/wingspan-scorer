FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# The views import each other as `views._shared`, which needs the app root on
# sys.path. Streamlit puts it there itself, but only when it is the thing
# launching the script -- setting it here keeps the imports working whatever
# starts the process.
ENV PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The SQLite file and uploaded player pictures live on a mounted volume, so
# both survive a redeploy -- the image's own filesystem does not. The pictures
# committed to the repository still ship in the image at /app/images and are
# found from there.
ENV WINGSPAN_DB=/data/wingspan.db \
    WINGSPAN_IMAGES=/data/images

EXPOSE 8080

CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
