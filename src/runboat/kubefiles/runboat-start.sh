#!/bin/bash

#
# Start Odoo
#

set -ex

if [ ! -f /mnt/data/initialized ] ; then
    echo "Build is not initialized. Cannot start."
    exit 1
fi

# show what is installed (the venv in /opt/odoo-venv has been mounted)
pip list

# Install 'deb' external dependencies of all Odoo addons found in path.
DEBIAN_FRONTEND=noninteractive apt-get install -qq --no-install-recommends $(oca_list_external_dependencies deb)

oca_wait_for_postgres

# --db_user is necessary for Odoo <= 10
unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --no-database-list \
  --database ${PGDATABASE} \
  --db-filter=^${PGDATABASE} \
  --db_user=${PGUSER}
