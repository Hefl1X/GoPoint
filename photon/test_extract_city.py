"""Тесты вырезания города из выгрузки Photon. Запуск: python3 -m unittest (в папке photon/)."""

import json
import unittest

from extract_city import extract, parse_box

NSK = parse_box("54.80,82.70,55.20,83.20")


def header(addresslines: bool) -> str:
    return json.dumps(
        {
            "type": "NominatimDumpFile",
            "content": {"version": "0.1.0", "features": {"has_addresslines": addresslines}},
        }
    )


def place(pid: str, lon: float, lat: float, **extra: object) -> str:
    item = {"place_id": pid, "centroid": [lon, lat], **extra}
    return json.dumps({"type": "Place", "content": [item]}, ensure_ascii=False)


def ids(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        record = json.loads(line)
        if record["type"] == "Place":
            out.append(record["content"][0]["place_id"])
    return out


class ExtractTest(unittest.TestCase):
    def test_keeps_city_drops_rest(self) -> None:
        lines = [
            header(False),
            json.dumps({"type": "CountryInfo", "content": []}),
            place("aura", 82.9366, 55.0287),
            place("akadem", 83.10, 54.84),
            place("moscow", 37.6, 55.75),
            place("tolmachevo", 82.65, 55.01),
        ]
        out = list(extract(lines, NSK))
        self.assertEqual(ids(out), ["aura", "akadem"])
        self.assertTrue(out[0].startswith('{"type": "NominatimDumpFile"'))
        self.assertEqual(json.loads(out[1])["type"], "CountryInfo")

    def test_region_kept_only_with_addresslines(self) -> None:
        oblast = place("oblast", 80.0, 55.5, address_type="state", bbox=[75.0, 53.3, 85.1, 57.2])
        far_area = place("far", 37.6, 55.7, address_type="city", bbox=[37, 55, 38, 56])
        self.assertEqual(ids(list(extract([header(True), oblast, far_area], NSK))), ["oblast"])
        self.assertEqual(ids(list(extract([header(False), oblast, far_area], NSK))), [])

    def test_house_is_not_area(self) -> None:
        house = place("h", 80.0, 55.5, rank_address=30, housenumber="1", bbox=[75, 53, 85, 57])
        self.assertEqual(ids(list(extract([header(True), house], NSK))), [])

    def test_empty_lines_and_newlines(self) -> None:
        out = list(extract(["", place("a", 82.92, 55.03)], NSK))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("\n"))

    def test_bad_box(self) -> None:
        with self.assertRaises(ValueError):
            parse_box("55.2,82.7,54.8,83.2")


if __name__ == "__main__":
    unittest.main()
