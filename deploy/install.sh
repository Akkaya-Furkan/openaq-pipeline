#!/bin/sh
# Install the systemd --user units for this checkout and enable the hourly timer.
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
dest="$HOME/.config/systemd/user"
mkdir -p "$dest" "$HOME/.config/openaq-pipeline"
sed "s|@REPO@|$repo|g" "$repo/deploy/openaq-pipeline.service" > "$dest/openaq-pipeline.service"
cp "$repo/deploy/openaq-pipeline.timer" "$dest/"
systemctl --user daemon-reload
systemctl --user enable --now openaq-pipeline.timer
systemctl --user list-timers openaq-pipeline.timer
