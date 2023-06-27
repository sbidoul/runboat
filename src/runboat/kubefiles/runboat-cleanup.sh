#!/bin/bash

set -ex

dropdb --if-exists --force $PGDATABASE
dropdb --if-exists --force $PGDATABASE-baseonly
