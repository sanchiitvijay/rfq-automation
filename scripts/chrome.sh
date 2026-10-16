#!/usr/bin/env bash
# Opens Chrome with remote debugging on port 9333 (needed for the live ferguson.com lookup).
# Uses a separate profile so your normal Chrome is untouched. Visit ferguson.com once in it.
# The many "ERROR ... page_load_metrics" / "handshake failed" lines it prints are harmless Chrome noise.
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9333 --user-data-dir="$HOME/chrome-debug-profile" --no-first-run \
  "https://www.ferguson.com/" > /dev/null 2>&1
