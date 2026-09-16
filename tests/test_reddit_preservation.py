import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.scraping_agents import reddit_scraper


class RedditPreservationTests(unittest.TestCase):
    def test_successful_requests_with_zero_usable_posts_preserve_main_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "scraped_reddit.json"
            partial = root / "partial.json"
            original = b'[{"url":"old","text":"retained corpus"}]'
            output.write_bytes(original)

            def successful_empty(_subreddit, _keyword, metrics, limit=25):
                metrics["attempted_requests"] += 1
                metrics["successful_requests"] += 1
                return []

            def capture_metrics(_label, metrics):
                return dict(metrics)

            with patch.object(reddit_scraper, "OUTPUT_PATH", str(output)), \
                 patch.object(reddit_scraper, "PARTIAL_OUTPUT_PATH", str(partial)), \
                 patch.object(reddit_scraper, "SUBREDDITS", ["Eltern"]), \
                 patch.object(reddit_scraper, "get_effective_keywords", return_value=["Elterngeld"]), \
                 patch.object(reddit_scraper, "search_subreddit", side_effect=successful_empty), \
                 patch.object(reddit_scraper, "save_reddit_metrics", side_effect=capture_metrics), \
                 patch.object(reddit_scraper.time, "sleep", return_value=None):
                reddit_scraper.run()

            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(partial.exists())


if __name__ == "__main__":
    unittest.main()
