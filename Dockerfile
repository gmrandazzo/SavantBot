# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (for potential C extensions in langchain/redis)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install the package and its dependencies
RUN pip install --no-cache-dir .

# Create data directory
RUN mkdir -p data

# Expose the API port
EXPOSE 8124

# The command to run will be overridden by docker-compose
CMD ["savant-api"]
