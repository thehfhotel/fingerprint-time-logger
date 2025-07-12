# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs pids database/migrations

# Set environment variables
ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite:///./database/attendance.db

# Expose port
EXPOSE 5000

# Run database migrations and start server
CMD ["sh", "-c", "alembic -c database/alembic.ini upgrade head && uvicorn app.main_unified:app --host 0.0.0.0 --port 5000"]