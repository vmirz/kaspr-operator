FROM python:3.12

RUN mkdir -p /app
WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

CMD kopf run kaspr --verbose