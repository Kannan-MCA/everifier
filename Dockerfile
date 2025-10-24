# Use Python 3.12.10 slim base image
FROM python:3.12.10-slim

# Set working directory inside container
WORKDIR /app

# Install system dependencies for DNS and SSL
RUN apt-get update && \
    apt-get install -y gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port 8000 (default FastAPI port)
ENV PORT=8000
EXPOSE ${PORT}

# Start the FastAPI app with uvicorn using app.main:app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
