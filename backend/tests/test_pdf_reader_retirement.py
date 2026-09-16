def test_paper_pdf_storage_is_not_mounted_as_public_media():
    from backend.app.main import app

    assert "/api/media/papers" not in {getattr(route, "path", None) for route in app.routes}
