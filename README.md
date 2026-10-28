# rdp-autofix

Keeps GNOME Remote Desktop working across reboots on an Ubuntu machine that logs in automatically.

> Built with Claude for my own machine and shared as is. It works on my setup (Ubuntu 26.04, GNOME 50, gnome-remote-desktop 50.2, GDM autologin). Issues and pull requests are welcome, and I'll update it as needed.

## The problem

You set up Desktop Sharing so you can RDP into a machine (a headless laptop, a home server). It works. Then the machine reboots or installs updates, and RDP stops working. Typing the RDP password into Settings again fixes it until the next reboot.

There are usually two separate problems that show up together and look like one.

### 1. The credentials are locked in the keyring

gnome-remote-desktop stores its RDP username and password in the GNOME keyring, in your default keyring, which has a password. **Automatic login never unlocks a keyring.** So after every boot gnome-remote-desktop can't read its credentials, and it rejects every client with:

```
[RDP] Credentials are not set, denying client
```

The credentials were never lost. Setting them again only seems to fix it because doing that unlocks the keyring as a side effect.

### 2. Two RDP servers fighting over port 3389

If xrdp is also installed, it and gnome-remote-desktop both want port 3389. Whichever starts first wins. gnome-remote-desktop quietly moves to port 3390 when it loses, so your client gets either xrdp (which starts a new, separate session) or nothing. Package updates can re-enable xrdp, so a one-time fix doesn't hold.

## What this installs

| Piece | Runs as, and when | What it does |
|---|---|---|
| `rdp-keyring-move.py` | you, once (install runs it) | Moves the RDP credential into its own keyring named `RDP` with no password, checks the copy, then removes the original. Never prints the password. |
| `rdp-guard` + `rdp-guard.service` | root, every boot, before xrdp and the login screen | Stops and masks xrdp if anything has turned it back on. Does nothing if xrdp isn't installed. |
| `99rdp-guard` (apt hook) | root, after every apt run | Same check, so an update can't re-arm xrdp before the next reboot. |
| `rdp-session-guard` + user service | you, at every login | Makes sure gnome-remote-desktop is on port 3389 (restarts it once the port is free if not), then logs whether the credential is in the `RDP` keyring. |

### The tradeoff, read this first

GNOME keyring stores a keyring with an empty password **unencrypted** (`~/.local/share/keyrings/RDP.keyring`, readable only by you). So the RDP password sits on disk in plain form. Anyone with root, or with access to your account, can read it.

That's built into "log in automatically and accept RDP with no one at the keyboard". There's no way around it if nobody is there to unlock a keyring. Only this one secret moves. Everything else stays in your encrypted keyring. Use a unique password for RDP, and don't expose port 3389 to the internet. Reach it over a VPN such as Tailscale or WireGuard.

## Install

1. Turn on remote desktop: **Settings > System > Remote Desktop > Desktop Sharing**. Turn on Desktop Sharing and Remote Control, and set a username and password.
2. Optional but recommended: if you don't use xrdp, remove it.
   ```bash
   sudo apt purge xrdp
   ```
3. Get the files and run the installer as your normal user, **not** with sudo. It asks for sudo itself for the system parts.
   ```bash
   git clone https://github.com/coltonfretz/rdp-autofix.git
   ```
   ```bash
   ./rdp-autofix/install.sh
   ```
   Your default keyring needs to be unlocked while it runs. It will be if you're logged in at the desktop.
4. Reboot, and connect over RDP without touching the machine.

The installer is safe to run again.

Needs `python3-dbus`, which Ubuntu desktop installs by default.

## If RDP breaks again

Run these as your normal user:

```bash
journalctl --user -u rdp-session-guard -b --no-pager -o cat
```

```bash
journalctl --user -b -u gnome-remote-desktop --no-pager | grep -iE 'denying|started'
```

```bash
ss -tlnp | grep -E ':(3389|3390)'
```

Then go by what they show:

- **"OK: RDP credentials in the RDP keyring; gnome-remote-desktop on port 3389"**: the machine's side is fine. Look at the network, the VPN or the client.
- **"Credentials are not set, denying client"**, or a guard warning about another keyring: the credential ended up back in the locked keyring. The usual cause is changing the RDP password, which always writes to the default keyring. Run `rdp-keyring-move.py` from this folder again. If it says the credential is locked, unlock your default keyring first (open Passwords and Keys), then run it again.
- **gnome-remote-desktop on 3390**: something is holding 3389. Find it with `sudo ss -tlnp | grep :3389`, and check `dpkg -l xrdp` in case xrdp came back.
- **gnome-remote-desktop not listening at all**: `systemctl --user start gnome-remote-desktop`.

## Changing the RDP password

Change it in Settings (or with `grdctl rdp set-credentials`), then run `rdp-keyring-move.py` again. **Every time.** If you skip it, RDP keeps working until the next reboot and then breaks.

## Things not to do

- **Don't `pkill` gnome-remote-desktop.** It's a systemd user service, and nothing restarts it after a kill. Use `systemctl --user restart gnome-remote-desktop`.
- **Don't run gnome-remote-desktop or keyring commands as root.** They belong to your session and do nothing useful from a root shell.
- **Don't restart `systemd-logind`** to "fix" a session. It can leave you with a black screen and a stuck session.

## Safe-to-ignore log noise

- A "client authentication failure" or "Connection reset by peer" during NLA, followed by a successful connection on the next try. Normal client behavior.
- `Cannot load libcuda.so.1` / `libnvidia-encode.so.1` when gnome-remote-desktop starts, on a machine without an NVIDIA GPU.

## Uninstall

```bash
sudo systemctl disable --now rdp-guard.service
```

```bash
sudo rm /usr/local/sbin/rdp-guard /etc/systemd/system/rdp-guard.service /etc/apt/apt.conf.d/99rdp-guard
```

```bash
systemctl --user disable rdp-session-guard.service
```

```bash
rm ~/.local/bin/rdp-session-guard ~/.config/systemd/user/rdp-session-guard.service
```

The `RDP` keyring stays until you delete it in Passwords and Keys. If you do, set the RDP password again in Settings.

## License

MIT. See [LICENSE](LICENSE).
