# Улицы для OpenTripPlanner

Сюда `scripts/build-otp-graph.sh` скачивает выгрузку OpenStreetMap по Сибирскому округу
(`siberian-fed-district.osm.pbf`, ~590 МБ) и, с флагом `--with-dem`, файлы рельефа Copernicus.
Файлы большие и в git не попадают. Вырезанный город и граф лежат в `data/otp/`.
