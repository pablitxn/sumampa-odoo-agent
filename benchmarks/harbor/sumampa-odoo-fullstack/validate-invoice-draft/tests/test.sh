#!/usr/bin/env bash
set -u

mkdir -p /logs/verifier /logs/artifacts
python /tests/verify.py
