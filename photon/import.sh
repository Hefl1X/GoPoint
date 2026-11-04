#!/bin/sh
# Сборка базы: распаковать выгрузку, оставить только прямоугольник города, загрузить в Photon.
# Аргументы: путь к выгрузке *.jsonl.zst и границы юг,запад,север,восток.
set -eu
dump="$1"
bbox="$2"
rm -rf /data/photon_data
zstd -dc "$dump" \
  | python3 /opt/extract_city.py --bbox "$bbox" \
  | java ${PHOTON_JAVA_OPTS:--Xmx2g} -jar /opt/photon.jar import \
      -data-dir /data -import-file - -languages ru,en -country-codes ru
echo "База поиска собрана: /data/photon_data"
