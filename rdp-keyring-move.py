#!/usr/bin/env python3
"""Move GNOME Remote Desktop's RDP credential into a keyring that is readable
right after autologin.

WHY: grd keeps its RDP username/password in the GNOME keyring (the "default"
collection, usually the password-protected Login keyring). GDM
autologin never types a password, so that keyring stays locked after every
reboot, grd can't read the credential, and every client gets denied with
"Credentials are not set". It looks like the credentials vanished. They
were never empty, just locked.

FIX: create a separate keyring named "RDP" with an EMPTY master password
(gnome-keyring stores that one unencrypted, so it's available at login with no
unlock), copy the credential there, verify the copy, then remove the original.
grd looks credentials up across all keyrings by schema, so it finds the new one.

Tradeoff, on purpose: the RDP password sits unencrypted in
~/.local/share/keyrings/ (mode 600). That's inherent to "autologin + headless
RDP". Only this one secret moves; everything else stays in the encrypted
default keyring.

Run as the desktop user, in the desktop session, while the default keyring is
unlocked.
Safe to re-run: it no-ops if the credential is already in the RDP keyring.
The secret value is never printed.
"""
import getpass
import sys

import dbus

BUS_NAME = "org.freedesktop.secrets"
SERVICE_PATH = "/org/freedesktop/secrets"
SCHEMA = {"xdg:schema": "org.gnome.RemoteDesktop.RdpCredentials"}
RDP_KEYRING_LABEL = "RDP"

bus = dbus.SessionBus()
svc_obj = bus.get_object(BUS_NAME, SERVICE_PATH)
svc = dbus.Interface(svc_obj, "org.freedesktop.Secret.Service")


def prop(path, iface, name):
    obj = bus.get_object(BUS_NAME, path)
    return obj.Get(iface, name, dbus_interface="org.freedesktop.DBus.Properties")


# "plain" session = secrets travel over the session bus unencrypted. Fine here:
# the bus is local to this user, and it's what libsecret itself falls back to.
_, session = svc.OpenSession("plain", dbus.String("", variant_level=1))

# --- 1. Find or create the unencrypted "RDP" keyring ---
rdp_coll = None
for coll in prop(SERVICE_PATH, "org.freedesktop.Secret.Service", "Collections"):
    if prop(coll, "org.freedesktop.Secret.Collection", "Label") == RDP_KEYRING_LABEL:
        rdp_coll = coll
        break

if rdp_coll is None:
    # The standard CreateCollection API always pops a GUI password prompt.
    # gnome-keyring's internal interface lets us pass the master password
    # directly; an empty one is exactly "unencrypted keyring".
    internal = dbus.Interface(svc_obj, "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface")
    empty_master = (session, dbus.ByteArray(b""), dbus.ByteArray(b""), "text/plain")
    rdp_coll = internal.CreateWithMasterPassword(
        {"org.freedesktop.Secret.Collection.Label": RDP_KEYRING_LABEL}, empty_master
    )
    print(f"Created unencrypted keyring '{RDP_KEYRING_LABEL}'")

# --- 2. Locate the credential ---
unlocked, locked = svc.SearchItems(SCHEMA)
in_rdp = [p for p in unlocked if p.startswith(rdp_coll + "/")]
elsewhere_unlocked = [p for p in unlocked if not p.startswith(rdp_coll + "/")]

if in_rdp and not elsewhere_unlocked and not locked:
    print("RDP credential is already in the RDP keyring. Nothing to do.")
    sys.exit(0)

if not elsewhere_unlocked:
    if locked:
        sys.exit("The RDP credential is in a LOCKED keyring. Unlock it first (open 'Passwords and Keys' "
                 "and unlock the default keyring, or connect over RDP once after typing the keyring password), "
                 "then re-run this script.")
    sys.exit(f"No RDP credential found. Set one with:  grdctl rdp set-credentials {getpass.getuser()}  then re-run this script.")

source = elsewhere_unlocked[0]

# --- 3. Copy it byte-for-byte (label, attributes, secret, content type) ---
# Copying the raw secret instead of re-running grdctl avoids depending on
# grd's internal serialization format and avoids re-typing the password.
src_secret = svc.GetSecrets([source], session)[source]
label = prop(source, "org.freedesktop.Secret.Item", "Label")
attrs = prop(source, "org.freedesktop.Secret.Item", "Attributes")

coll_iface = dbus.Interface(bus.get_object(BUS_NAME, rdp_coll), "org.freedesktop.Secret.Collection")
new_item, _ = coll_iface.CreateItem(
    {
        "org.freedesktop.Secret.Item.Label": label,
        "org.freedesktop.Secret.Item.Attributes": dbus.Dictionary(attrs, signature="ss"),
    },
    (session, src_secret[1], src_secret[2], src_secret[3]),
    True,  # replace an existing item with the same attributes (makes re-runs safe)
)

# --- 4. Verify before removing anything ---
new_secret = svc.GetSecrets([new_item], session)[new_item]
if bytes(new_secret[2]) != bytes(src_secret[2]):
    sys.exit("Copy verification FAILED. Original left untouched.")

# Remove the original so there is exactly one credential. If both existed,
# grd would pick whichever the keyring returns first, and a future edit to one
# copy would silently not take effect.
dbus.Interface(bus.get_object(BUS_NAME, source), "org.freedesktop.Secret.Item").Delete()
print(f"Moved RDP credential into the '{RDP_KEYRING_LABEL}' keyring (verified, original removed).")
