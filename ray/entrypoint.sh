#!/bin/bash

# Initialiser Ray
ray start --head --port=6380  --ray-client-server-port=10001  --dashboard-port=8265

# Afficher les logs de Ray
tail -f /tmp/ray/session_latest/logs/raylet.out
