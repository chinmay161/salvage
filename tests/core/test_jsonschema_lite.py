import json
import os
import tempfile
import time
import unittest

from salvagekit.core import jsonschema_lite as js
from salvagekit.core.jsonschema_lite import Schema, SchemaError, UnsupportedSchema, load_schema


def errs(schema, instance, limit=50):
    return Schema(schema).errors(instance, limit)


class KeywordTests(unittest.TestCase):
    """Each keyword with a valid and an invalid instance."""

    def ok(self, schema, *instances):
        for inst in instances:
            with self.subTest(schema=schema, instance=inst):
                self.assertEqual(errs(schema, inst), [])

    def bad(self, schema, *instances):
        for inst in instances:
            with self.subTest(schema=schema, instance=inst):
                self.assertTrue(errs(schema, inst), "expected an error")

    def test_type(self):
        self.ok({"type": "null"}, None)
        self.bad({"type": "null"}, 0, False, "")
        self.ok({"type": "boolean"}, True, False)
        self.bad({"type": "boolean"}, 0, 1, None)
        self.ok({"type": "integer"}, 0, -5, 10 ** 30, 1.0, -2.0)
        self.bad({"type": "integer"}, True, False, 1.5, "1", float("inf"))
        self.ok({"type": "number"}, 0, 1.5, -3)
        self.bad({"type": "number"}, True, "1", None)
        self.ok({"type": "string"}, "", "x")
        self.bad({"type": "string"}, b"x", 1)
        self.ok({"type": "array"}, [], [1])
        self.bad({"type": "array"}, {}, "ab")
        self.ok({"type": "object"}, {}, {"a": 1})
        self.bad({"type": "object"}, [], None)
        self.ok({"type": ["string", "null"]}, "a", None)
        self.bad({"type": ["string", "null"]}, 1, False)

    def test_type_message(self):
        self.assertEqual(errs({"type": "integer"}, True), ["$: expected integer, got boolean"])

    def test_properties_required_additional(self):
        schema = {"type": "object", "properties": {"a": {"type": "integer"}},
                  "required": ["a"], "additionalProperties": False}
        self.ok(schema, {"a": 1})
        self.assertEqual(errs(schema, {}), ['$: required property "a" is missing'])
        self.assertEqual(errs(schema, {"a": 1, "b": 2}), ["$.b: additional property not allowed"])
        self.assertEqual(errs(schema, {"a": "x"}), ["$.a: expected integer, got string"])
        self.ok({"additionalProperties": {"type": "string"}}, {"x": "y"})
        self.bad({"additionalProperties": {"type": "string"}}, {"x": 1})
        self.ok({"properties": {"a": {"type": "string"}}}, {"b": 1}, [], 3)  # non-objects pass

    def test_items_and_prefix_items(self):
        self.ok({"items": {"type": "integer"}}, [], [1, 2], "not an array")
        self.assertEqual(errs({"items": {"type": "integer"}}, [1, "x"]),
                         ["$[1]: expected integer, got string"])
        pair = {"prefixItems": [{"type": "integer"}, {"type": "string"}], "items": False}
        self.ok(pair, [1, "a"], [1], [])
        self.bad(pair, ["a", "a"], [1, "a", None])
        self.ok({"prefixItems": [{"type": "integer"}], "items": {"type": "string"}}, [1, "a", "b"])
        self.bad({"prefixItems": [{"type": "integer"}], "items": {"type": "string"}}, [1, 2])

    def test_enum_and_const(self):
        self.ok({"enum": ["a", 1, None, [1, 2], {"k": True}]}, "a", 1, 1.0, None, [1, 2],
                {"k": True})
        self.bad({"enum": ["a", 1]}, "b", True, [1])
        self.bad({"enum": [True]}, 1)
        self.ok({"const": {"a": [1, 2]}}, {"a": [1.0, 2]})
        self.bad({"const": 0}, False)
        self.bad({"const": "x"}, "y")

    def test_numeric_bounds(self):
        self.ok({"minimum": 0, "maximum": 1}, 0, 1, 0.5, "strings are ignored", True)
        self.bad({"minimum": 0}, -1, -0.1)
        self.bad({"maximum": 1}, 1.01)
        self.ok({"exclusiveMinimum": 0, "exclusiveMaximum": 10}, 1, 9.99)
        self.bad({"exclusiveMinimum": 0}, 0)
        self.bad({"exclusiveMaximum": 10}, 10)

    def test_string_keywords(self):
        self.ok({"minLength": 2, "maxLength": 3}, "ab", "abc", "é漢", 5)
        self.bad({"minLength": 2}, "a")
        self.bad({"maxLength": 3}, "abcd")
        self.ok({"pattern": "^[0-9a-f]+$"}, "00ff")
        self.ok({"pattern": "b"}, "abc")   # re.search, not a full match
        self.bad({"pattern": "^[0-9a-f]+$"}, "00FF", "")

    def test_array_keywords(self):
        self.ok({"minItems": 1, "maxItems": 2}, [1], [1, 2], "x")
        self.bad({"minItems": 1}, [])
        self.bad({"maxItems": 2}, [1, 2, 3])
        self.ok({"uniqueItems": True}, [1, "1", True, None, [1], {"a": 1}], [])
        self.bad({"uniqueItems": True}, [1, 1.0], [{"a": 1, "b": 2}, {"b": 2, "a": 1}],
                 [[1], [1]])
        self.ok({"uniqueItems": False}, [1, 1])

    def test_combinators(self):
        any_of = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.ok(any_of, "a", 1)
        self.bad(any_of, None)
        one_of = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
        self.ok(one_of, -1, 0.5)
        self.bad(one_of, 1)        # matches both
        self.bad(one_of, -0.5)     # matches neither
        all_of = {"allOf": [{"type": "integer"}, {"minimum": 3}]}
        self.ok(all_of, 3)
        self.bad(all_of, 2, "x")
        self.ok({"not": {"type": "string"}}, 1)
        self.bad({"not": {"type": "string"}}, "x")

    def test_boolean_schemas(self):
        self.ok(True, 1, None, {"a": [1]})
        self.bad(False, 1, None)
        self.ok({"properties": {"x": True, "y": False}}, {"x": 1})
        self.bad({"properties": {"x": True, "y": False}}, {"y": 1})

    def test_annotations_ignored(self):
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "x",
                  "title": "t", "description": "d", "default": 5, "examples": [1],
                  "$comment": "c", "format": "email", "type": "string"}
        self.ok(schema, "not an email")


class RefTests(unittest.TestCase):
    def test_defs_and_definitions(self):
        schema = {"$defs": {"n": {"type": "integer"}},
                  "definitions": {"s": {"type": "string"}},
                  "properties": {"a": {"$ref": "#/$defs/n"}, "b": {"$ref": "#/definitions/s"}}}
        self.assertEqual(errs(schema, {"a": 1, "b": "x"}), [])
        self.assertEqual(errs(schema, {"a": "x", "b": 1}),
                         ["$.a: expected integer, got string", "$.b: expected string, got integer"])

    def test_ref_chain(self):
        schema = {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/c"},
                            "c": {"type": "integer", "minimum": 10}},
                  "$ref": "#/$defs/a"}
        self.assertEqual(errs(schema, 12), [])
        self.assertEqual(errs(schema, 5), ["$: 5 is less than minimum 10"])

    def test_recursive_ref(self):
        tree = {"$defs": {"node": {"type": "object", "additionalProperties": False,
                                   "properties": {"v": {"type": "integer"},
                                                  "kids": {"type": "array",
                                                           "items": {"$ref": "#/$defs/node"}}}}},
                "$ref": "#/$defs/node"}
        good = {"v": 1, "kids": [{"v": 2, "kids": [{"v": 3}]}]}
        self.assertEqual(errs(tree, good), [])
        bad = {"v": 1, "kids": [{"v": 2, "kids": [{"v": "3"}]}]}
        self.assertEqual(errs(tree, bad), ["$.kids[0].kids[0].v: expected integer, got string"])

    def test_ref_siblings_also_apply(self):
        schema = {"$defs": {"n": {"type": "integer"}}, "$ref": "#/$defs/n", "minimum": 5}
        self.assertEqual(errs(schema, 7), [])
        self.assertTrue(errs(schema, 3))

    def test_escaped_pointer(self):
        schema = {"$defs": {"a/b": {"type": "null"}}, "$ref": "#/$defs/a~1b"}
        self.assertEqual(errs(schema, None), [])

    def test_bad_refs_refused_at_load(self):
        with self.assertRaises(SchemaError) as cm:
            Schema({"$ref": "#/$defs/missing"})
        self.assertIn("unresolvable $ref", str(cm.exception))
        with self.assertRaises(UnsupportedSchema):
            Schema({"$ref": "other.json#/x"})
        with self.assertRaises(SchemaError) as cm:
            Schema({"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"allOf": [{"$ref": "#/$defs/a"}]}},
                    "$ref": "#/$defs/a"})
        self.assertIn("circular", str(cm.exception))


class LoadTests(unittest.TestCase):
    def test_unsupported_keywords_all_named_with_paths(self):
        schema = {"type": "object",
                  "properties": {"a": {"patternProperties": {}},
                                 "if": {"type": "string"}},   # a property NAMED "if" is fine
                  "items": [{"type": "string"}],
                  "$defs": {"x": {"exclusiveMinimum": True, "dependentRequired": {}}},
                  "if": {}}
        with self.assertRaises(UnsupportedSchema) as cm:
            Schema(schema)
        self.assertEqual(sorted(cm.exception.problems), sorted([
            "#/properties/a/patternProperties: patternProperties",
            "#/items: items (array form; use prefixItems)",
            "#/$defs/x/exclusiveMinimum: exclusiveMinimum (boolean form)",
            "#/$defs/x/dependentRequired: dependentRequired",
            "#/if: if",
        ]))
        self.assertIsInstance(cm.exception, SchemaError)

    def test_malformed_keywords(self):
        for schema in ({"type": "integr"}, {"required": "a"}, {"minLength": -1},
                       {"pattern": "("}, {"anyOf": []}, {"minimum": "0"},
                       {"properties": []}, {"uniqueItems": 1}, 5):
            with self.subTest(schema=schema):
                with self.assertRaises(SchemaError):
                    Schema(schema)

    def test_load_schema_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"type": "string"}, fh)
            schema = load_schema(path)
            self.assertEqual(schema.name, "s.json")
            self.assertTrue(schema.is_valid("x"))
            self.assertFalse(schema.is_valid(1))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with self.assertRaises(SchemaError):
                load_schema(path)
            with self.assertRaises(SchemaError):
                load_schema(os.path.join(tmp, "missing.json"))


class RobustnessTests(unittest.TestCase):
    def test_never_raises_on_odd_instances(self):
        schema = Schema({"type": "object", "properties": {"a": {"enum": [1]}},
                         "additionalProperties": {"uniqueItems": True}})
        cyclic: list = []
        cyclic.append(cyclic)
        for inst in (object(), {"a": {1, 2}}, {"b": [object(), object()]}, {1: 2},
                     {"a": float("nan")}, b"bytes", cyclic):
            with self.subTest(instance=repr(inst)[:40]):
                self.assertIsInstance(schema.errors(inst), list)

    def test_deep_nesting_is_an_error_not_a_crash(self):
        schema = Schema({"$defs": {"n": {"type": "array", "items": {"$ref": "#/$defs/n"}}},
                         "$ref": "#/$defs/n"})
        deep: list = []
        for _ in range(100_000):
            deep = [deep]
        got = schema.errors(deep)
        self.assertEqual(got, ["$: instance is nested too deeply to validate"])

    def test_limit(self):
        schema = Schema({"items": {"type": "string"}})
        self.assertEqual(len(schema.errors(list(range(500)))), 50)
        self.assertEqual(len(schema.errors(list(range(500)), limit=3)), 3)
        self.assertEqual(schema.errors(list(range(500)), limit=1),
                         ["$[0]: expected string, got integer"])

    def test_path_format(self):
        self.assertEqual(js._fmt_path(None), "$")
        self.assertEqual(js._fmt_path(((((None, "a"), 0), "b c"), "d")), '$.a[0]["b c"].d')


class SpeedTests(unittest.TestCase):
    def test_40000_record_output_under_2s(self):
        from salvagekit.core import validate
        record = {"v": "x" * 108, "n": 5, "flag": True, "verified": False,
                  "issues": ["crc_mismatch"]}
        doc = {"source_file": "big.t", "format": "T-BIG", "status": "partial",
               "metadata": {"k": 1},
               "records": [json.loads(json.dumps(record)) for _ in range(40_000)],
               "damage": [{"kind": "crc_mismatch", "offset": 0, "detail": "", "lossy": False}]}
        schema = validate.active("output").schema
        t0 = time.perf_counter()
        problems = schema.errors(doc)
        elapsed = time.perf_counter() - t0
        self.assertEqual(problems, [])
        self.assertLess(elapsed, 2.0, f"validation took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
