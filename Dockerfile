# Multi-stage Dockerfile optimized for Docker Bake
# Eliminates redundant pip installs and improves layer caching

# Base stage with system dependencies and Python packages
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies (shared by all stages)
RUN pip install --no-cache-dir -r requirements.txt

# Development stage with additional tools
FROM base AS development

# Install development dependencies
ARG INSTALL_DEV_DEPS=false
RUN if [ "$INSTALL_DEV_DEPS" = "true" ] ; then \
    pip install --no-cache-dir pytest pytest-asyncio pytest-cov flake8 black isort ; \
    fi

# Cache busting argument for forcing rebuilds when files change
ARG CACHEBUST=1

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs pids database/migrations

# Production stage (default) - inherits Python packages from base
FROM base AS fingerprint-logger

# Build arguments for optimization
ARG BUILD_TYPE=production
ARG PYTHON_OPTIMIZE=1

# Cache busting argument for forcing rebuilds when files change
ARG CACHEBUST=1

# Copy application code
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p logs pids database/migrations \
    && chmod -R 755 logs pids database

# Set optimized environment variables
ENV DATABASE_URL=sqlite:///./database/attendance.db
ENV PYTHON_OPTIMIZE=${PYTHON_OPTIMIZE}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/fingerprintlogs/api/devices/health || exit 1

# Expose port
EXPOSE 5000

# Run database migrations and start server
CMD ["sh", "-c", "alembic -c database/alembic.ini upgrade head && uvicorn app.main_unified:app --host 0.0.0.0 --port 5000"]