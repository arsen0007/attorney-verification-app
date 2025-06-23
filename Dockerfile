# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for Chrome and its driver
# These are essential for Selenium to run in a Linux environment
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    # Clean up the cache to keep the image size small
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get -y update \
    && apt-get install -y google-chrome-stable

# Copy the requirements file into the container first
# This helps with Docker layer caching, making subsequent builds faster
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
# This includes app.py and the 'templates' folder if it existed
COPY . .

# Tell Docker that the container will listen on this port (Render provides this)
EXPOSE 10000

# Define the command to run your Streamlit app
# This command tells Streamlit to run on all network interfaces and on the port Render expects
CMD ["streamlit", "run", "app.py", "--server.port=10000", "--server.address=0.0.0.0"]
