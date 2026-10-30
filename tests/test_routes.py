import tempfile
import unittest
from pathlib import Path


from controller.core import (
    RouteRequestError,
    make_route_request,
    validate_route_ack,
    validate_route_request,
    read_route_request_file,
)


class RouteTests(unittest.TestCase):
    def test_route_request_by_name_and_path(self):
        by_name = validate_route_request({"id": 4, "route": "P1_1-2-4-6", "ignored": True})
        self.assertEqual(by_name, {"id": 4, "route": "P1_1-2-4-6", "path": [1, 2, 4, 6]})
        by_path = make_route_request(5, [1, 3, 4, 6])
        self.assertEqual(by_path["route"], "P3_1-3-4-6")
        self.assertEqual(validate_route_ack(by_path, by_path), by_path)

    def test_route_request_file_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route_request.json"
            path.write_text('{"id": 9, "route": "P2_1-2-5-6"}', encoding="utf-8")
            self.assertEqual(read_route_request_file(path)["path"], [1, 2, 5, 6])
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(RouteRequestError):
                read_route_request_file(path)

    def test_route_request_rejects_bad_input(self):
        for request in (
            {},
            {"id": 0, "path": [1, 2, 4, 6]},
            {"id": True, "path": [1, 2, 4, 6]},
            {"id": 1, "path": [1, 2, 6]},
            {"id": 1, "route": "not-configured"},
        ):
            with self.assertRaises(RouteRequestError):
                validate_route_request(request)
        with self.assertRaises(RouteRequestError):
            validate_route_ack(
                {"id": 2, "path": [1, 2, 4, 6]},
                {"id": 1, "path": [1, 2, 4, 6]},
            )


if __name__ == "__main__":
    unittest.main()
