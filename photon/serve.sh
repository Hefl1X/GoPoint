#!/bin/sh
# Запуск сервера поиска на готовой базе (/data/photon_data).
set -eu
if [ ! -d /data/photon_data ]; then
  echo "База поиска не собрана. Запустите: bash scripts/build-photon-db.sh" >&2
  exit 1
fi
exec java ${PHOTON_JAVA_OPTS:--Xmx1g} -jar /opt/photon.jar serve \
  -data-dir /data -listen-ip 0.0.0.0 -listen-port 2322 -max-results 20 -max-reverse-results 5
