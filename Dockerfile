# syntax=docker/dockerfile:1
FROM python:3.10-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Create app directory
WORKDIR /app

# Copy project files
COPY . /app/

# Create virtual environment and install Python dependencies using uv
RUN uv venv && uv pip install .

# Final stage - copy only what's needed
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv in final stage
RUN pip install uv

# Create app directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . /app/

# Create a non-root user
RUN useradd -m trinetrauser

# Set proper ownership of the app directory
RUN chown -R trinetrauser:trinetrauser /app

# Switch to non-root user
USER trinetrauser

# Expose port
EXPOSE 8969

# Entrypoint: use run.sh with config file for consistent log level and configuration
ENTRYPOINT ["/bin/bash", "run.sh", "/app/.venv/bin/python", "/app/config.yaml"] 
