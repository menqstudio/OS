import json
import pathlib
import unittest

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeDependencySchemaTests(unittest.TestCase):
    def test_sst_validates_against_its_own_record_schema(self):
        # The SST names its own schema in `record_schema`; that schema must actually
        # accept the file (it previously forbade the SST's own record_schema/policy keys
        # via additionalProperties:false, so it validated neither a record nor the file).
        sst = json.loads((ROOT / "config" / "runtime-dependencies.json").read_text(encoding="utf-8"))
        schema_rel = sst["record_schema"]
        schema = json.loads((ROOT / schema_rel).read_text(encoding="utf-8"))
        jsonschema.validate(sst, schema)  # raises on drift


if __name__ == "__main__":
    unittest.main()
