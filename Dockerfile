FROM python:3.10

LABEL maintainer="Stéphane Bidoul"

RUN curl -L \
  "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
  -o /usr/local/bin/kubectl \
  && chmod +x /usr/local/bin/kubectl

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV RUNBOAT_REPOS='[{"repo": "^oca/.*", "branch": "^15.0$", "builds": [{"image": "ghcr.io/oca/oca-ci/py3.8-odoo15.0:latest"}]}]'
ENV RUNBOAT_API_ADMIN_USER="admin"
ENV RUNBOAT_API_ADMIN_PASSWD="admin"
ENV RUNBOAT_BUILD_NAMESPACE=runboat-builds
ENV RUNBOAT_BUILD_DOMAIN=runboat-builds.example.com
ENV RUNBOAT_BUILD_ENV='{"PGHOST": "postgres14.runboat-builds-db", "PGPORT": "5432", "PGUSER": "runboat-build"}'
ENV RUNBOAT_BUILD_SECRET_ENV='{"PGPASSWORD": "..."}'
ENV RUNBOAT_BUILD_TEMPLATE_VARS='{}'
ENV RUNBOAT_GITHUB_TOKEN=
ENV RUNBOAT_BASE_URL=https://runboat.example.com

# KUBECONFIG to be provided by user, unless running in cluster with a service account
# having the necessary permissions.

COPY log-config.yaml /etc/runboat-log-config.yaml
ENV RUNBOAT_LOG_CONFIG=/etc/runboat-log-config.yaml

COPY src /app
ENV PYTHONPATH=/app

EXPOSE 8000

CMD [ "gunicorn", "-w", "1", "--bind", ":8000", "-k", "runboat.uvicorn.RunboatUvicornWorker", "runboat.app:app"]
