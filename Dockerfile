# Use a lightweight Python image
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Install system dependencies for pycurl
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev \
    libssl-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the Flask app port
EXPOSE 5000

# Set environment variables
ENV FLASK_ENV=production

# Start the application
CMD ["python", "app.py"]