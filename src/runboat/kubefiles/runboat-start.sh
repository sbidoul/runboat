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

# Add ADDONS_DIR to addons_path (because that oca_install_addons did,
# but $ODOO_RC is not on a persistent volume, so it is lost when we
# start in another container).
echo "addons_path=${ADDONS_PATH},${ADDONS_DIR}" >> ${ODOO_RC}
cat ${ODOO_RC}

# Install 'deb' external dependencies of all Odoo addons found in path.
# This is also something oca_install_addons did, but that is not persisted
# when we start in another container.
deb_deps=$(oca_list_external_dependencies deb)
if [ -n "$deb_deps" ]; then
    apt-get update -qq
    # Install 'deb' external dependencies of all Odoo addons found in path.
    DEBIAN_FRONTEND=noninteractive apt-get install -qq --no-install-recommends ${deb_deps}
fi

oca_wait_for_postgres

# --db_user is necessary for Odoo <= 10
unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --no-database-list \
  --database ${PGDATABASE} \
  --db-filter=^${PGDATABASE} \
  --db_user=${PGUSER} \
  --smtp=localhost \
  --smtp-port=1025
