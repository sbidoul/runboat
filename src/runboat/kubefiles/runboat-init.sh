#!/bin/bash

#
# Install all addons to test.
#

set -ex

bash /runboat/runboat-clone-and-install.sh

oca_wait_for_postgres

# TODO: do nothing if db exists and all addons are installed, so we can start instantly

ADDONS=$(addons --addons-dir ${ADDONS_DIR} --include "${INCLUDE}" --exclude "${EXCLUDE}" list)

unbuffer $(which odoo || which openerp-server) \
  -d ${PGDATABASE} \
  -i ${ADDONS:-base} \
  --stop-after-init
