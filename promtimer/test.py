#!/usr/bin/env python3
#
# Copyright (c) 2020-Present Couchbase, Inc All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

import dashboard
import templating
from templating import Parameter


class TestTemplating(unittest.TestCase):

    def test_find_parameter_basic(self):
        self.assertEqual(templating.find_parameter("aa {bucket} bb", "bucket"), 3)
        self.assertEqual(templating.find_parameter("prefix {a} suffix {a}", "a"), 7)

    def test_find_parameter_with_start_idx(self):
        s = "x {a} y {a} z"
        first = templating.find_parameter(s, "a")
        self.assertEqual(first, 2)  # index of '{' before first 'a'
        second = templating.find_parameter(s, "a", start_idx=first + len("{a}"))
        self.assertEqual(second, 8)

    def test_find_parameter_escaped_double_brace(self):
        # '{{bucket}}' is treated as escaped and returns -1
        self.assertEqual(templating.find_parameter("{{bucket}}", "bucket"), -1)

    def test_find_parameter_not_found(self):
        self.assertEqual(templating.find_parameter("no params here", "bucket"), -1)

    def test_replace_parameter_multiple_and_missing(self):
        s = "x {a} y {a} z"
        self.assertEqual(templating.replace_parameter(s, "a", "A"), "x A y A z")
        # missing param leaves string unchanged
        self.assertEqual(templating.replace_parameter("nothing", "a", "A"), "nothing")

    def test_replace_parameter_keeps_escaped_only(self):
        s = "keep {{a}} only"
        self.assertEqual(templating.replace_parameter(s, "a", "X"), "keep {{a}} only")

    def test_replace_parameter_mixed_real_and_escaped(self):
        s = "first {a} then {{a}}"
        self.assertEqual(templating.replace_parameter(s, "a", "X"), "first X then {{a}}")

    def test_replace_map_multi_keys(self):
        s = "url {ds:name} and {ds:uid} in {bucket}"
        m = {"ds:name": "Prom", "ds:uid": "123", "bucket": "b1"}
        self.assertEqual(templating.replace(s, m), "url Prom and 123 in b1")


class TestParameterBasics(unittest.TestCase):
    def test_make_path(self):
        self.assertEqual(templating.Parameter.make_path("ds"), "ds")
        self.assertEqual(templating.Parameter.make_path("ds", "uid"), "ds:uid")

    def test_name_and_attributes(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        self.assertEqual(p1.name(), "bucket")
        self.assertEqual(p1.attributes(), [])
        self.assertEqual(p2.attributes(), ["name", "uid"])

    def test_all_paths(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        self.assertEqual(p1.all_paths(), ["bucket"])
        self.assertEqual(p2.all_paths(), ["ds:name", "ds:uid"])

    def test_get_path_value_map_attrless(self):
        p = templating.Parameter("bucket")
        self.assertEqual(p.get_path_value_map("b1"), {"bucket": "b1"})

    def test_get_path_value_map_with_attrs(self):
        p = templating.Parameter("ds", ["name", "uid"])
        v = {"name": "Prom", "uid": "123"}
        self.assertEqual(p.get_path_value_map(v), {"ds:name": "Prom", "ds:uid": "123"})

    def test_get_path_value_map_missing_key_raises(self):
        p = templating.Parameter("ds", ["name", "uid"])
        with self.assertRaises(KeyError):
            p.get_path_value_map({"name": "Prom"})  # missing uid

    def test_make_single_valued_value(self):
        self.assertEqual(templating.Parameter("bucket").make_single_valued_value("b1"), "b1")
        # For attributed parameters, value is duplicated for each attr (by design)
        dup = templating.Parameter("ds", ["name", "uid"]).make_single_valued_value("$node")
        self.assertEqual(dup, {"name": "$node", "uid": "$node"})

    def test_eq_hash_and_repr(self):
        a = templating.Parameter("bucket")
        b = templating.Parameter("bucket")
        c = templating.Parameter("ds", ["name"])
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        s = {a, b, c}
        self.assertEqual(len(s), 2)
        self.assertIn("ParameterType(", repr(a))

    def test_find_in_string(self):
        self.assertTrue(templating.Parameter("bucket").find_in_string("x {bucket} y"))
        self.assertTrue(templating.Parameter("ds", ["name", "uid"]).find_in_string("x {ds:uid} y"))
        self.assertFalse(templating.Parameter("none").find_in_string("x {bucket} y"))

    def test_find_params_in_string(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        plist = [(p1, ["b1"]), (p2, [{"name": "x", "uid": "y"}])]
        found = templating.Parameter.find_params_in_string("x {ds:uid} and {bucket} y", plist)
        self.assertEqual({p.name() for p, _ in found}, {"bucket", "ds"})

    def test_collect_replacements_and_replace_all(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        val = [(p1, "b1"), (p2, {"name": "Prom", "uid": "123"})]
        repl = templating.Parameter.collect_replacements(val)
        self.assertEqual(repl, {"bucket": "b1", "ds:name": "Prom", "ds:uid": "123"})
        s = "X {bucket} -> {ds:name}/{ds:uid}"
        self.assertEqual(templating.Parameter.replace_all(val, s), "X b1 -> Prom/123")

    def test_find_parameter_by_name(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        self.assertEqual(
            templating.Parameter.find_parameter_by_name("ds", [(p1, ["b1"]), (p2, ["x"])]),
            (p2, ["x"])
        )
        self.assertIsNone(templating.Parameter.find_parameter_by_name("nope", [(p1, ["b1"])]))


class TestCartesianProduct(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(templating.make_cartesian_product([]), [])

    def test_single_list(self):
        p = templating.Parameter("bucket")
        out = templating.make_cartesian_product([(p, ["b1", "b2"])])
        expected = [[(p, "b1")], [(p, "b2")]]
        self.assertEqual(out, expected)

    def test_two_lists(self):
        p1 = templating.Parameter("bucket")
        p2 = templating.Parameter("ds", ["name", "uid"])
        out = templating.make_cartesian_product([(p1, ["b1", "b2"]), (p2, ["x", "y"])])
        # Flatten for easier verification of count and unique combos
        flat = [tuple((a.name(), v) for a, v in row) for row in out]
        self.assertEqual(len(out), 4)
        self.assertIn((("bucket", "b1"), ("ds", "x")), flat)
        self.assertIn((("bucket", "b2"), ("ds", "y")), flat)

    def test_three_lists(self):
        param_values = [
            (Parameter('type1'), ['a', 'b', 'c']),
            (Parameter('type2'), ['1', '2', '3']),
            (Parameter('type3'), ['x', 'y']),
        ]
        result = templating.make_cartesian_product(param_values)
        self.assertEqual(len(result), 3 * 3 * 2, "Should have 18 combinations")
        for t1 in param_values[0][1]:
            for t2 in param_values[1][1]:
                for t3 in param_values[2][1]:
                    combination = [(param_values[0][0], t1),
                                   (param_values[1][0], t2),
                                   (param_values[2][0], t3)]
                    self.assertIn(combination, result)


class TestDashboard(unittest.TestCase):

    def test_substitute_templating_variables(self):
        db = {'templating':
                  {'list': [
                      {'name': 'x', 'type': 'datasource'}
                  ]}}
        dstype = Parameter('data-source', ['name', 'uid'])
        typed_values = [
            (dstype, [
                dstype.make_single_valued_value('a'),
                dstype.make_single_valued_value('b'),
            ]),
        ]
        params = dashboard.maybe_substitute_templating_variables(db, typed_values)
        self.assertEqual(len(params), 1, "Should have one parameter")
        self.assertEqual(params[0][0].name(), dstype.name(),
                         "Should have the correct parameter type name")
        self.assertEqual(params[0][1], [dstype.make_single_valued_value('$x')],
                         "Should have the correct parameter values")


if __name__ == "__main__":
    unittest.main(verbosity=2)
