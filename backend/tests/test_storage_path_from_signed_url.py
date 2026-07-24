from app.storage import path_from_signed_url


def test_extracts_path_from_signed_url():
    url = (
        "http://host.docker.internal:54321/storage/v1/object/sign/"
        "madhats-assets/canvas_front_ab12cd.png?token=eyJhbGciOi.abc.def"
    )
    assert path_from_signed_url(url) == "canvas_front_ab12cd.png"


def test_extracts_nested_path_and_ignores_query():
    url = (
        "https://proj.supabase.co/storage/v1/object/public/"
        "madhats-assets/sub/dir/logo.png?download=1"
    )
    assert path_from_signed_url(url) == "sub/dir/logo.png"


def test_returns_none_for_non_storage_url():
    assert path_from_signed_url("https://cdn.shopify.com/x/cap.jpg") is None
    assert path_from_signed_url("/media/abc") is None


def test_returns_none_for_empty():
    assert path_from_signed_url(None) is None
    assert path_from_signed_url("") is None
