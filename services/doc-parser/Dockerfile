FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# functions-framework speaks CloudEvents over HTTP -- this is the standard
# way to run an Eventarc-triggered handler on Cloud Run (2nd gen).
CMD ["functions-framework", "--target=main", "--signature-type=cloudevent", "--port=8080"]
