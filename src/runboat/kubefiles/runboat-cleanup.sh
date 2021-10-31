#!/bin/bash

set -ex

dropdb --if-exists --force $PGDATABASE
