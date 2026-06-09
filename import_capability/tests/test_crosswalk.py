import json
from pathlib import Path

from import_capability.crosswalk import write_crosswalk


FIXTURES = Path(__file__).parent / "fixtures" / "crosswalk"


def test_wordpress_processwire_crosswalk_maps_common_concepts(tmp_path):
    crosswalk = write_crosswalk(
        "wordpress",
        "processwire",
        FIXTURES / "wordpress_schema.json",
        tmp_path,
    )

    assert crosswalk["mappings"] == [
        {"source": "post", "target": "page/article"},
        {"source": "page", "target": "page"},
        {"source": "category", "target": "taxonomy"},
        {"source": "tag", "target": "taxonomy"},
        {"source": "media", "target": "asset"},
    ]
    assert crosswalk["unmapped_fields"] == [
        "custom_rating",
        "product",
        "product_brand",
    ]
    assert json.loads((tmp_path / "crosswalk.json").read_text(encoding="utf-8")) == crosswalk
