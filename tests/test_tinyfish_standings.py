import unittest

from app.archive.tinyfish_standings import parse_standings_html


class ParseStandingsHtmlTests(unittest.TestCase):
    def test_extracts_structured_table_and_source(self):
        rows = "".join(
            f"<tr><td>{i}</td><td>{team}</td><td>10</td><td>7</td>"
            f"<td>2</td><td>1</td><td>21</td><td>8</td><td>+13</td><td>23</td></tr>"
            for i, team in enumerate(
                ["Arsenal", "Liverpool", "Chelsea", "City", "United", "Spurs"], start=1
            )
        )
        html = f"""
        <html><body><table>
          <thead><tr><th>Pos</th><th>Team</th><th>P</th><th>W</th>
          <th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></body></html>
        """
        result = parse_standings_html(
            html,
            source_url="https://www.espn.com/soccer/standings",
            source_title="Premier League Table",
            league_id=39,
            league_name="Premier League",
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(result["rows"][0]["team"], "Arsenal")
        self.assertEqual(result["rows"][0]["points"], 23)
        self.assertEqual(result["rows"][0]["goal_difference"], 13)
        self.assertEqual(result["source_url"], "https://www.espn.com/soccer/standings")
        self.assertTrue(result["verified_structure"])

    def test_rejects_short_or_unrelated_tables(self):
        html = """
        <table><tr><th>Team</th><th>P</th><th>Pts</th></tr>
        <tr><td>Arsenal</td><td>10</td><td>23</td></tr>
        <tr><td>Liverpool</td><td>10</td><td>22</td></tr></table>
        """
        result = parse_standings_html(
            html,
            source_url="https://www.espn.com/soccer/standings",
            source_title="Partial table",
            league_id=39,
            league_name="Premier League",
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
