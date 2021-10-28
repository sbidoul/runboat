# runboat ☸️

A simple runbot lookalike on kubernetes. Main goal is replacing the OCA runbot.

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
  with permissions to create and delete service, deployment, ingress, secret and
  configmap resources.

## Developing

- setup environment variables (start from `.env.sample`)
- create a virtualenv, make sure to have pip>=21.3.1 and `pip install -e .`
- run with `uvicorn runboat.app:app --reload --log-config=log-config-dev.yaml`

## Author and contributors

Authored by Stéphane Bidoul (@sbidoul).

Contributions welcome.

## TODO

Prototype (min required to do load testing):

- plug it on a bunch of OCA and shopinvader repos to test load
- handle init failures, add failed status
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
