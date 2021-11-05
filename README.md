# runboat ☸️

A simple Odoo runbot lookalike on kubernetes. Main goal is replacing the OCA runbot.

## Principle of operation

This program is a Kubernetes operator that manages Odoo instances with pre-installed
addons. The addons come from commits on branches and pull requests in GitHub
repositories. A deployment of a given commit of a given branch or pull request of a
given repository is known as a build.

Runboat has the following main components:

- An in-memory database of builds, with their current status.
- A REST API to list builds and trigger new deployments as well as start, stop, redeploy
  or undeploy builds.
- A GitHub webhook to automatically trigger new builds on pushes to branches and pull
  requests of supported repositories.
- A controller that performs the following tasks:

  - monitor deployments in a kubernetes namespaces to maintain the in-memory database;
  - on new deployments, trigger an initialization job to create the corresponding
    postgres database and install the addons in it;
  - initialization jobs are started concurrently up to a configured limit;
  - when the initialization job succeeds, scale up the deployment, so it becomes
    accessible;
  - when the initializaiton job fails, flag the deployment as failed;
  - when there are too many deployments started, stop the oldest started;
  - when there are too many deployments, deleted the oldest created;
  - when a deployment is deleted, run a cleanp job to destroy the database and delete
    all kubernetes resources associated with the deployment.

When a deployment is stopped, the corresponding postgres database remains present, so
deployments can restart almost instantly.

This approach allows the deployment of a very large number of builds which consume no
memory nor CPU until they are started. The number of started deployment can also be
high, by reserving limited CPU and memory resources for each, taking advantage of the
fact that they are typically used infrequently. The number of concurrent initialization
jobs is limited strongly, and they are queued, as these are typically the more
resource-intensive part of the lifecycle of builds.

All state is stored in kubernetes resources (labels and annotations on deployments). The
controller can be stopped and restarted without losing state.

## Requirements

For running the builds:

- A namespace in a kubernetes cluster.
- A wildcard DNS domain that points to the kubernetes ingress.
- A postgres database, accessible from within the cluster namespace with a user with
  permissions to create database.

For running the controller (runboat itself):

- Python 3.10
- `kubectl`
- A `KUBECONFIG` that provides access to the namespace where the builds are deployed,
  with permissions to create and delete Service, Job, Deployment, Ingress, Secret and
  ConfigMap resources.
- Some sort of reverse proxy to expose the REST API.

The controller can be run outside the kubernetes cluster or deployed inside it, or even
in a different cluster.

## Developing

- setup environment variables (start from `.env.sample`)
- create a virtualenv, make sure to have pip>=21.3.1 and `pip install -e .`
- run with `uvicorn runboat.app:app --log-config=log-config-dev.yaml`

## Running in production

`gunicorn -w 1 -k runboat.uvicorn.RunboatUvicornWorker runboat.app:app`.

One and only one worker process !

Gunicorn also necessary so SIGINT/SIGTERM shutdowns after a few seconds. Since we use
`run_in_executor`, SIGINT/SIGTERM handling does not work very well, and gunicorn makes
it more robust. https://bugs.python.org/issue29309

## Kubernetes resources

All resources to be deployed in kubernetes for a build are in `src/runboat/kubefiles`.
They are gathered together from a `kustomization.yaml` jinja template that leads to
three possible resource groups depending on a mode variable in the jinja rendering context:

- the deployment with its associated service and ingress;
- the initialization job that creates the database;
- the cleanup job that drops the database;

Besides the three modes, the controller as little of what the kubefiles actually deploy.

It expect and does the following about the kubernetes resources:

- a deployment starts with 0 replicas and must initially have a
  `runboat/init-status=todo` label, as well as a finalizer;
- the intialization job starts with a `runboat/job-kind=initialize` label;
- the cleanup job starts with a `runboat/job-kind=cleanup` label.

The controller sets the following labels on resources:

- `runboat/build`, with the unique build name as identifier.

The controller sets the following annotations on resources:

- `runboat/repo`: the repository in owner/repo format;
- `runboat/target-branch`: the branch or pull request base branch;
- `runboat/pr`: the pull request number or "";
- `runboat/git-commit`: the commit sha.

It also sets a `runboat/init-status` annotation to track the outcome of initialization jobs (`todo`, `started`, `succeeded`, `failed`).

## TODO

Prototype (min required to do load testing):

- plug it on a bunch of OCA and shopinvader repos to test load
- configuring many repos in a .env file may be difficult, switch to a toml file ?

MVP:

- deployment and more load testing
- build/log and build/init-log api endpoints
- report build status to github
- secure github webhooks
- k8s init container timeout
- better error handling in API (return 400 on user errors)
- basic tests
- build and publish runboat container image
- look at other TODO in code to see if anything important remains
- basic UI (single page with a combo box to select repo and show builds by branch/pr,
  with start/stop buttons)

More:

- shiny UI
- websocket stream of build changes, for a dynamic UI
- handle PR close (delete all builds for PR)
- handle branch delete (delete all builds for branch)
- create builds for all supported repos on startup (goes with sticky branches)
- never undeploy last build of sticky branches
- make build images configurable (see `build_images.py`)

## Author and contributors

Authored by Stéphane Bidoul (@sbidoul).

Contributions welcome.
