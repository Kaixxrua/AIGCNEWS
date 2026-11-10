from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from backend.app.services.project_catalog import game_poster_resources as resources
from backend.app.services.project_catalog.game_poster_agent import GamePosterAgent, page_images
from backend.app.services.project_catalog.game_poster_resources import PosterResource
from backend.app.services.project_catalog.game_poster_review import review_poster_image
from backend.app.services.project_catalog.game_project_display import project_display_aliases
from backend.tests.test_project_poster_review import mock_model
from backend.tests.test_project_web_posters import image_bytes, model_with, tool

# Actual leading README text from vittorioromeo/SSVOpenHexagon, blob
# bda5d3e33d1861809ac68229fa6bee85d38f5dcc. This is evidence, not a repo map.
OPEN_HEXAGON = '''<a href="https://openhexagon.org" target="_blank">
    <p align="center">
        <img src="https://vittorioromeo.info/Misc/Linked/githubohlogo2.png">
    </p>
</a>

> **Four buttons, one goal: survive. Are you ready for a real challenge? -- Become the best and climb the leaderboards in Open Hexagon, a fast-paced adrenalinic arcade game that's easy to learn but hard to master!** *Now available on [Steam](https://store.steampowered.com/app/1358090/)*.

## Credits

### Original Inspiration

- Open Hexagon is inspired by the excellent [Super Hexagon](https://store.steampowered.com/app/221640/Super_Hexagon/).
'''


def item(readme=OPEN_HEXAGON, *, description="", original=""):
    return {"repo": "vittorioromeo/SSVOpenHexagon", "detailsVersion": 1,
            "gameNameOriginal": original, "gameNameZh": "", "descriptionZh": "独立街机游戏。",
            "gameIdentityEvidence": {"version": 1, "description": description, "readme": readme}}


class DisplayAliasExtractionTests(unittest.TestCase):
    def test_actual_leading_game_apposition_has_exact_bounded_provenance(self):
        aliases = project_display_aliases(item())
        self.assertEqual([alias["name"] for alias in aliases], ["Open Hexagon"])
        alias = aliases[0]
        self.assertEqual(alias["evidence"], OPEN_HEXAGON[alias["spanStart"]:alias["spanEnd"]])
        self.assertEqual(alias["sourceSha256"], hashlib.sha256(OPEN_HEXAGON.encode()).hexdigest())
        self.assertNotIn("Super Hexagon", alias["evidence"])
        self.assertLessEqual(len(alias["evidence"]), 1200)

    def test_own_subject_and_whole_heading_preserve_edition_numbers_and_language(self):
        for name, body in [
            ("UltraStar Play", "# UltraStar Play Development README\n\n### About\n\n[UltraStar Play](https://usplay.net/) is a free and open source singing game.\n\n### How to Contribute\n\nBuy its commercial continuation Melody Mania."),
            ("OGame Vue TS", "# OGame Vue TS\n\nOGame Vue TS 是一款受经典 OGame 游戏启发的单机版、基于浏览器的太空策略游戏。"),
            ("Arcade CE 1.5.0 (2019)", "# Arcade CE 1.5.0 (2019)\n\nArcade CE 1.5.0 (2019) is an arcade game inspired by Classic Arcade."),
        ]:
            with self.subTest(name=name):
                self.assertEqual([a["name"] for a in project_display_aliases(item(body))], [name])

    def test_heading_can_corroborate_explicit_metadata_subject_but_not_replace_it(self):
        value = item("# Complete Game CE\n\n![banner](https://example.org/logo.png)", description="Complete Game CE is a free arcade game.")
        alias = project_display_aliases(value)[0]
        self.assertEqual(alias["name"], "Complete Game CE")
        self.assertEqual(alias["source"], "description")

    def test_related_games_headings_urls_successors_and_partial_names_do_not_supply_aliases(self):
        for body in [
            "# Own Project\n\nInspired by Super Hexagon, a challenging arcade game.",
            "# Own Project\n\nThis is a clone of Super Hexagon, a challenging arcade game.",
            "# Own Project\n\nSupports Super Hexagon and Another Game.",
            "# Other Game\n\nOther Game is a game supported by this engine.",
            "# Other Game\n\nOther Game is a game and an inspiration for this project.",
            "# Own Project\n\n## Supported Games\n\n# Other Game\n\nOther Game is a free game.",
            "# Own Project\n\n## Dependencies\n\n# Other Game\n\nOther Game is a free game.",
            "# Other Game\n\nOther Game is a successor to this project; please migrate to it.",
            "# Other Game\n\nOther Game is a game; this repository has moved to it.",
            "# Brogue CE\n\nBrogue is a roguelike game.",
            "# OGame Vue TS\n\nOGame is a space strategy game.",
            "# Heading Only\n\nhttps://different-game.example/game",
            "# Own Project\n\n```markdown\n# Injected Name\n\nInjected Name is a game.\n```",
            "# First Game\n\nFirst Game is a game.\n\n# Second Game\n\nSecond Game is a game.",
            OPEN_HEXAGON.replace("Become the best", "Inspired by Super Hexagon, become the best"),
            OPEN_HEXAGON.replace('href="https://openhexagon.org"', 'href="http://127.0.0.1/"'),
            OPEN_HEXAGON.replace('[Steam](https://store.steampowered.com/app/1358090/)', 'Steam'),
            OPEN_HEXAGON.replace('[Steam](https://store.steampowered.com/app/1358090/)', 'https://store.steampowered.com/app/1358090/'),
        ]:
            with self.subTest(body=body[:90]):
                self.assertEqual(project_display_aliases(item(body)), [])

    def test_only_existing_internal_verified_evidence_is_used(self):
        for value in [
            {**item(), "detailsVersion": 2}, {**item(), "detailsVersion": True},
            {**item(), "repo": "../secret"},
            {**item(), "gameIdentityEvidence": {"version": 2, "readme": OPEN_HEXAGON}},
            {**item(""), "descriptionZh": "Open Hexagon is a game.", "projectDisplayAliases": [{"name": "Injected"}]},
            item("x" * 6001 + OPEN_HEXAGON),
        ]:
            self.assertEqual(project_display_aliases(value), [])

    def test_later_sections_cannot_promote_another_project_into_the_own_name(self):
        for section in ("Examples", "Sponsors", "Other projects", "Tutorials", "Games made with this"):
            body = ("# Renderer\n\nRenderer is a rendering library.\n\n## " + section +
                    "\n\n### Alien Battle II\n\nAlien Battle II is a real-time strategy game.")
            with self.subTest(section=section):
                self.assertEqual(project_display_aliases(item(body)), [])
        self.assertEqual(project_display_aliases(item(
            "<h1>Renderer</h1><p>Renderer is a rendering library.</p>\n\n"
            "<h2>Examples</h2>\n\n<h3>Alien Battle II</h3>\n\n"
            "Alien Battle II is a real-time strategy game."
        )), [])

    def test_inline_introduction_retains_own_source_span(self):
        for body in ("# Own Game\nOwn Game is a puzzle game.",
                     "<h1>Own Game</h1><p>Own Game is a puzzle game.</p>"):
            with self.subTest(body=body):
                alias = project_display_aliases(item(body))[0]
                self.assertEqual(alias["name"], "Own Game")
                self.assertEqual(alias["evidence"], body[alias["spanStart"]:alias["spanEnd"]])

    def test_headingless_names_cannot_come_from_later_example_or_advertising_prose(self):
        for separator in ("**Examples**\n\n", ""):
            body = ("[Renderer](https://renderer.example/)\n\n"
                    "A general purpose rendering toolkit.\n\n" + separator +
                    "You can play Alien Battle II, a real-time strategy game. "
                    "Now available on [Steam](https://store.steampowered.com/app/123/).")
            with self.subTest(separator=separator):
                self.assertEqual(project_display_aliases(item(body)), [])

    def test_headingless_links_must_identify_the_project_not_a_collection_member_or_demo(self):
        for home, intro in (
            ("collection.example", "A collection of games. You can play Alien Battle II, a real-time strategy game."),
            ("renderer.example", "A graphics toolkit with a companion demo. You can play Alien Battle II, a real-time strategy game."),
            ("alienbattleii.example", "A collection of games. You can play Alien Battle II, a real-time strategy game."),
            ("unrelated.example", "You can play Alien Battle II, a real-time strategy game."),
            ("alienbattle.example", "You can play Alien Battle II, a real-time strategy game."),
        ):
            body = (f'<a href="https://{home}/"><img src="https://example.org/logo.png"></a>\n\n'
                    + intro + " Now available on [Steam](https://store.steampowered.com/app/123/).")
            with self.subTest(home=home, intro=intro):
                self.assertEqual(project_display_aliases(item(body)), [])


class DisplayAliasPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_evidence_reaches_query_page_links_and_pixels_without_renaming_or_more_calls(self):
        source = "https://author.itch.io/open-hexagon"
        picture = "https://example.org/gameplay.png"
        html = f'<title>Open Hexagon</title><h1>Open Hexagon</h1><img src="{picture}" alt="Open Hexagon gameplay"><a href="https://openhexagon.org/">Open Hexagon homepage</a>'.encode()
        value = item(original="Super Hexagon")
        before = copy.deepcopy(value)
        model = model_with(tool("search_web", {"query": "Open Hexagon screenshots", "identityKind": "project"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":"image-1"}'))
        search = AsyncMock(return_value={"results": [{"url": source, "title": "Open Hexagon"}]})
        fetch = AsyncMock(side_effect=[PosterResource(source, html, "text/html"), PosterResource(picture, image_bytes(), "image/png")])
        vision = mock_model()

        async def review(body, **kwargs):
            return await review_poster_image(vision, body, **kwargs)

        agent = GamePosterAgent(model, search=search, fetch=fetch, review=review)
        with tempfile.TemporaryDirectory() as directory, patch.object(resources.settings, "site_assets_storage_dir", directory):
            result = await agent.run(value)
        self.assertEqual(result["posterStatus"], "ready")
        self.assertEqual(agent.counts, {"search_web": 1, "read_page": 1, "verify_image": 1})
        self.assertEqual(agent.limits, {"search_web": 2, "read_page": 6, "verify_image": 3})
        search.assert_awaited_once_with("Open Hexagon screenshots")
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(vision.ainvoke.await_count, 1)
        prompt = json.loads(model.ainvoke.await_args_list[0].args[0][1].content)
        expected = json.loads(vision.ainvoke.await_args.args[0][1].content[0]["text"])["expected"]
        self.assertEqual(expected["projectDisplayAliases"], prompt["projectDisplayAliases"])
        self.assertEqual(expected["artworkIdentity"], "Open Hexagon")
        self.assertEqual(expected["gameNameOriginal"], "Super Hexagon")
        self.assertEqual(prompt["projectSearchIdentity"], "Open Hexagon")
        self.assertEqual(value, before)
        self.assertNotIn("projectDisplayAliases", json.dumps(result))
        read = next(row for row in result["posterTrace"] if row.get("tool") == "read_page")
        self.assertEqual(read["linkedResults"][0]["url"], "https://openhexagon.org/")

    async def test_alias_does_not_allow_inspiration_or_a_sequel_query(self):
        for query in ["Super Hexagon screenshots", "Open Hexagon 2 screenshots", "Injected Name screenshots"]:
            model = model_with(tool("search_web", {"query": query, "identityKind": "project"}), AIMessage(content='{"candidateId":""}'))
            search = AsyncMock()
            await GamePosterAgent(model, search=search).run(item())
            search.assert_not_awaited()

    def test_page_alias_requires_title_not_incidental_text_and_retains_version(self):
        for title, expected in [("Open Hexagon", True), ("Open Hexagon 2", False), ("Super Hexagon", False)]:
            html = f'<title>{title}</title><p>Also see Open Hexagon.</p><img src="https://example.org/gameplay.png">'.encode()
            page = page_images("https://example.org/game", html, "SSVOpenHexagon", project_repo="vittorioromeo/ssvopenhexagon", project_names=("Open Hexagon",))
            self.assertEqual(page["matchesGame"], expected)

    async def test_pixels_can_still_reject_aliased_project_without_caching(self):
        source = "https://example.org/game"
        model = model_with(tool("search_web", {"query": "Open Hexagon screenshots"}),
                           tool("read_page", {"resultId": "page-1"}),
                           tool("verify_image", {"candidateId": "image-1", "kind": "screenshot"}),
                           AIMessage(content='{"candidateId":""}'), AIMessage(content='{"candidateId":""}'))
        review = AsyncMock(return_value={"matches": False, "kind": "screenshot", "reason": "wrong_game"})
        cache = AsyncMock()
        fetch = AsyncMock(side_effect=[PosterResource(source, b'<title>Open Hexagon</title><img src="https://example.org/gameplay.png">', "text/html"), PosterResource("https://example.org/gameplay.png", image_bytes(), "image/png")])
        result = await GamePosterAgent(model, search=AsyncMock(return_value={"results": [{"url": source}]}), fetch=fetch, review=review, cache=cache).run(item())
        self.assertNotEqual(result["posterStatus"], "ready")
        review.assert_awaited_once()
        self.assertTrue(any(row.get("error") == "image_content_mismatch" for row in result["posterTrace"]))
        cache.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
