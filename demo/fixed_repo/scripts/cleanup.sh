#!/bin/bash
set -euo pipefail

echo "cleaning..."
rm -rf /tmp/build_cache
rm -rf ./dist/tmp
echo "cleanup done: OK"
