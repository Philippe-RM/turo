#!/bin/bash

# Initialiser Ray
ray start --head --port=6380

# Afficher les logs de Ray
tail -f /tmp/ray/session_latest/logs/raylet.out
