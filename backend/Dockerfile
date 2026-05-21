FROM python:3.11-slim

WORKDIR /app

# Install system libraries needed by lxml and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libjpeg62-turbo \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure uploads directory exists at startup
RUN mkdir -p uploads

EXPOSE 5002

CMD ["python", "main.py"]
