#!/usr/bin/env bash
# Read a JSON array from stdin and convert to naxel text format:
#   Object array → 👉👈 separator text (main collection)
#   String array → comma-separated text (reference collection)

set -euo pipefail

input=$(cat)

first_type=$(printf '%s' "$input" | jq -r '
  if length == 0 then "empty"
  elif (.[0] | type) == "object" then "object"
  elif (.[0] | type) == "string" then "string"
  else "unknown"
  end
')

case "$first_type" in
    object)
        printf '%s' "$input" | jq -r '
          .[] | "🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔\n" +
          (to_entries | map("👉\(.key)👈\n\(.value)") | join("\n"))
        '
        ;;
    string)
        printf '%s' "$input" | jq -r 'join(",")'
        ;;
    empty)
        ;;
    *)
        echo "error: expected a JSON array of objects or strings" >&2
        exit 1
        ;;
esac
