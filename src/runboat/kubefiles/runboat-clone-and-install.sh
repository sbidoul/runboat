#!/bin/bash

set -ex


# If it exists, copy the previously initialized venv.
if [ -f /mnt/data/initialized ] ; then
    #rsync -a --delete /mnt/data/odoo-venv/ /opt/odoo-venv
    pip list
    # issue#23: install debian package dependencies (hack oca_install_addons to only
    # install deb)
    exit 0
fi
DEBIAN_FRONTEND=noninteractive apt-get -yqq install rsync

# Remove addons dir, in case we are reinitializing after a previously
# failed installation.
rm -fr $ADDONS_DIR

#
# Clone an addons repository at git reference in $ADDONS_DIR.
# Run oca_install_addons on it.
#

git clone --quiet --filter=blob:none $RUNBOAT_GIT_REPO $ADDONS_DIR
cd $ADDONS_DIR
git fetch origin $RUNBOAT_GIT_REF:build
git checkout build

oca_install_addons

# Keep a copy of the venv that we can re-use for shorter startup time.
rsync -a /opt/odoo-venv/ /mnt/data/odoo-venv

touch /mnt/data/initialized
