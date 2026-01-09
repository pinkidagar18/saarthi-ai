FROM python:3.10

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install -r requirements.txt

# Hugging Face uses port 7860
EXPOSE 7860

# Run Flask app
CMD ["python", "app.py"]
