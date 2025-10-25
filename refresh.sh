#!/bin/bash
rm -f /home/phil/github/turo/init-data/init-complete 
docker stop $(docker ps -a -q)
docker rm $(docker ps -a -q)
docker volume prune -f
docker compose build
docker compose up --force-recreate