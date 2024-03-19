FROM python:3.12

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the requirements file into the container at /usr/src/app
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the operator code into the container
COPY kaspr/ ./kaspr/

# Set PYTHONPATH to include the app directory
ENV PYTHONPATH "${PYTHONPATH}:/usr/src/app"

CMD kopf run /usr/src/app/kaspr/app.py --verbose --all-namespaces
