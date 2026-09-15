import pytest

from teslai.places import Place, distance_m, load_places_csv, match_place

HOME = Place("Home", "home", 39.0, -94.5, 60, id=1)
WORK = Place("Work", "work", 39.1, -94.6, 150, id=2)


def test_distance_matches_known_value():
    # One degree of latitude is about 111.2 km.
    assert distance_m(39.0, -94.5, 40.0, -94.5) == pytest.approx(111_195, rel=0.001)


def test_match_nearest_within_radius():
    near_home = {"latitude": 39.0003, "longitude": -94.5}  # ~33 m
    assert match_place(near_home, [HOME, WORK]) == HOME
    assert match_place({"latitude": 39.001, "longitude": -94.5}, [HOME]) is None  # ~111 m
    assert match_place(None, [HOME]) is None
    overlapping = Place("Driveway", "home", 39.0002, -94.5, 60, id=3)
    assert match_place({"latitude": 39.00018, "longitude": -94.5}, [HOME, overlapping]) == overlapping


def test_price_kind():
    assert HOME.price_kind() == "home"
    assert WORK.price_kind() == "public"
    assert Place("Garage", "free", 0, 0, 10).price_kind() == "free"


def test_csv_loader_validates(tmp_path):
    good = tmp_path / "places.csv"
    good.write_text("name,kind,latitude,longitude,radius_m\nHome,home,39,-94.5,60\nWork,work,39.1,-94.6,120\n")
    assert [p.name for p in load_places_csv(good)] == ["Home", "Work"]
    for body, msg in [
        ("name,kind,latitude\nHome,home,39\n", "missing columns"),
        ("name,kind,latitude,longitude,radius_m\nHome,castle,39,-94,60\n", "kind must be"),
        ("name,kind,latitude,longitude,radius_m\nHome,home,39,-94,60\nHome,home,39,-94,60\n", "duplicate"),
        ("name,kind,latitude,longitude,radius_m\nHome,home,95,-94,60\n", "out of range"),
        ("name,kind,latitude,longitude,radius_m\nHome,home,x,-94,60\n", "must be numbers"),
    ]:
        bad = tmp_path / "bad.csv"
        bad.write_text(body)
        with pytest.raises(ValueError, match=msg):
            load_places_csv(bad)
