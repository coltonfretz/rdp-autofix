#!/bin/bash
# Installs the RDP fix. Run as your normal desktop user (NOT with sudo);
# it calls sudo itself for the system parts. Safe to re-run.
#
#   root side : /usr/local/sbin/rdp-guard + rdp-guard.service (boot)
#               + /etc/apt/apt.conf.d/99rdp-guard (after every apt run)
#   user side : ~/.local/bin/rdp-session-guard + rdp-session-guard.service
#   one-time  : move the RDP credential into an autologin-readable keyring
#
# WHY user vs root split: masking xrdp needs root; restarting
# gnome-remote-desktop and touching the keyring must happen inside the user's
# session (from root they silently do nothing useful).

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your desktop user, not root/sudo. It will ask for sudo when needed." >&2
    exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"

echo "== Root side (boot + apt guard) =="
sudo install -m 755 rdp-guard /usr/local/sbin/rdp-guard
sudo install -m 644 rdp-guard.service /etc/systemd/system/rdp-guard.service
sudo install -m 644 99rdp-guard /etc/apt/apt.conf.d/99rdp-guard
sudo systemctl daemon-reload
sudo systemctl enable rdp-guard.service
sudo /usr/local/sbin/rdp-guard   # apply now too, not just at the next boot

echo "== User side (login guard) =="
install -D -m 755 rdp-session-guard ~/.local/bin/rdp-session-guard
install -D -m 644 rdp-session-guard.service ~/.config/systemd/user/rdp-session-guard.service
systemctl --user daemon-reload
systemctl --user enable rdp-session-guard.service

echo "== Keyring (credentials readable after autologin) =="
python3 rdp-keyring-move.py

echo "== Check =="
systemctl --user start rdp-session-guard.service
journalctl --user -u rdp-session-guard -n 3 --no-pager -o cat
echo "xrdp:        $(systemctl is-enabled xrdp 2>&1)"
echo "xrdp-sesman: $(systemctl is-enabled xrdp-sesman 2>&1)"
