#!/usr/bin/env python3
"""
signal_relay.py — runs on Amol's VM. Tails ~/orion_run.log for ORION's
ENTRY:/EXIT: lines and pushes them as JSON to Vishal's VM over SSH
(appends to ~/orion_signals/incoming.jsonl there).

Decoupled from the bot: reads the log only — a relay crash cannot affect
trading. If SSH is down, signals spool to .relay_spool.jsonl and are
flushed when connectivity returns (executor still drops anything older
than its MAX_AGE_SECS, so late flushes can't fire stale trades).

Enabled only when ~/Amol/relay_enabled exists. Exits after 15:35 IST.
"""
import hashlib, json, os, re, subprocess, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

IST      = ZoneInfo("Asia/Kolkata")
HOME     = os.path.expanduser("~")
LOG      = os.path.join(HOME, "orion_run.log")
FLAG     = os.path.join(HOME, "Amol", "relay_enabled")
SPOOL    = os.path.join(HOME, "Amol", ".relay_spool.jsonl")
PIDF     = os.path.join(HOME, "Amol", ".relay.pid")
SSH_DEST = "gce-vishal"
REMOTE   = "~/orion_signals/incoming.jsonl"

RE_ENTRY = re.compile(r"^ENTRY: (?:NFO:)?(\S+) @ ([\d.]+)\s+engine=(\S+)")
RE_EXIT  = re.compile(r"^EXIT: (?:NFO:)?(\S+) @ ([\d.]+) reason=(\S+)")

def say(msg):
    print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] {msg}", flush=True)

def push(payload: str) -> bool:
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                            SSH_DEST, f"cat >> {REMOTE}"],
                           input=payload, text=True, timeout=15,
                           capture_output=True)
        return r.returncode == 0
    except Exception:
        return False

def flush_spool():
    if not os.path.exists(SPOOL) or os.path.getsize(SPOOL) == 0:
        return
    data = open(SPOOL).read()
    if push(data):
        open(SPOOL, "w").close()
        say(f"spool flushed ({data.count(chr(10))} signals)")

def main():
    if not os.path.exists(FLAG):
        say("relay_enabled flag absent — exiting (no-op)")
        return
    # singleton
    if os.path.exists(PIDF):
        try:
            os.kill(int(open(PIDF).read().strip()), 0)
            say("relay already running — exiting"); return
        except Exception:
            pass
    open(PIDF, "w").write(str(os.getpid()))

    say(f"relay up — tailing {LOG} -> {SSH_DEST}:{REMOTE}")
    proc = subprocess.Popen(["tail", "-n", "0", "-F", LOG],
                            stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            now = datetime.now(IST)
            if now.hour > 15 or (now.hour == 15 and now.minute >= 35):
                say("past 15:35 IST — relay exiting for the day"); break
            line = line.strip()
            m, typ = None, None
            mm = RE_ENTRY.match(line)
            if mm: m, typ, info = mm, "ENTRY", f"engine={mm.group(3)}"
            else:
                mm = RE_EXIT.match(line)
                if mm: m, typ, info = mm, "EXIT", f"reason={mm.group(3)}"
            if not m:
                continue
            sig = {"id": hashlib.sha1(f"{line}{time.time()}".encode()).hexdigest()[:16],
                   "ts": time.time(), "type": typ, "symbol": m.group(1),
                   "price": float(m.group(2)), "info": info}
            payload = json.dumps(sig) + "\n"
            say(f"signal: {typ} {sig['symbol']} @ {sig['price']} ({info})")
            flush_spool()
            if not push(payload):
                open(SPOOL, "a").write(payload)
                say("push failed — spooled")
    finally:
        proc.kill()
        try: os.remove(PIDF)
        except Exception: pass

if __name__ == "__main__":
    main()
