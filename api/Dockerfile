FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system -e .

# Copy source code
COPY src/ ./src/
COPY start.py .
COPY scripts/ ./scripts/

# Run both servers (UI on 8000, API on 8001)
CMD ["python", "start.py"]
