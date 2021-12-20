#!/bin/bash

set -ex

# Remove initialization sentinel, in case we are reinitializing.
rm -fr /mnt/data/initialized

# Remove addons dir, in case we are reinitializing after a previously
# failed installation.
rm -fr $ADDONS_DIR
# Clone the repository at git reference into $ADDONS_DIR.
git clone --quiet --filter=blob:none $RUNBOAT_GIT_REPO $ADDONS_DIR
cd $ADDONS_DIR
git fetch origin $RUNBOAT_GIT_REF:build
git checkout build

# Install.
oca_install_addons

# Keep a copy of the venv that we can re-use for shorter startup time.
DEBIAN_FRONTEND=noninteractive apt-get -yqq install rsync
rsync -a --delete /opt/odoo-venv/ /mnt/data/odoo-venv

touch /mnt/data/initialized
