from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingReader,
    BriefingWriter,
)
from backend.app.repositories.mysql_repo import MySQLRepository


class BriefingRepositoryContractTests(unittest.TestCase):
    def test_mysql_repository_exposes_content_contract(self) -> None:
        repository = MySQLRepository.__new__(MySQLRepository)

        contract: BriefingContentRepository = repository

        self.assertTrue(callable(contract.save_briefing))
        self.assertTrue(callable(contract.get_latest_briefing))
        self.assertTrue(callable(contract.get_briefing_by_date))
        self.assertTrue(callable(contract.list_briefings))

    def test_writer_spec_does_not_expose_reads(self) -> None:
        repository = MagicMock(spec=BriefingWriter)
        repository.save_briefing.return_value = 42

        self.assertEqual(repository.save_briefing("2026-07-22", "content"), 42)
        with self.assertRaises(AttributeError):
            repository.list_briefings()

    def test_reader_spec_does_not_expose_writes(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_latest_briefing.return_value = {"id": 42}
        repository.get_briefing_by_date.return_value = {"id": 42}
        repository.list_briefings.return_value = [{"id": 42}]

        self.assertEqual(repository.get_latest_briefing(), {"id": 42})
        self.assertEqual(repository.get_briefing_by_date("2026-07-22"), {"id": 42})
        self.assertEqual(repository.list_briefings(limit=7), [{"id": 42}])
        with self.assertRaises(AttributeError):
            repository.save_briefing("2026-07-22", "content")


if __name__ == "__main__":
    unittest.main()
