#!/bin/bash
# 清理临时文件
echo "cleaning..."
rm -rf /tmp/build_cache 2>/dev/null
rm -rf ./dist/tmp 2>/dev/null || true
echo "cleanup done: OK"
