FROM python:3.10

LABEL maintainer="Stéphane Bidoul"

RUN pip install --no-cache-dir --upgrade "pip>=21.3.1"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app
ENV PYTHONPATH=/app

COPY log-config.yaml /etc/runboat-log-config.yaml

ENV RUNBOAT_SUPPORTED_REPOS='["oca/server-env", "oca/mis-builder"]'
ENV RUNBOAT_API_ADMIN_USER="admin"
ENV RUNBOAT_API_ADMIN_PASSWD=
ENV RUNBOAT_BUILD_NAMESPACE=runboat-builds
ENV RUNBOAT_BUILD_PGHOST=postgres14.runboat-builds-db
ENV RUNBOAT_BUILD_PGPORT=5432
ENV RUNBOAT_BUILD_PGUSER=runboat-build
ENV RUNBOAT_BUILD_PGPASSWORD=
ENV RUNBOAT_BUILD_ADMIN_PASSWD=
ENV RUNBOAT_BUILD_DOMAIN=runboat.example.com
ENV RUNBOAT_GITHUB_TOKEN=
ENV RUNBOAT_LOG_CONFIG=/etc/runboat-log-config.yaml

ENV KUBECONFIG=/run/kubeconfig

EXPOSE 8000

CMD [ "gunicorn", "-w", "1", "-k", "runboat.uvicorn.RunboatUvicornWorker", "runboat.app:app"]
