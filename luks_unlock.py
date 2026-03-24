#!/usr/bin/env python3
"""
LUKS Unlock Web Interface mit Datei-Browser und Statusanzeige
Läuft auf /mnt/ssdusr/luks-unlock/
"""

from flask import Flask, request, session, redirect, url_for, render_template, abort
import pam
import subprocess
import os
import shutil
from datetime import datetime
from collections import deque
import threading

app = Flask(__name__)
app.secret_key = os.urandom(32)

# ── Log-System ──────────────────────────────────────────────────────────────
_log = deque(maxlen=200)
_log_lock = threading.Lock()

def log(msg, level='info'):
    ts = datetime.now().strftime('%H:%M:%S')
    with _log_lock:
        _log.append({'ts': ts, 'level': level, 'msg': msg})

def get_log():
    with _log_lock:
        return list(_log)

DEVICES = {
    'backup': {'dev': '/dev/sda2', 'mapper': '/dev/mapper/backup', 'mount': '/mnt/backup'},
    'nas':    {'dev': '/dev/sdb2', 'mapper': '/dev/mapper/nas',    'mount': '/mnt/nas'},
}

BROWSE_ROOTS = ['/mnt/backup', '/mnt/nas']

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr

def fmt_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M')

def get_smart(dev):
    try:
        r = subprocess.run(['sudo', 'smartctl', '-H', '-A', dev],
                           capture_output=True, text=True, timeout=5)
        health = 'OK' if 'PASSED' in r.stdout else ('FEHLER' if 'FAILED' in r.stdout else '?')
        temp = None
        for line in r.stdout.splitlines():
            if 'Temperature_Celsius' in line or 'Temperature' in line:
                parts = line.split()
                if len(parts) >= 10:
                    try:
                        temp = int(parts[9])
                    except ValueError:
                        pass
        return {'health': health, 'temp': temp}
    except Exception:
        return None

def get_device_status():
    status = {}
    for name, info in DEVICES.items():
        mounted = os.path.ismount(info['mount'])
        disk = None
        if mounted:
            try:
                total, used, free = shutil.disk_usage(info['mount'])
                pct = int(used / total * 100)
                disk = {
                    'total': fmt_size(total),
                    'used':  fmt_size(used),
                    'free':  fmt_size(free),
                    'pct':   pct,
                }
            except Exception:
                pass
        smart = get_smart(info['dev']) if mounted else None
        status[name] = {**info, 'mounted': mounted, 'disk': disk, 'smart': smart}
    return status

def safe_path(path):
    path = os.path.realpath(path)
    for root in BROWSE_ROOTS:
        if path == root or path.startswith(root + '/'):
            return path
    return None

def list_dir(path):
    entries = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
                is_dir = os.path.isdir(full)
                entries.append({
                    'name':   name,
                    'path':   full,
                    'is_dir': is_dir,
                    'size':   fmt_size(st.st_size) if not is_dir else '',
                    'mtime':  fmt_time(st.st_mtime),
                })
            except PermissionError:
                entries.append({'name': name, 'path': full, 'is_dir': False,
                                'size': '—', 'mtime': '—'})
    except PermissionError:
        pass
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    return entries

# ── Routen ───────────────────────────────────────────────────────────────────

def logged_in():
    return session.get('logged_in', False)

def render(tab='home', error=None, success=None,
           devices=None, mounted=True, entries=None,
           breadcrumbs=None, parent=None):
    d = devices or {}
    all_m = all(x['mounted'] for x in d.values()) if d else False
    any_m = any(x['mounted'] for x in d.values()) if d else False
    return render_template('index.html',
        logged_in=True, username=session.get('username',''),
        tab=tab, devices=d, all_mounted=all_m, any_mounted=any_m,
        error=error, success=success,
        mounted=mounted, entries=entries or [],
        breadcrumbs=breadcrumbs or [], parent=parent,
        log_entries=get_log())

@app.route('/')
def index():
    if not logged_in():
        return render_template('index.html', logged_in=False, error=None)
    return render(tab='home', devices=get_device_status())

@app.route('/login', methods=['POST'])
def login():
    u = request.form.get('username','')
    pw = request.form.get('password','')
    if pam.pam().authenticate(u, pw):
        session['logged_in'] = True
        session['username'] = u
        return redirect(url_for('index'))
    return render_template('index.html', logged_in=False,
                           error='Ungültige Anmeldedaten')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/unlock', methods=['POST'])
def unlock():
    if not logged_in(): return redirect(url_for('index'))
    pp = request.form.get('passphrase','')
    errors = []
    for name, info in DEVICES.items():
        if not os.path.ismount(info['mount']):
            log(f"{name}: cryptsetup open {info['dev']} ...")
            r = subprocess.run(['sudo','cryptsetup','open',info['dev'],name],
                               input=pp, capture_output=True, text=True)
            if r.returncode != 0:
                msg = f"{name}: {r.stderr.strip()}"
                log(msg, 'error')
                errors.append(msg); continue
            log(f"{name}: cryptsetup open OK")
            log(f"{name}: mount {info['mapper']} -> {info['mount']} ...")
            ok, err = run_cmd(['sudo','mount',info['mapper'],info['mount']])
            if not ok:
                msg = f"{name} mount: {err.strip()}"
                log(msg, 'error')
                errors.append(msg)
            else:
                log(f"{name}: mount OK")
        else:
            log(f"{name}: bereits eingehängt, übersprungen")
    d = get_device_status()
    return render(tab='home', devices=d,
                  error=' | '.join(errors) if errors else None,
                  success='Alle Laufwerke erfolgreich eingehängt.' if not errors else None)

@app.route('/lock', methods=['POST'])
def lock():
    if not logged_in(): return redirect(url_for('index'))
    errors = []
    for name, info in DEVICES.items():
        if os.path.ismount(info['mount']):
            log(f"{name}: umount {info['mount']} ...")
            ok, err = run_cmd(['sudo','umount',info['mount']])
            if not ok:
                msg = f"{name}: umount fehlgeschlagen – {err.strip()}"
                log(msg, 'error')
                errors.append(msg)
                continue
            log(f"{name}: umount OK")
        log(f"{name}: cryptsetup close ...")
        ok, err = run_cmd(['sudo','cryptsetup','close',name])
        if not ok:
            if 'not active' not in err.lower():
                msg = f"{name}: close fehlgeschlagen – {err.strip()}"
                log(msg, 'error')
                errors.append(msg)
            else:
                log(f"{name}: bereits geschlossen")
        else:
            log(f"{name}: close OK")
    d = get_device_status()
    return render(tab='home', devices=d,
                  error=' | '.join(errors) if errors else None,
                  success='Alle Laufwerke gesperrt.' if not errors else None)

@app.route('/browse/<path:subpath>')
def browse(subpath):
    if not logged_in(): return redirect(url_for('index'))
    full = '/' + subpath
    safe = safe_path(full)
    if not safe: abort(403)

    tab = 'backup' if safe.startswith('/mnt/backup') else 'nas'
    mnt = os.path.ismount('/mnt/' + tab)

    parts = safe.strip('/').split('/')
    crumbs = [{'name': p, 'path': '/'.join(parts[:i+1])}
              for i, p in enumerate(parts)]

    parent = None
    pp = os.path.dirname(safe)
    if safe_path(pp) and pp != safe:
        parent = pp.lstrip('/')

    entries = list_dir(safe) if mnt and os.path.isdir(safe) else []
    return render(tab=tab, devices={},
                  mounted=mnt, entries=entries,
                  breadcrumbs=crumbs, parent=parent)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
