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
#

from __future__ import annotations
from typing import Any


def find_parameter(string, parameter, start_idx=0):
    to_find = '{' + parameter + '}'
    idx = string.find(to_find, start_idx)
    if idx <= 0:
        return idx
    if string[idx - 1] == '{' and string[idx + len(to_find)] == '}':
        return -1
    return idx


def replace_parameter(string, to_find, to_replace):
    idx = find_parameter(string, to_find)
    if idx < 0:
        return string
    find_len = len(to_find)
    result = []
    prev_idx = 0
    while idx >= 0:
        result.append(string[prev_idx:idx])
        result.append(to_replace)
        prev_idx = idx + find_len + 2
        idx = find_parameter(string, to_find, prev_idx)
    result.append(string[prev_idx:])
    return ''.join(result)


def replace(string, replacement_map):
    for k, v in replacement_map.items():
        string = replace_parameter(string, k, v)
    return string


class Parameter:
    """
    Represents a placeholder string that will be substituted with potentially
    different values in a larger string. The larger string is called a template. The
    placeholder string is called a template parameter.

    For example, say there a number of bucket names that may get substituted
    in a template. The placeholder string may look as follows: {bucket}

    This is an example of an "attribute-less" template parameter. The values
    associated with this kind of template parameter are single-valued -- in this
    case strings.

    It is permitted for template parameters to be multi-valued, in which case the
    placeholder string may look like this: {data-source:name} or
    {data-source:uid} where the type of the template parameter is
    'data-source' and 'name' and 'uid' are attributes. In this case, the values
    associated with the parameter type are dictionaries, where the keys are the
    attributes (e.g., "name" and "uid").
    """
    def __init__(self, param_name: str, attributes: list[str] | None = None):
        self._name = param_name
        self._attrs = attributes[:] if attributes else []

    """
    A Parameter.Value is a tuple of a Parameter and a single value that should be
    compatible with that Parameter.
    """
    Value = tuple['Parameter', Any]

    """
    A Parameter.ValueList is a tuple of a Parameter and a list of values, each of
    which should be compatible with that Parameter.
    """
    ValueList = tuple['Parameter', list[Any]]

    @staticmethod
    def make_path(param_name: str, attribute: str | None = None) -> str:
        if attribute:
            return f'{param_name}:{attribute}'  # noqa E231
        return param_name

    def name(self):
        """
        Returns the name of this template parameter type.
        """
        return self._name

    def attributes(self) -> list[str]:
        """
        Returns all attributes for this template parameter or the empty list if this
        template parameter does not have attributes.
        """
        return self._attrs

    def all_paths(self) -> list[str]:
        """
        Returns all paths for this template parameter. A path is the string that this template parameter
        type will appear as in a template.

        For example, for an attribute-less template parameter named "bucket", the path is simply "bucket".
        For a template parameter named "data-source" with attributes "name" and "uid", the paths are
        "data-source:name" and "data-source:uid".
        """
        attrs = self.attributes()
        if attrs:
            return [f'{Parameter.make_path(self._name, p)}' for p in attrs]  # noqa E231
        return [self._name]

    def get_path_value_map(self, value: Any) -> dict[str, Any]:
        """
        Returns a map of path to value for the given value.

        For an attribute-less parameter, the map contains a single entry mapping the parameter name to
        the value. For a parameter with attributes, the map contains an entry for each attribute, mapping
        the full path (e.g., "data-source:name") to the corresponding value from the supplied value
        which should be a dictionary.
        """
        attrs = self.attributes()
        if attrs:
            return {f'{Parameter.make_path(self._name, p)}': value[p] for p in attrs}  # noqa E231
        return {self._name: value}

    def make_single_valued_value(self, value: Any) -> Any:
        """
        Converts the value to a single-valued representation if applicable.
        By default, returns the value as is.
        """
        attrs = self.attributes()
        if attrs:
            return {p: value for p in attrs}
        return value

    def __eq__(self, other):
        return isinstance(other, Parameter) and \
               (self._name == other._name) and \
               (self._attrs == other._attrs)

    def __hash__(self):
        return hash(self._name)

    def __repr__(self):
        return f'ParameterType({self._name})'

    def find_in_string(self, string: str) -> bool:
        for param_path in self.all_paths():
            if find_parameter(string, param_path) >= 0:
                return True
        return False

    @staticmethod
    def find_params_in_string(
            string: str,
            parameter_value_lists: list[Parameter.ValueList]) -> list[Parameter.ValueList]:
        result = []
        for param_value_list in parameter_value_lists:
            if param_value_list[0].find_in_string(string):
                result.append(param_value_list)
        return result

    @staticmethod
    def collect_replacements(param_values: list[Parameter.Value]) -> dict[str, Any]:
        result = {}
        for param_value in param_values:
            param = param_value[0]
            value = param_value[1]
            for k, v in param.get_path_value_map(value).items():
                result[k] = v
        return result

    @staticmethod
    def replace_all(param_values: list[Parameter.Value], string: str) -> str:
        replacements = Parameter.collect_replacements(param_values)
        return replace(string, replacements)

    @staticmethod
    def find_parameter_by_name(name: str,
                               parameter_list: list[tuple[Parameter, Any]]
                               ) -> tuple[Parameter, Any] | None:
        for p in parameter_list:
            if p[0].name() == name:
                return p
        return None


def make_cartesian_product(
        parameter_value_lists: list[Parameter.ValueList]
    ) -> list[list[Parameter.Value]]:
    """
    Returns the cartesian product of each parameter value in each list
    with all values in all other lists.

    E.g. When invoked with this argument:
        [(Parameter('p1'), ['a', 'b']),
         (Parameter('p2'), ['1', '2'])]
    this function will return:
        [[(Parameter('p1'), 'a'), (Parameter('p2'), '1')],
         [(Parameter('p1'), 'a'), (Parameter('p2'), '2')],
         [(Parameter('p1'), 'b'), (Parameter('p2'), '1')],
         [(Parameter('p1'), 'b'), (Parameter('p2'), '2')]]

    :param parameter_value_lists: the list of parameter values to create
           the cartesian product of
    :return: the cartesian product as a list of lists of Parameter.Value
    """
    if not parameter_value_lists:
        return []
    first_list = parameter_value_lists[0]
    first_param = first_list[0]
    first_values = first_list[1]
    rest = parameter_value_lists[1:]
    rest_combinations = make_cartesian_product(rest)
    result = []
    for value in first_values:
        head_value = [(first_param, value)]
        if not rest_combinations:
            result.append(head_value)
        else:
            for combination in rest_combinations:
                result.append(head_value + combination)
    return result
