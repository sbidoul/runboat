#!/bin/bash

#
# Clone repo and install all addons in the test database.
#

set -ex

bash /runboat/runboat-clone-and-install.sh

oca_wait_for_postgres

# Drop database, in case we are reinitializing.
dropdb --if-exists ${PGDATABASE}
dropdb --if-exists ${PGDATABASE}-baseonly

ADDONS=$(manifestoo --select-addons-dir ${ADDONS_DIR} --select-include "${INCLUDE}" --select-exclude "${EXCLUDE}" list --separator=,)

# In Odoo 19+, demo data is not loaded by default. We enable it via $ODOO_RC,
# because --with-demo does not exists in previous version and would error out,
# while unknown options in the configuration file are ignored.
echo "with_demo = True" >> $ODOO_RC

# Create the baseonly database if installation failed.
unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --db-template=template1 \
  -d ${PGDATABASE}-baseonly \
  -i base \
  --stop-after-init

# Try to install all addons, but do not fail in case of error, to let the build start
# so users can work with the 'baseonly' database.
unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --db-template=template1 \
  -d ${PGDATABASE} \
  -i ${ADDONS:-base} \
  --stop-after-init || dropdb --if-exists ${PGDATABASE} && exit 0
