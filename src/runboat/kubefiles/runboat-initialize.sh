#!/bin/bash

#
# Clone repo and install all addons in the test database.
#

set -ex

bash /runboat/runboat-clone-and-install.sh

oca_wait_for_postgres

# Drop database, in case we are reinitializing.
dropdb --if-exists $PGDATABASE

ADDONS=$(addons --addons-dir ${ADDONS_DIR} --include "${INCLUDE}" --exclude "${EXCLUDE}" list)

unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  -d ${PGDATABASE} \
  -i ${ADDONS:-base} \
  --stop-after-init
