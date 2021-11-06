FROM python:3.10

LABEL maintainer="Stéphane Bidoul"

RUN pip install --no-cache-dir --upgrade "pip>=21.3.1"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app
ENV PYTHONPATH=/app

COPY log-config.yaml /etc/runboat-log-config.yaml

ENV RUNBOAT_SUPPORTED_REPOS='["OCA/mis-builder", "shopinvader/odoo-shopinvader", "OCA/server-env"]''
ENV RUNBOAT_API_ADMIN_USER="admin"
ENV RUNBOAT_API_ADMIN_PASSWD="admin"
ENV RUNBOAT_BUILD_NAMESPACE=runboat-builds
ENV RUNBOAT_BUILD_DOMAIN=runboat-builds.example.com
ENV RUNBOAT_BUILD_ENV='{"PGHOST": "postgres14.runboat-builds-db", "PGPORT": "5432", "PGUSER": "runboat-build"}'
ENV RUNBOAT_BUILD_SECRET_ENV='{"PGPASSWORD": "..."}'
ENV RUNBOAT_GITHUB_TOKEN=
ENV RUNBOAT_LOG_CONFIG=/etc/runboat-log-config.yaml
ENV RUNBOAT_BASE_URL=https://runboat.example.com

ENV KUBECONFIG=/run/kubeconfig

EXPOSE 8000

CMD [ "gunicorn", "-w", "1", "-k", "runboat.uvicorn.RunboatUvicornWorker", "runboat.app:app"]
