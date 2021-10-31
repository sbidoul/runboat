# runboat ☸️

A simple Odoo runbot lookalike on kubernetes. Main goal is replacing the OCA runbot.

## Requirements

For running the builds:

- A namespace in a kubernetes cluster.
- A wildcard DNS domain that points to the kubernetes ingress.
- A postgres database, accessible from within the cluster namespace with a user with
  permissions to create database.

For running the controller:

- Python 3.10
- `kubectl`
- A `KUBECONFIG` that provides access to the namespace where the builds are deployed,
  with permissions to create and delete Service, Job, Deployment, Ingress, Secret and
  ConfigMap resources.

## Developing

- setup environment variables (start from `.env.sample`)
- create a virtualenv, make sure to have pip>=21.3.1 and `pip install -e .`
- run with `uvicorn runboat.app:app --reload --log-config=log-config-dev.yaml`

## Author and contributors

Authored by Stéphane Bidoul (@sbidoul).

Contributions welcome.

## TODO

Prototype (min required to do load testing):

- github token for github api requests
- set requests otherwise requests is same as limits ?
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
- test what happens when the watcher looses connection to k8s
- look at other TODO in code to see if anything important remains
- basic UI (single page with a combo box to select repo and show builds by branch/pr,
  with start/stop buttons)

More:

- shiny UI
- handle PR close (delete all builds for PR)
- handle branch delete (delete all builds for branch)
- create builds for all supported repos on startup (goes with sticky branches)
- never undeploy last build of sticky branches
- make build images configurable (see `build_images.py`)


## Kubefiles

Kustomize template with 3 modes (deploy, initialize, cleanup).

## Synchronous actions on builds (fast)

- deploy

  - create deployment with 0 replicas and runboat/init-status="todo"

- start:

  - if runboat/init-status=="ready", scale to 1
  - elif runboat/init-status in ("todo", "initializing"), do nothing
  - elif runboat/init-status=="failed", set runboat/init-status="todo"

- stop:

  - scale deployment to 0

- undeploy:

  - scale deployment to 0
  - set runboat/init-status to "dropping"
  - start dropdb job (restart=Never, backoffLimit=6)

## Workers

- initializer (works on deployments with runboat/init-status="todo", ordered by
  runboat/init-status-timestamp), obeying max_initializing:

  - set runboat/init-status to "initializing"
  - (re)create init job which will drop and init db (restart=Never, backoffLimit=0)

- job-watcher:

  - on successful termination of initdb job: set runboat/init-status to "ready", scale
    deployment to 1
  - on failure of initdb job: set runboat/init-status to "failed"
  - on success of dropdb job: delete all resources

- deployment-watcher:

  - maintains an in-memory db of deployments

- stopper:

  - stop old started, to reach max_running

- undeployer:

  - undeploy old stopped, to reach max_deployed
