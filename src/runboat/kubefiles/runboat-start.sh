#!/bin/bash

#
# Start Odoo
#

set -ex

bash /runboat/runboat-clone-and-install.sh

oca_wait_for_postgres


# --db_user is necessary for Odoo <= 10

unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --no-database-list \
  -d ${PGDATABASE} \
  --db_user ${PGUSER}
