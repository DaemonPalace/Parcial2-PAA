"""Parser checks on real rows captured from the live sites on 2026-10-09.

Run: docker compose run --rm --no-deps ingestion python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

from flows.clean import clean_cars, clean_flights, clean_hotels, digits

FLIGHT = {
    "source": "google_flights", "origin": "BOG", "destination": "CTG", "day": "2026-10-20",
    "label": "A partir de 177805 pesos colombianos.El acceso al compartimento superior no está "
             "incluido en el precio. Vuelo directo de Wingo. Sale de Aeropuerto Internacional El "
             "Dorado el martes, octubre 20 a las 17:20. Llega a Aeropuerto Internacional Rafael "
             "Núñez el martes, octubre 20 a las 18:53. Duración total: 1 h 33 min.   Seleccionar vuelo",
}
HOTEL = {
    "source": "booking", "city": "CTG", "check_in": "2026-10-20", "check_out": "2026-10-23",
    "name": "The Clock Hostel & Suites", "price": "COP 125.760",
    "rating": "Puntuación: 8,1\n8,1\nMuy bien\n1.889 comentarios",
    "url": "https://www.booking.com/hotel/co/the-clock-hostel-amp-suites.es.html?aid=304142&label=x",
}
CAR = {
    "source": "booking_cars", "city": "CTG", "pickup_date": "2026-10-20", "dropoff_date": "2026-10-23",
    "vendor": "Alamo",
    "text": "Nissan March\nor similar small car\n5 seats\nManual\nPrice for 3 days:\nCOP 540,200\nFree cancellation",
}


class CleanTest(unittest.TestCase):
    def test_digits_handles_both_thousand_separators(self):
        self.assertEqual(digits("COP 2.759.760"), 2759760)
        self.assertEqual(digits("COP 540,200"), 540200)
        self.assertIsNone(digits(""))

    def test_flight_label(self):
        rows, rejected = clean_flights([FLIGHT])
        self.assertEqual(rejected, 0)
        f = rows[0]
        self.assertEqual((f["airline"], f["stops"], f["price_cop"], f["duration_minutes"]), ("Wingo", 0, 177805, 93))
        self.assertEqual(f["depart_at"].isoformat(), "2026-10-20T17:20:00-05:00")
        self.assertEqual(f["arrive_at"].isoformat(), "2026-10-20T18:53:00-05:00")

    def test_flight_label_with_non_breaking_spaces(self):
        label = FLIGHT["label"].replace("1 h 33 min", "1\u00a0h 33\u00a0min").replace("a las 17:20", "a las\u202f17:20")
        f = clean_flights([{**FLIGHT, "label": label}])[0][0]
        self.assertEqual((f["duration_minutes"], f["depart_at"].hour), (93, 17))

    def test_flight_with_stops(self):
        label = FLIGHT["label"].replace("Vuelo directo de Wingo", "Vuelo con 1 escala de Avianca")
        self.assertEqual(clean_flights([{**FLIGHT, "label": label}])[0][0]["stops"], 1)

    def test_garbage_is_rejected_not_loaded(self):
        self.assertEqual(clean_flights([{**FLIGHT, "label": "Seleccionar vuelo"}]), ([], 1))
        self.assertEqual(clean_hotels([{**HOTEL, "price": "COP 5"}]), ([], 1))   # out of bounds
        self.assertEqual(clean_cars([{**CAR, "vendor": None}]), ([], 1))

    def test_dedupe_keeps_cheapest(self):
        rows, _ = clean_flights([FLIGHT, {**FLIGHT, "label": FLIGHT["label"].replace("177805", "150000")}])
        self.assertEqual([r["price_cop"] for r in rows], [150000])

    def test_hotel(self):
        h = clean_hotels([HOTEL])[0][0]
        self.assertEqual((h["price_total_cop"], h["rating"], h["check_in"]), (125760, 8.1, date(2026, 10, 20)))
        self.assertEqual(h["url"], "https://www.booking.com/hotel/co/the-clock-hostel-amp-suites.es.html")

    def test_car(self):
        c = clean_cars([CAR])[0][0]
        self.assertEqual((c["model"], c["category"], c["price_total_cop"]), ("Nissan March", "small", 540200))


if __name__ == "__main__":
    unittest.main()
