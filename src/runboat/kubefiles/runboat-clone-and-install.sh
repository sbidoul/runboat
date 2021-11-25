#!/bin/bash

set -ex


# If it exists, copy the previously initialized venv.
if [ -f /mnt/data/initialized ] ; then
    pip list
    # Install 'deb' external dependencies of all Odoo addons found in path.
    DEBIAN_FRONTEND=noninteractive apt-get install -qq --no-install-recommends $(oca_list_external_dependencies deb)
    exit 0
fi

DEBIAN_FRONTEND=noninteractive apt-get -yqq install rsync

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
rsync -a /opt/odoo-venv/ /mnt/data/odoo-venv

touch /mnt/data/initialized
