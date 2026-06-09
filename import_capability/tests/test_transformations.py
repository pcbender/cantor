import json
from pathlib import Path

from import_capability.transformations import write_transformed_content


FIXTURES = Path(__file__).parent / "fixtures" / "transformations"


def test_transformation_rules_map_fields_and_record_missing_values(tmp_path):
    result = write_transformed_content(
        FIXTURES / "wordpress_content.json",
        [
            {"from": "title.rendered", "to": "title"},
            {"from": "content.rendered", "to": "body"},
        ],
        tmp_path,
    )

    assert result["pages"] == [
        {"id": 10, "title": "Example title", "body": "<p>Example body</p>"},
        {"id": 11, "title": "Missing body"},
    ]
    assert result["skipped"] == [
        {
            "id": 11,
            "from": "content.rendered",
            "to": "body",
            "reason": "missing source field",
        }
    ]
    assert json.loads(
        (tmp_path / "transformed_content.json").read_text(encoding="utf-8")
    ) == result
