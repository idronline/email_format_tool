#!/usr/bin/env bash
# Copy the shared IDR tools files from their master copies to every tool repo.
#
# Master copies (edit only these):
#   email_format_tool/shared/static/   idr-tools.css, idr-tools.js        -> all four tools
#   email_format_tool/shared/flask/    _nav.html, login.html, idr_login.py -> Translate, Audio, Image Search
#   email_format_tool/shared/          idr_usage.py (usage log for /admin)  -> all four tools
#   email_format_tool/deploy/          idr-deploy.sh, idr_healthcheck.py   -> Image Search
# (Email Collector's own nav.html / login.html / login.py are FastAPI versions and stay separate.)
#
# Run on the laptop, where all four repos sit side by side in one folder:
#   shared/sync.sh           copy, then list which repos changed (commit + push each one)
#   shared/sync.sh --check   only report copies that differ; exit 1 if any do
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)          # email_format_tool
ROOT=$(dirname "$HERE")                          # folder holding all the tool repos
CHECK=$([ "${1:-}" = "--check" ] && echo 1 || echo 0)

COPIES=(
  "shared/static/idr-tools.css  email_format_tool/idr_emails/static multilang_translation_ui/static audio_generation/static idr-image-search/static"
  "shared/static/idr-tools.js   email_format_tool/idr_emails/static multilang_translation_ui/static audio_generation/static idr-image-search/static"
  "shared/flask/_nav.html       multilang_translation_ui/templates audio_generation/templates idr-image-search/templates"
  "shared/flask/login.html      multilang_translation_ui/templates audio_generation/templates idr-image-search/templates"
  "shared/flask/idr_login.py    multilang_translation_ui audio_generation idr-image-search"
  "shared/idr_usage.py          email_format_tool/idr_emails multilang_translation_ui audio_generation idr-image-search"
  "deploy/idr-deploy.sh         idr-image-search/deploy"
  "deploy/idr_healthcheck.py    idr-image-search/deploy"
)

differ=0
changed_repos=()
for line in "${COPIES[@]}"; do
  read -r src dests <<< "$line"
  for dest in $dests; do
    repo=${dest%%/*}
    target="$ROOT/$dest/$(basename "$src")"
    if [ ! -d "$ROOT/$repo" ]; then
      echo "skip  $repo (not found next to email_format_tool)"; continue
    fi
    if ! cmp -s "$HERE/$src" "$target"; then
      differ=1
      if [ "$CHECK" = 1 ]; then
        echo "DIFFERS  $dest/$(basename "$src")"
      else
        cp -p "$HERE/$src" "$target"
        echo "updated  $dest/$(basename "$src")"
        [[ " ${changed_repos[*]:-} " == *" $repo "* ]] || changed_repos+=("$repo")
      fi
    fi
  done
done

if [ "$CHECK" = 1 ]; then
  [ $differ = 0 ] && echo "All copies match the master copies."
  exit $differ
fi
if [ ${#changed_repos[@]} = 0 ]; then
  echo "Everything already matches the master copies."
else
  echo
  echo "Changed: ${changed_repos[*]} - review, commit and push each, then run idr-deploy on the servers."
fi
