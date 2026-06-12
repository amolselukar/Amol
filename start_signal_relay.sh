#!/bin/bash
# Launches the ORION->Vishal signal relay (no-op unless ~/Amol/relay_enabled exists)
nohup python3 -u /home/selukar_amol123/Amol/signal_relay.py >> /home/selukar_amol123/relay.log 2>&1 &
