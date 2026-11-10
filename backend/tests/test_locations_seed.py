"""The LGD place lists, and that Import resolves a district against them rather than creating one."""

import os
import pathlib
import sys

import psycopg
import pytest
from psycopg.rows import dict_row

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root, for `seed`

from seed.locations_seed import read_rows, seed_locations

from app.ingest.geography import _STATES, qualifiers, resolve_location

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
NORTH_EAST = {"Arunachal Pradesh", "Assam", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura"}


class TestQualifiers:
    @pytest.mark.parametrize(
        ("name", "words"),
        [("BENGALURU URBAN", {"urban"}), ("Bangalore Rural", {"rural"}), ("EASTERN WEST KHASI HILLS", {"east", "west"}),
         ("KAMRUP METROPOLITAN", {"metro"}), ("DIBRUGARH", set())],
    )
    def test_the_words_that_tell_neighbours_apart(self, name, words):
        assert qualifiers(name) == words


class TestTheFiles:
    def test_counts(self):
        states, districts = read_rows()
        assert (len(states), len(districts)) == (36, 784)

    def test_state_names_are_the_ones_import_resolves_to(self):
        states, _ = read_rows()
        assert {name for _, name in states} == set(_STATES)

    def test_every_district_has_a_known_state_and_a_unique_code(self):
        states, districts = read_rows()
        codes = {code for code, _ in states}
        assert all(d.state_code in codes for d in districts)
        assert len({d.code for d in districts}) == len(districts)

    def test_no_state_has_two_districts_of_one_name(self):
        _, districts = read_rows()
        assert len({(d.state_code, d.name) for d in districts}) == len(districts)

    def test_the_north_east_is_complete(self):
        states, districts = read_rows()
        ne = {code for code, name in states if name in NORTH_EAST}
        assert len(ne) == 8
        assert sum(d.state_code in ne for d in districts) == 132


@pytest.mark.integration
class TestTheSeed:
    """Runs in a transaction that is rolled back, so the database is left as it was."""

    @pytest.fixture
    def cur(self):
        try:
            conn = psycopg.connect(DSN, connect_timeout=3)
        except psycopg.OperationalError:
            pytest.skip("compose Postgres not reachable on localhost:5433")
        try:
            yield conn.cursor()
        finally:
            conn.rollback()
            conn.close()

    def counts(self, cur):
        cur.execute("SELECT kind, count(*), count(lgd_code) FROM locations "
                    "WHERE kind IN ('state', 'district') GROUP BY 1")
        return {k: (n, c) for k, n, c in cur.fetchall()}

    def test_idempotent_and_every_place_has_a_code(self, cur):
        seed_locations(cur)
        first = self.counts(cur)
        seed_locations(cur)
        assert self.counts(cur) == first
        assert first == {"state": (36, 36), "district": (784, 784)}

    def test_a_code_less_spelling_gains_the_code_rather_than_a_twin(self, cur):
        seed_locations(cur)
        cur.execute("UPDATE locations SET lgd_code = NULL, name = 'RI-BHOI' WHERE kind = 'district' "
                    "AND lgd_code = '276' RETURNING id")
        (row_id,) = cur.fetchone()
        seed_locations(cur)
        cur.execute("SELECT id, name FROM locations WHERE kind = 'district' AND lgd_code = '276'")
        assert cur.fetchall() == [(row_id, "RI BHOI")]
        assert self.counts(cur)["district"] == (784, 784)


@pytest.mark.integration
class TestImportResolvesAgainstTheList:
    """Needs the LGD list loaded (make locations-seed); each test is rolled back."""

    @pytest.fixture
    async def conn(self):
        try:
            conn = await psycopg.AsyncConnection.connect(DSN, connect_timeout=3, row_factory=dict_row)
        except psycopg.OperationalError:
            pytest.skip("compose Postgres not reachable on localhost:5433")
        try:
            row = await (await conn.execute(
                "SELECT count(*) AS n FROM locations WHERE kind = 'district' AND lgd_code IS NOT NULL")).fetchone()
            if row["n"] < 784:
                pytest.skip("LGD districts not loaded: run make locations-seed")
            yield conn
        finally:
            await conn.rollback()
            await conn.close()

    @pytest.mark.parametrize(
        ("state", "printed", "name"),
        [
            ("Meghalaya", "Ri-Bhoi District", "RI BHOI"),
            ("Assam", "Kamrup Rural", "KAMRUP"),
            ("Assam", "Kamrup Metropolitan", "KAMRUP METRO"),
            ("Karnataka", "Bangalore", "BENGALURU URBAN"),
            ("Karnataka", "Bangalore Rural", "BENGALURU RURAL"),
            # An old name in one state is the official name in another, and wins there.
            ("Bihar", "Aurangabad", "AURANGABAD"),
            ("Maharashtra", "Aurangabad", "CHHATRAPATI SAMBHAJINAGAR"),
        ],
    )
    async def test_by_name_or_alias_with_no_note(self, conn, state, printed, name):
        district_id, note = await resolve_location(conn, state, printed)
        assert note is None
        assert await self.name(conn, district_id) == name

    @pytest.mark.parametrize(
        ("state", "printed", "name"),
        [
            ("Meghalaya", "RI-BOI", "RI BHOI"),
            ("Assam", "Dibrughar", "DIBRUGARH"),
            ("Nagaland", "Tuensaang", "TUENSANG"),
            ("Meghalaya", "West Garo", "WEST GARO HILLS"),
            ("Assam", "Kamrup Metropolitian", "KAMRUP METRO"),
        ],
    )
    async def test_a_clearly_closest_name_is_taken_and_said(self, conn, state, printed, name):
        district_id, note = await resolve_location(conn, state, printed)
        assert await self.name(conn, district_id) == name
        assert note and f"read as {name}" in note

    @pytest.mark.parametrize(
        ("state", "printed", "why"),
        [
            ("Meghalaya", "Khasi Hills", "East, West and South West all score alike"),
            ("Manipur", "Imphal", "Imphal East and Imphal West tie"),
            ("Assam", "Karbi Anglong East", "the closest, KARBI ANGLONG, lacks 'east'"),
            ("Assam", "Guwahati", "a city; nothing is close"),
        ],
    )
    async def test_anything_less_certain_is_held_for_a_person(self, conn, state, printed, why):
        count = "SELECT count(*) AS n FROM locations"
        before = (await (await conn.execute(count)).fetchone())["n"]
        district_id, reason = await resolve_location(conn, state, printed)
        assert district_id is None, why
        assert "a person picks one" in reason
        assert (await (await conn.execute(count)).fetchone())["n"] == before

    async def name(self, conn, district_id):
        row = await (await conn.execute("SELECT name FROM locations WHERE id = %s", (district_id,))).fetchone()
        return row["name"]
