from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from backend.app.services.project_catalog.game_poster_page_identity import has_project_identity, project_artwork_links


class ProjectNamePresentationTests(unittest.TestCase):
    def test_complete_project_spelling_survives_slug_camelcase_and_display_punctuation(self):
        for text, name in [
            ("DOOM Retro · The classic, refined DOOM source port", "doomretro"),
            ("NSMB: Mario vs. Luigi Online Screenshots & Trailers", "nsmb-mariovsluigi"),
            ("GitHub - owner/SpaceStation14: official project", "space-station-14"),
            ("Open RA — official project", "OpenRA"),
            ("DOOM Retro v6.3", "DoomRetro"),
            ("ＦｒｅｅＤｏｏｍ screenshots", "free-doom"),
            ("Café-Game screenshots", "CaféGame"),
        ]:
            with self.subTest(text=text, name=name):
                self.assertTrue(has_project_identity(text, name))

    def test_project_boundaries_and_numbers_cannot_turn_another_project_into_a_match(self):
        for text, name in [
            ("SuperOpenRA", "OpenRA"),
            ("OpenRacing", "OpenRA"),
            ("OpenRAPlus", "OpenRA"),
            ("Other-OpenRA", "OpenRA"),
            ("OpenRA-fork", "OpenRA"),
            ("OpenRA_shy-edition", "OpenRA"),
            ("NSMB-MarioVsLuigi-ShySanctuaryEdition", "nsmb-mariovsluigi"),
            ("NSMB: Luigi vs. Mario", "nsmb-mariovsluigi"),
            ("OpenRA2", "OpenRA"),
            ("OpenRA 2 screenshots", "OpenRA"),
            ("OpenRA II screenshots", "OpenRA"),
            ("OpenRA XI screenshots", "OpenRA"),
            ("Space Station 13", "SpaceStation14"),
            ("Space Station", "SpaceStation14"),
            ("Space Station 1.4", "SpaceStation14"),
            ("Project 12", "Project1.2"),
            ("Project 1.2", "Project12"),
            ("Quake", "LibreQuake"),
            ("Red Alert", "OpenRA"),
            ("DOOM", "UZDoom"),
            ("MyGame", ""),
            ("", "MyGame"),
            ("anything", "---"),
            ("anything", None),
        ]:
            with self.subTest(text=text, name=name):
                self.assertFalse(has_project_identity(text, name))

    def test_a_rejected_occurrence_does_not_hide_a_later_complete_project_name(self):
        self.assertTrue(has_project_identity("OpenRA-fork compared with Open RA", "openra"))


class ProjectArtworkLinksTests(unittest.TestCase):
    @staticmethod
    def links(html, source="https://www.doomretro.com/", repo="bradharding/doomretro", name="doomretro"):
        return project_artwork_links(BeautifulSoup(html, "html.parser"), source, repo, name)

    def test_real_doomretro_homepage_evidence_follows_only_its_own_wiki(self):
        html = """
          <a href="https://github.com/bradharding/doomretro/wiki/">¥ DOOM Retro Wiki</a>
          <a href="https://doomwiki.org/wiki/ID24">ID24</a>
          <a href="https://github.com/bradharding/doomretro/wiki/License">License</a>
          <a href="https://github.com/someone/doomretro/wiki">DOOM Retro Wiki</a>
        """
        self.assertEqual(self.links(html), [
            {"url": "https://github.com/bradharding/doomretro/wiki/", "title": "¥ DOOM Retro Wiki"},
            {"url": "https://github.com/bradharding/doomretro/wiki/License", "title": "License"},
        ])

    def test_real_nsmb_readme_itch_link_is_recovered_without_a_game_specific_mapping(self):
        html = """
          <a href="https://ipodtouch0218.itch.io/nsmb-mariovsluigi">Play now in browser on itch.io!</a>
          <a href="https://ipodtouch0218.itch.io/">Other games</a>
          <a href="https://itch.io/games/tag-mario">Mario games</a>
        """
        self.assertEqual(self.links(html, "https://github.com/ipodtouch0218/NSMB-MarioVsLuigi", "ipodtouch0218/nsmb-mariovsluigi", "NSMB-MarioVsLuigi"), [
            {"url": "https://ipodtouch0218.itch.io/nsmb-mariovsluigi", "title": "Play now in browser on itch.io!"},
        ])

    def test_visible_project_evidence_is_required_for_an_itch_game_with_a_different_slug(self):
        html = """
          <a href="https://example-author.itch.io/play" title="Example Project">Play</a>
          <a href="https://example-author.itch.io/other-game">Unrelated game</a>
          <a href="https://other.example/ExampleProject">Example Project</a>
        """
        self.assertEqual(self.links(html, "https://github.com/demo/ExampleProject", "demo/exampleproject", "ExampleProject"), [
            {"url": "https://example-author.itch.io/play", "title": "Play"},
        ])

    def test_relative_links_are_resolved_deduplicated_and_bounded(self):
        html = """
          <a href="/BradHarding/DOOMRetro/wiki#Screenshots">Wiki</a>
          <a href="/BradHarding/DOOMRetro/wiki#Screenshots">Duplicate</a>
          <a href="/bradharding/doomretro/wiki/Images">Images</a>
          <a href="/bradharding/doomretro/wiki/Screenshots">Screenshots</a>
          <a href="/bradharding/doomretro/wiki/Fourth">Fourth</a>
        """
        links = self.links(html, "https://github.com/bradharding/doomretro")
        self.assertEqual(len(links), 3)
        self.assertEqual(links[0]["url"], "https://github.com/BradHarding/DOOMRetro/wiki")
        self.assertEqual(links[2]["title"], "Screenshots")

    def test_no_cross_project_paths_private_urls_or_itch_site_navigation(self):
        addresses = [
            "http://github.com/bradharding/doomretro/wiki",
            "https://user:secret@github.com/bradharding/doomretro/wiki",
            "https://github.com:443/bradharding/doomretro/wiki",
            "https://github.com.evil.example/bradharding/doomretro/wiki",
            "https://github.com/bradharding/doomretro/wiki-other",
            "https://github.com/bradharding/doomretro/wiki/../../other",
            "https://github.com/bradharding/doomretro/wiki/%2e%2e/other",
            "https://github.com/bradharding/doomretro-fork/wiki",
            "https://localhost/doomretro", "https://192.168.1.2/doomretro",
            "https://itch.io/login", "https://www.itch.io/doomretro",
            "https://author.itch.io/doomretro/devlog/123",
            "https://author.itch.io/doomretro-fork",
            "https://author.itch.io/", "https://author.itch.io.evil.example/doomretro",
            "javascript:alert(1)", "data:text/html,doomretro",
        ]
        for address in addresses:
            with self.subTest(address=address):
                self.assertEqual(self.links(f'<a href="{address}">Open</a>'), [])
        self.assertEqual(self.links('<a href="https://author.itch.io/quake">Quake</a>', repo="team/librequake", name="LibreQuake"), [])

    def test_invalid_source_or_repository_and_absent_evidence_return_no_invented_urls(self):
        html = '<a href="https://github.com/bradharding/doomretro/wiki">Wiki</a>'
        self.assertEqual(self.links(html, source="http://example.com"), [])
        self.assertEqual(self.links(html, repo="https://github.com/bradharding/doomretro"), [])
        self.assertEqual(self.links("<p>There should be screenshots on the project wiki.</p>"), [])
