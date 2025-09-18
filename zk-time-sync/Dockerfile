# ZK Time Sync Service - Minimal Docker Container
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set Bangkok timezone
ENV TZ=Asia/Bangkok

# Install system timezone data
RUN apt-get update && \
    apt-get install -y tzdata && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY sync_service.py .
COPY config/ ./config/

# Create logs directory
RUN mkdir -p logs

# Make service executable
RUN chmod +x sync_service.py

# Health check - verify service can start and connect
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "from sync_service import ZKTimeSyncService; print(ZKTimeSyncService().health_check())" || exit 1

# Run the sync service
CMD ["python", "sync_service.py"]