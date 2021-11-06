# runboat ☸️

A simple Odoo runbot lookalike on kubernetes. Main goal is replacing the OCA runbot.

[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/sbidoul/runboat/main.svg)](https://results.pre-commit.ci/latest/github/sbidoul/runboat/main)

## Principle of operation

This program is a Kubernetes operator that manages Odoo instances with pre-installed
addons. The addons come from commits on branches and pull requests in GitHub
repositories. A deployment of a given commit of a given branch or pull request of a
given repository is known as a build.

Runboat has the following main components:

- An in-memory database of deployed builds, with their current status.
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
  - when there are too many deployments, delete the oldest created;
  - when a deployment is deleted, run a cleanp job to drop the database and delete
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

- setup environment variables (start from `.env.sample`, the meaning of the environment
  variables is documented in [settings.py](./src/runboat/settings.py))
- create a virtualenv, make sure to have pip>=21.3.1 and `pip install -c
  requirements.txt -e .[test]`
- run with `uvicorn runboat.app:app --log-config=log-config.yaml`
- api documentation is at `http://localhost:8000/docs`
- run tests with `pytest` (environment variables used in tests are declared in
  `.env.test`)

## Running in production

`gunicorn -w 1 -k runboat.uvicorn.RunboatUvicornWorker runboat.app:app`.

One and only one worker process !

Gunicorn also necessary so SIGINT/SIGTERM shutdowns after a few seconds. Since we use
`run_in_executor`, SIGINT/SIGTERM handling does not work very well, and gunicorn makes
it more robust. https://bugs.python.org/issue29309

## Kubernetes resources

All resources to be deployed in kubernetes for a build are in
[src/runboat/kubefiles](./src/runboat/kubefiles). They are gathered together from a
`kustomization.yaml` jinja template that leads to three possible resource groups
depending on a `mode` variable in the jinja rendering context:

- `deployment` creates a kubernetes deployment with its associated service and ingress;
- `initialization` creates a job that creates the database;
- `cleanup` creates a job that drops the database;

Besides the three modes, the controller has limited knowledge of what the kubefiles
actually deploy. It expects the following to hold true:

- the `runboat/build` label is set on all resources, with the unique build name as
  value;
- a deployment starts with 0 replicas and is created with a
  `runboat/init-status=todo` label, as well as a `runboat/cleanup` finalizer;
- the intialization job has a `runboat/job-kind=initialize` label;
- the cleanup job has a `runboat/job-kind=cleanup` label.
- the following annotations are set on deployments:

  - `runboat/repo`: the repository in owner/repo format;
  - `runboat/target-branch`: the branch or pull request target branch;
  - `runboat/pr`: the pull request number if this build is for a pull request;
  - `runboat/git-commit`: the commit sha.

- the home page of a running build is exposed at `http://{build_slug}.{build_domain}`.

During the lifecycle of a build, the controller does the following on the deployed
resources:

- it sets the `runboat/init-status` annotation (`todo`, `started`, `succeeded`,
  `failed`) on deployments to track the outcome of the initialization jobs;
- it sets the deployment's `specs.replica` to 1 or 0 to start or stop it;
- it deletes the deployment when an undeploy is requested (the actual delete occurs
  later due to the finalizer);
- it removes the deployment finalizers and deletes resources matching the
  `runboat/build` label after the cleanup job succeeded.

## TODO

Advanced prototype (min required to open the project):

- plug it on a bunch of OCA and shopinvader repos to test load

MVP:

- build/log and build/init-log api endpoints
- better error handling in API (return 400 on user errors)
- more tests
- look at other TODO in code to see if anything important remains
- basic UI (single page with a combo box to select repo and show builds by branch/pr,
  with start/stop buttons)
- secure github webhooks
- deployment and more load testing

More:

- shiny UI
- websocket stream of build changes, for a dynamic UI
- handle PR close (delete all builds for PR)
- handle branch delete (delete all builds for branch)
- create builds for all supported repos on startup (goes with sticky branches)
- never undeploy last build of sticky branches
- configurable kubefiles directory
- even more tests

## Author and contributors

Authored by Stéphane Bidoul (@sbidoul).

Contributions welcome.
