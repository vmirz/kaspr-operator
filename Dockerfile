FROM python:3.12

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the requirements file into the container at /usr/src/app
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the operator code into the container
COPY kaspr/ ./kaspr/
COPY run_operator.py ./

# Set PYTHONPATH to include the app directory
ENV PYTHONPATH "${PYTHONPATH}:/usr/src/app"

# Default arguments for the operator (can be overridden)
CMD ["python3", "/usr/src/app/run_operator.py", "--verbose", "--all-namespaces"]
