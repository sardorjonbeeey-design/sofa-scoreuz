from app.football.news import parse_news_feed


def test_parse_news_feed_skips_invalid_items_and_limits_results():
    payload = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>Premier League update</title>
        <link>https://news.example.test/1</link>
        <source>Example Sport</source><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate>
      </item>
      <item><title>Missing link</title></item>
      <item><title>La Liga update</title>
        <link>https://news.example.test/2</link>
      </item>
    </channel></rss>"""

    items = parse_news_feed(payload, limit=1)

    assert len(items) == 1
    assert items[0].title == "Premier League update"
    assert items[0].source == "Example Sport"


def test_parse_news_feed_handles_invalid_xml():
    assert parse_news_feed("<rss><broken>") == ()
