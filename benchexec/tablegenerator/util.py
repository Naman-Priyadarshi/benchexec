# BenchExec is a framework for reliable benchmarking.
# This file is part of BenchExec.
#
# Copyright (C) 2007-2015  Dirk Beyer
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module contains some useful functions for Strings, Files and Lists.
"""

# prepare for Python 3
from __future__ import absolute_import, division, print_function, unicode_literals

from decimal import Decimal
import glob
import io
import json
import logging
import os
import re
from urllib.parse import quote as url_quote
import urllib.request
import tempita
import copy
from functools import reduce

import benchexec.util


def get_file_list(shortFile):
    """
    The function get_file_list expands a short filename to a sorted list
    of filenames. The short filename can contain variables and wildcards.
    """
    if "://" in shortFile:  # seems to be a URL
        return [shortFile]

    # expand tilde and variables
    expandedFile = os.path.expandvars(os.path.expanduser(shortFile))

    # expand wildcards
    fileList = glob.glob(expandedFile)

    # sort alphabetical,
    # if list is emtpy, sorting returns None, so better do not sort
    if len(fileList) != 0:
        fileList.sort()
    else:
        logging.warning("No file matches '%s'.", shortFile)

    return fileList


def extend_file_list(filelist):
    """
    This function takes a list of files, expands wildcards
    and returns a new list of files.
    """
    return [file for wildcardFile in filelist for file in get_file_list(wildcardFile)]


def make_url(path_or_url):
    """Make a URL from a string which is either a URL or a local path,
    by adding "file:" if necessary.
    """
    if not is_url(path_or_url):
        return "file:" + urllib.request.pathname2url(path_or_url)
    return path_or_url


def open_url_seekable(path_url, mode="rt"):
    """Open a URL and ensure that the result is seekable,
    copying it into a buffer if necessary."""

    logging.debug("Making request to '%s'", path_url)
    response = urllib.request.urlopen(path_url)
    logging.debug("Got response %s", response.info())

    try:
        response.seek(0)
    except (IOError, AttributeError):
        # Copy into buffer to allow seeking.
        response = io.BytesIO(response.read())
    if "b" in mode:
        return response
    else:
        return io.TextIOWrapper(response)


def split_number_and_unit(s):
    """
    Split a string into two parts: a number prefix and an arbitrary suffix.
    Splitting is done from the end, so the split is where the last digit
    in the string is (that means the prefix may include non-digit characters,
    if they are followed by at least one digit).
    """
    return split_string_at_suffix(s, False)


def split_string_at_suffix(s, numbers_into_suffix=False):
    """
    Split a string into two parts: a prefix and a suffix. Splitting is done from the end,
    so the split is done around the position of the last digit in the string
    (that means the prefix may include any character, mixing digits and chars).
    The flag 'numbers_into_suffix' determines whether the suffix consists of digits or non-digits.
    """
    if not s:
        return s, ""
    pos = len(s)
    while pos and numbers_into_suffix == s[pos - 1].isdigit():
        pos -= 1
    return s[:pos], s[pos:]


def remove_unit(s):
    """
    Remove a unit from a number string, or return the full string if it is not a number.
    """
    (prefix, suffix) = split_number_and_unit(s)
    return suffix if prefix == "" else prefix


def is_url(path_or_url):
    return "://" in path_or_url or path_or_url.startswith("file:")


def create_link(href, base_dir, runResult=None, href_base=None):
    def get_replacements(task_file):
        var_prefix = "taskdef_" if task_file.endswith(".yml") else "inputfile_"
        return [
            (var_prefix + "name", os.path.basename(task_file)),
            (var_prefix + "path", os.path.dirname(task_file) or "."),
            (var_prefix + "path_abs", os.path.dirname(os.path.abspath(task_file))),
        ] + (
            [
                ("logfile_name", os.path.basename(runResult.log_file)),
                (
                    "logfile_path",
                    os.path.dirname(
                        os.path.relpath(runResult.log_file, href_base or ".")
                    )
                    or ".",
                ),
                (
                    "logfile_path_abs",
                    os.path.dirname(os.path.abspath(runResult.log_file)),
                ),
            ]
            if runResult.log_file
            else []
        )

    source_file = (
        os.path.relpath(runResult.task_id[0], href_base or ".") if runResult else None
    )

    if is_url(href):
        # quote special characters only in inserted variable values, not full URL
        if source_file:
            source_file = url_quote(source_file)
            href = benchexec.util.substitute_vars(href, get_replacements(source_file))
        return href

    # quote special characters everywhere (but not twice in source_file!)
    if source_file:
        href = benchexec.util.substitute_vars(href, get_replacements(source_file))
    return url_quote(os.path.relpath(href, base_dir))


def format_options(options):
    """Helper function for formatting the content of the options line"""
    # split on one of the following tokens: ' -' or '[[' or ']]'
    lines = [""]
    for token in re.split(r"( -|\[\[|\]\])", options):
        if token in ["[[", "]]"]:
            lines.append(token)
            lines.append("")
        elif token == " -":
            lines.append(token)
        else:
            lines[-1] += token
    # join all non-empty lines and wrap them into 'span'-tags
    return (
        '<span style="display:block">'
        + '</span><span style="display:block">'.join(
            line for line in lines if line.strip()
        )
        + "</span>"
    )


def to_decimal(s):
    if s:
        if s.lower() in ["nan", "inf", "-inf"]:
            return Decimal(s)
        else:
            # remove whitespaces and trailing units (e.g., in '1.23s')
            s, _ = split_number_and_unit(s.strip())
            return Decimal(s) if s else None
    else:
        return None


def collapse_equal_values(values, counts):
    """
    Take a tuple (values, counts), remove consecutive values and increment their count instead.
    """
    assert len(values) == len(counts)
    previousValue = values[0]
    previousCount = 0

    for value, count in zip(values, counts):
        if value != previousValue:
            yield (previousValue, previousCount)
            previousCount = 0
            previousValue = value
        previousCount += count

    yield (previousValue, previousCount)


def get_column_value(sourcefileTag, columnTitle, default=None):
    for column in sourcefileTag.findall("column"):
        if column.get("title") == columnTitle:
            return column.get("value")
    return default


def flatten(list_):
    return [value for sublist in list_ for value in sublist]


def to_json(obj):
    return tempita.html(json.dumps(obj, sort_keys=True))


def prepare_run_sets_for_js(run_sets):
    # Almost all run_set attributes are relevant, use blacklist here
    run_set_exclude_keys = {"filename"}

    def prepare_column(column):
        result = {k: v for k, v in column.__dict__.items() if v is not None}
        result["display_title"] = column.display_title or column.title
        result["type"] = column.type.type.name
        return result

    def prepare_run_set(attributes, columns):
        result = {
            k: v for k, v in attributes.items() if k not in run_set_exclude_keys and v
        }
        result["columns"] = [prepare_column(col) for col in columns]
        return result

    return [prepare_run_set(rs.attributes, rs.columns) for rs in run_sets]


def prepare_rows_for_js(rows, base_dir, href_base, relevant_id_columns):
    results_include_keys = ["category"]

    def prepare_value(column, value, run_result):
        """
        Return a dict that represents one value (table cell).
        We always add the raw value (as in CSV), and sometimes a version that is
        formatted for HTML (e.g., with spaces for alignment).
        """
        raw_value = column.format_value(value, False, "csv")
        # We need to make sure that formatted_value is safe (no unescaped tool output),
        # but for text columns format_value returns the same for csv and html_cell,
        # and for number columns the HTML result is safe.
        formatted_value = column.format_value(value, True, "html_cell")
        result = {}
        if column.href:
            result["href"] = create_link(column.href, base_dir, run_result, href_base)
            if not raw_value and not formatted_value:
                raw_value = column.pattern
        if raw_value is not None and not raw_value == "":
            result["raw"] = raw_value
        if formatted_value and formatted_value != raw_value:
            result["html"] = formatted_value
        return result

    def clean_up_results(res):
        values = [
            prepare_value(column, value, res)
            for column, value in zip(res.columns, res.values)
        ]
        toolHref = [
            column.href for column in res.columns if column.title.endswith("status")
        ][0] or res.log_file
        result = {k: getattr(res, k) for k in results_include_keys}
        if toolHref:
            result["href"] = create_link(toolHref, base_dir, res, href_base)
        result["values"] = values
        return result

    def clean_up_row(row):
        result = {}
        result["id"] = list(
            id_part
            for id_part, relevant in zip(row.id, relevant_id_columns)
            if id_part and relevant
        )
        # Replace first part of id (task name, which is always shown) with short name
        assert relevant_id_columns[0]
        result["id"][0] = row.short_filename

        result["results"] = [clean_up_results(res) for res in row.results]
        if row.has_sourcefile:
            result["href"] = create_link(row.filename, base_dir)
        return result

    return [clean_up_row(row) for row in rows]


def partition_list_according_to_other(l, template):
    """
    Partition a list "l" into the same shape as a given list of lists "template".
    """
    lengths = [len(sublist) for sublist in template]
    assert len(l) == sum(lengths)

    def get_sublist(i):
        start = sum(lengths[0:i])
        return l[start : start + lengths[i]]

    return [get_sublist(i) for i in range(len(template))]


def prepare_stats_for_js(stats, all_columns):
    def prepare_values(column, value, key):
        return (
            column.format_value(value, True, "html_cell")
            if key is "sum"
            else column.format_value(value, False, "tooltip")
        )

    flattened_columns = flatten(all_columns)

    def clean_up_stat(stat):
        prepared_content = [
            {
                k: prepare_values(column, v, k)
                for k, v in col_content.__dict__.items()
                if v is not None
            }
            if col_content
            else None
            for column, col_content in zip(flattened_columns, stat.content)
        ]

        result = dict(stat)
        result["content"] = partition_list_according_to_other(
            prepared_content, all_columns
        )
        return result

    return [clean_up_stat(stat_row) for stat_row in stats]


def merge_entries_with_common_prefixes(list_, number_of_needed_commons=6):
    """
    Returns a list where sequences of post-fixed entries are shortened to their common prefix.
    This might be useful in cases of several similar values,
    where the prefix is identical for several entries.
    If less than 'number_of_needed_commons' are identically prefixed, they are kept unchanged.
    Example: ['test', 'pc1', 'pc2', 'pc3', ... , 'pc10'] -> ['test', 'pc*']
    """
    # first find common entry-sequences
    prefix = None
    lists_to_merge = []
    for entry in list_:
        newPrefix, number = split_string_at_suffix(entry, numbers_into_suffix=True)
        if entry == newPrefix or prefix != newPrefix:
            lists_to_merge.append([])
            prefix = newPrefix
        lists_to_merge[-1].append((entry, newPrefix, number))

    # then merge them
    returnvalue = []
    for common_entries in lists_to_merge:
        common_prefix = common_entries[0][1]
        assert all(common_prefix == prefix for entry, prefix, number in common_entries)
        if len(common_entries) <= number_of_needed_commons:
            returnvalue.extend((entry for entry, prefix, number in common_entries))
        else:
            # we use '*' to indicate several entries,
            # it would also be possible to use '[min,max]' from '(n for e,p,n in common_entries)'
            returnvalue.append(common_prefix + "*")

    return returnvalue


def prettylist(list_):
    """
    Filter out duplicate values while keeping order.
    """
    if not list_:
        return ""

    values = set()
    uniqueList = []

    for entry in list_:
        if not entry in values:
            values.add(entry)
            uniqueList.append(entry)

    return uniqueList[0] if len(uniqueList) == 1 else "[" + "; ".join(uniqueList) + "]"


def read_bundled_file(name):
    """Read a file that is packaged together with this application."""
    try:
        return __loader__.get_data(name).decode("UTF-8")
    except NameError:
        with open(name, mode="r") as f:
            return f.read()


class _DummyFuture(object):
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class DummyExecutor(object):
    """Executor similar to concurrent.futures.ProcessPoolExecutor
    but executes everything sequentially in the current process.
    This can be useful for debugging.
    Not all features of ProcessPoolExecutor are supported.
    """

    def submit(self, func, *args, **kwargs):
        return _DummyFuture(func(*args, **kwargs))

    map = map

    def shutdown(self, wait=None):
        pass


class TableDefinitionError(Exception):
    """Exception raised for errors in the table definition.

    :param message Error message
    """

    def __init__(self, message):
        self.message = message
