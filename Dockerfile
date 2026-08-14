FROM python:3.13-slim

# Set working directory inside the container
WORKDIR /app

# Install system dependencies (build-essential may be required for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker build cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Install local aviationstack-mcp package
RUN pip install --no-cache-dir ./aviationstack-mcp

# Expose the Streamlit default port
EXPOSE 8501

# Run the Streamlit application
CMD ["streamlit", "run", "frontend.py", "--server.address=0.0.0.0", "--server.port=8501"]
