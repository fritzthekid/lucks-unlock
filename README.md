# luks-unlock

A lightweight web interface for unlocking and managing LUKS-encrypted partitions on a Raspberry Pi (or any Linux server). Built with Flask and served via uWSGI.

## Features

- **Login** using existing Linux system accounts (PAM authentication)
- **Unlock & mount** two LUKS-encrypted partitions with a single passphrase
- **Lock** (unmount & close) all encrypted partitions
- **Disk status** — used/free space, fill level bar, S.M.A.R.T. health and temperature
- **File browser** — read-only navigation of mounted volumes
- Accessible via browser over LAN or VPN (e.g. WireGuard)

## Use Case

The server boots normally and remains accessible via SSH. The encrypted data partitions (`/mnt/backup`, `/mnt/nas`) stay locked until an authorized user logs into the web interface and enters the LUKS passphrase. This avoids storing the passphrase anywhere on the system while still allowing remote unlock over a secure VPN connection.

## Requirements

- Python 3.10+
- `python-pam`, `flask`, `uwsgi` (see below)
- `smartmontools` (optional, for S.M.A.R.T. data)
- Two LUKS2-encrypted partitions configured in `/etc/crypttab` and `/etc/fstab`
- `sudo` rules allowing the web server process to run `cryptsetup` and `mount`

## Installation

```bash
# Clone the repository
git clone https://github.com/fritzthekid/luks-unlock
cd luks-unlock

# Create a virtual environment
python3 -m venv .venv
.venv/bin/pip install flask python-pam uwsgi six

# Optional: S.M.A.R.T. support
sudo apt install smartmontools
```

## Configuration

Edit the `DEVICES` dictionary in `luks_unlock.py` to match your partition layout:

```python
DEVICES = {
    'backup': {'dev': '/dev/sda2', 'mapper': '/dev/mapper/backup', 'mount': '/mnt/backup'},
    'nas':    {'dev': '/dev/sdb2', 'mapper': '/dev/mapper/nas',    'mount': '/mnt/nas'},
}
```

### sudo rules

Add to `/etc/sudoers.d/luks-unlock` (adjust group and paths as needed):

```
%luks-users ALL=(root) NOPASSWD: /usr/sbin/cryptsetup open /dev/sda2 backup
%luks-users ALL=(root) NOPASSWD: /usr/sbin/cryptsetup open /dev/sdb2 nas
%luks-users ALL=(root) NOPASSWD: /usr/sbin/cryptsetup close backup
%luks-users ALL=(root) NOPASSWD: /usr/sbin/cryptsetup close nas
%luks-users ALL=(root) NOPASSWD: /bin/mount /dev/mapper/backup /mnt/backup
%luks-users ALL=(root) NOPASSWD: /bin/mount /dev/mapper/nas /mnt/nas
%luks-users ALL=(root) NOPASSWD: /bin/umount /mnt/backup
%luks-users ALL=(root) NOPASSWD: /bin/umount /mnt/nas
```

### systemd service

Copy `luks-unlock.service` to `/etc/systemd/system/` and adjust paths, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now luks-unlock
```

The service runs as `root` to allow `cryptsetup` and `mount` operations.

## Usage

Open `http://<server-ip>:5000` in your browser (or port 80 if nginx is configured as a reverse proxy). Log in with your Linux username and password.

## Security Notes

- Only expose this interface over a trusted network or VPN — it is not hardened for public internet access.
- The LUKS passphrase is transmitted over HTTP unless TLS is configured upstream (e.g. via nginx with a certificate).
- PAM authentication uses your existing system accounts — no separate password management required.

## Dependencies

| Package | License |
|---------|---------|
| Flask | BSD-3-Clause |
| python-pam | MIT |
| uWSGI (runtime) | GPL-2.0 |

## License

BSD 3-Clause License — see [LICENSE](LICENSE) for details.
