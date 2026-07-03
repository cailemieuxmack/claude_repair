#!/usr/bin/env bash
#
# Entry point for the dockerized APR tool.
#
# Expects two bind-mounted directories:
#   /input  - buggy code + test cases (read)
#   /output - where the repaired controller.c, patch, and report are written
#
# Input layout (filenames overridable via the env vars below):
#   /input/controller.c        (SOURCE)
#   /input/controller.h        (HEADER)
#   /input/test_driver.cpp     (DRIVER)
#   /input/test/               (TEST_DIR: n1/, p1/, ... test cases)
#
# The Anthropic API key must be provided at run time:
#   docker run -e ANTHROPIC_API_KEY=sk-... ...
#
# Any extra arguments passed to `docker run <image> ...` are forwarded
# straight to the tool, e.g.  --verbose --enable-asan --max-attempts 8
set -euo pipefail

INPUT_DIR="${INPUT_DIR:-/input}"
OUTPUT_DIR="${OUTPUT_DIR:-/output}"

SOURCE="${INPUT_DIR}/${SOURCE_NAME:-controller.c}"
HEADER="${INPUT_DIR}/${HEADER_NAME:-controller.h}"
DRIVER="${INPUT_DIR}/${DRIVER_NAME:-test_driver.cpp}"
TEST_DIR="${INPUT_DIR}/${TEST_SUBDIR:-test}"

err() { echo "[entrypoint] ERROR: $*" >&2; exit 1; }

[ -n "${ANTHROPIC_API_KEY:-}" ] || err "ANTHROPIC_API_KEY is not set. Pass it with: docker run -e ANTHROPIC_API_KEY=... "
[ -d "$INPUT_DIR" ]  || err "input directory '$INPUT_DIR' is not mounted."
[ -d "$OUTPUT_DIR" ] || err "output directory '$OUTPUT_DIR' is not mounted."
[ -f "$SOURCE" ]     || err "source file not found: $SOURCE"
[ -f "$HEADER" ]     || err "header file not found: $HEADER"
[ -f "$DRIVER" ]     || err "driver file not found: $DRIVER"
[ -d "$TEST_DIR" ]   || err "test directory not found: $TEST_DIR"

exec python -m apr_tool \
    --source   "$SOURCE" \
    --header   "$HEADER" \
    --driver   "$DRIVER" \
    --test-dir "$TEST_DIR" \
    --output   "$OUTPUT_DIR" \
    "$@"
