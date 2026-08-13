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
if unbuffer $(which odoo || which openerp-server) \
  --data-dir=/mnt/data/odoo-data-dir \
  --db-template=template1 \
  -d ${PGDATABASE} \
  -i ${ADDONS:-base} \
  --stop-after-init ; then
  # Grant admin all groups (except the exclusive portal/public user types) so
  # addon menus are visible to reviewers; best effort, never fails the build.
  $(which odoo || which openerp-server) shell \
    --data-dir=/mnt/data/odoo-data-dir \
    -d ${PGDATABASE} \
    --no-http <<'PYEOF' || true
Groups = env["res.groups"]
admin = env.ref("base.user_admin", raise_if_not_found=False) or env.ref("base.user_root")
field = "group_ids" if "group_ids" in admin._fields else "groups_id"
bad = Groups.browse()
for xid in ("base.group_portal", "base.group_public"):
    g = env.ref(xid, raise_if_not_found=False)
    if g:
        bad |= g
closure = next((f for f in ("all_implied_ids", "trans_implied_ids") if f in Groups._fields), "implied_ids")
groups = (Groups.search([("share", "=", False)]) - bad).filtered(lambda g: not (g[closure] & bad))
admin.write({field: [(4, g.id) for g in groups]})
env.cr.commit()
PYEOF
else
  dropdb --if-exists ${PGDATABASE}
fi
exit 0
