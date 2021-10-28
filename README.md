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

## TODO

Prototype:

- plug it on a bunch of OCA and shopinvader repos to test load
- handle init failures, add failed status
- basic API

MVP:

- finish api
- build/log and build/init-log api endpoints
- report build status to github
- k8s init container timeout
- error handling in API
- basic tests
- look at other TODO in code
- build and publis runboat container image
- deployment
- plug it on shopinvader and acsone to test on small scale
- create builds for all supported repos on startup (goes with sticky branches)
- advanced reaper (sticky branches)
- test what happens when the watcher looses connection to k8s

More:

- UI
- handle PR close (delete all builds for PR)
- handle branch delete (delete all builds for branch)
