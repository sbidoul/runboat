#!/bin/bash

set -ex

#
# Clone an addons repository at git reference in $ADDONS_DIR.
# Run oca_install_addons and oca_init_db on it.
#

git clone --filter=blob:none $RUNBOAT_GIT_REPO $ADDONS_DIR
cd $ADDONS_DIR
git fetch origin $RUNBOAT_GIT_REF:build
git checkout build

oca_install_addons

# disable the database manager
echo "list_db = False" >> $ODOO_RC
