#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
tar \
  --exclude='quant_research/__pycache__' \
  --exclude='quant_research/src/__pycache__' \
  -czf quant_research.tar.gz quant_research
printf 'Created %s\n' "$(pwd)/quant_research.tar.gz"
