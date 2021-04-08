"""
Kernel CI report object-relational mapping (ORM) - report data organized into
objects, but without the object-oriented interface.
"""

import re
import textwrap
import argparse
from abc import ABC, abstractmethod
import jinja2
import jsonschema
import kcidb_io as io
import kcidb.misc
from kcidb.misc import LIGHT_ASSERTS
from kcidb.templates import ENV as TEMPLATE_ENV

# We'll get to it, pylint: disable=too-many-lines


class Relation:
    """A parent/child relation between object types"""

    def __init__(self, parent, child, ref_fields):
        """
        Initialize a relation.

        Args:
            parent:     The parent type.
            child:      The child type.
            ref_fields: A tuple containing the list of names of child fields,
                        containing values of parent's globally-identifying
                        fields (in the same order), and linking the two.
        """
        assert isinstance(parent, Type)
        assert isinstance(child, Type)
        assert isinstance(ref_fields, tuple)
        assert all(isinstance(ref_field, str) for ref_field in ref_fields)
        assert len(ref_fields) == len(parent.id_fields)
        self.parent = parent
        self.child = child
        self.ref_fields = ref_fields


class Type:
    """An object type"""

    # It's OK, pylint: disable=too-many-instance-attributes,too-many-arguments

    def __init__(self, name, json_schema, id_fields,
                 summary_template, description_template):
        """
        Initialize an object type.

        Args:
            name:                   The type name.
            json_schema:            The JSON schema describing the raw object
                                    data.
            id_fields:              A tuple containing the names of object
                                    fields identifying it globally.
            summary_template:       A Jinja2 Template object producing a
                                    plain-text summary of an object of this
                                    type, with the object exposed as the
                                    type-named variable.
            description_template:   A Jinja2 Template object producing a
                                    plain-text summary of an object of this
                                    type, with the object exposed as the
                                    type-named variable.
        """
        assert isinstance(name, str)
        assert isinstance(json_schema, dict)
        assert isinstance(id_fields, tuple) and \
               all(isinstance(f, str) for f in id_fields)
        assert isinstance(summary_template, jinja2.Template)
        assert isinstance(description_template, jinja2.Template)

        # The name of this type
        self.name = name
        # The JSON schema for this type's raw data
        self.json_schema = json_schema
        # List of ID field names
        self.id_fields = id_fields
        # A list of all relations
        self.relations = []
        # A map of parent type names and their relations
        self.parents = {}
        # A map of child type names and their relations
        self.children = {}
        # A summary template
        self.summary_template = summary_template
        # A description template
        self.description_template = description_template

    def add_relation(self, relation):
        """
        Add a relation of this object to another.

        Args:
            relation:   The relation to add.
                        Must have this type as either the parent or the child.
                        Must not have been added before.
        """
        assert isinstance(relation, Relation)
        assert self is relation.parent or self is relation.child
        assert relation not in self.relations
        self.relations.append(relation)
        if self is relation.parent:
            self.children[relation.child.name] = relation
        if self is relation.child:
            self.parents[relation.parent.name] = relation

    def validate(self, data):
        """
        Validate a type's data against its JSON schema.

        Args:
            data:   The data to validate.

        Returns:
            The validated (but unmodified) data.

        Raises:
            `jsonschema.exceptions.ValidationError`, if the data did not
            adhere to this type's JSON schema.
        """
        jsonschema.validate(instance=data, schema=self.json_schema,
                            format_checker=jsonschema.draft7_format_checker)
        return data

    def is_valid(self, data):
        """
        Check if a type's data is valid according to its JSON schema.

        Args:
            data:   The data to check.

        Returns:
            True if the data is valid, False otherwise.
        """
        try:
            self.validate(data)
            return True
        except jsonschema.exceptions.ValidationError:
            return False

    def get_id(self, data):
        """
        Retrieve a tuple of field values identifying an object globally, from
        its data.

        Args:
            data:   The object data to retrieve the IDs from.

        Returns:
            A tuple of values of object fields identifying it globally.
        """
        assert LIGHT_ASSERTS or self.is_valid(data)
        return tuple(data[field] for field in self.id_fields)


class Schema:
    """A repository of recognized object types"""

    def __init__(self, types):
        """
        Initialize the schema.

        Args:
            types:  A dictionary of type descriptions. Keys being type names
                    and values being dictionaries with the following entries:
                        * "field_json_schemas" - a dictionary of field names
                                                 and JSON schemas for their
                                                 values (when present),
                        * "required_fields" - a set of names of required
                                              fields,
                        * "id_fields" - a tuple of names of the object fields
                                        identifying it globally,
                        * "summary_template" - a jinja2.Template instance
                                               formatting a plain-text summary
                                               of an object of this type, the
                                               object provided in the template
                                               environment under the name of
                                               the type.
                        * "description_template" - a jinja2.Template instance
                                                   formatting a plain-text
                                                   description of an object of
                                                   this type, the object
                                                   provided in the template
                                                   environment under the name
                                                   of the type.
                        * "children" - the optional dictionary of names of
                                       child types and tuples containing
                                       names of fields with values of parent's
                                       identifying fields ("id_fields"),
                                       in the same order.
        """
        assert isinstance(types, dict)
        assert all(
            isinstance(name, str) and
            isinstance(info, dict) and
            "field_json_schemas" in info and
            isinstance(info["field_json_schemas"], dict) and
            "required_fields" in info and
            isinstance(info["required_fields"], set) and
            "id_fields" in info and
            isinstance(info["id_fields"], tuple) and
            (set(info["id_fields"]) ==
             set(info["id_fields"]) & set(info["field_json_schemas"])) and
            all(isinstance(f, str) for f in info["id_fields"]) and
            "summary_template" in info and
            isinstance(info["summary_template"], jinja2.Template) and
            "description_template" in info and
            isinstance(info["description_template"], jinja2.Template) and
            ("children" not in info or (
                isinstance(info["children"], dict) and
                all(
                    isinstance(name, str) and
                    name in types and
                    isinstance(ref_fields, tuple) and
                    all(isinstance(f, str) for f in ref_fields)
                    for name, ref_fields in info["children"].items()
                )
            ))
            for name, info in types.items()
        )

        # Create types and build the JSON schema
        self.types = {}
        self.json_schema = dict(
            type="object",
            additionalProperties=False,
            properties={},
        )
        for name, info in types.items():
            json_schema = dict(
                type="object",
                properties={
                    name: (
                        json_schema if name in info["required_fields"]
                        else dict(anyOf=[dict(type="null"), json_schema])
                    )
                    for name, json_schema in
                    info["field_json_schemas"].items()
                },
                required=list(info["field_json_schemas"]),
                additionalProperties=False,
            )
            self.json_schema["properties"][name] = dict(
                type="array", items=json_schema
            )
            self.types[name] = Type(name, json_schema, info["id_fields"],
                                    info["summary_template"],
                                    info["description_template"])

        # Create and register relations
        self.relations = []
        for name, info in types.items():
            type = self.types[name]
            for child_name, ref_fields in info.get("children", {}).items():
                try:
                    child_type = self.types[child_name]
                except KeyError:
                    raise Exception(f"Couldn't find child {child_name!r} "
                                    f"of type {name!r}") from None
                relation = Relation(type, child_type, ref_fields)
                self.relations.append(relation)
                type.add_relation(relation)
                child_type.add_relation(relation)

    def validate(self, data):
        """
        Validate raw object-oriented data against the schema.

        Args:
            data:   The data to validate.

        Returns:
            The validated data.

        Raises:
            `jsonschema.exceptions.ValidationError`, if the data did not
            match the schema.
        """
        jsonschema.validate(instance=data, schema=self.json_schema,
                            format_checker=jsonschema.draft7_format_checker)
        return data

    def is_valid(self, data):
        """
        Check if a raw object-oriented data is valid according to the schema.

        Args:
            data:   The data to check.

        Returns:
            True if the data is valid, False otherwise.
        """
        try:
            self.validate(data)
            return True
        except jsonschema.exceptions.ValidationError:
            return False

    def format_dot(self):
        """
        Format the directed graph of object type relations in the schema using
        the DOT language. The returned value could be visualized with e.g.
        "dot -Tx11".

        Returns:
            The string containing the DOT representation of object type
            relations in the schema.
        """
        return "".join(
            ["digraph {\n"] +
            [
                f"{r.parent.name} -> {r.child.name}\n"
                for r in self.relations
            ] +
            ["}\n"]
        )


# Checkout properties from the latest I/O schema
_CHECKOUT = \
    io.schema.LATEST.json['properties']['checkouts']['items']['properties']
# Build properties from the latest I/O schema
_BUILD = \
    io.schema.LATEST.json['properties']['builds']['items']['properties']
# Test properties from the latest I/O schema
_TEST = \
    io.schema.LATEST.json['properties']['tests']['items']['properties']

# The schema of the raw object-oriented data
SCHEMA = Schema(dict(
    revision=dict(
        field_json_schemas=dict(
            git_commit_hash=_CHECKOUT['git_commit_hash'],
            patchset_hash=_CHECKOUT['patchset_hash'],
            patchset_files=_CHECKOUT['patchset_files'],
            git_commit_name=_CHECKOUT['git_commit_name'],
            contacts=_CHECKOUT['contacts'],
        ),
        required_fields=set(),
        id_fields=("git_commit_hash", "patchset_hash"),
        children=dict(
            checkout=("git_commit_hash", "patchset_hash",)
        ),
        summary_template=TEMPLATE_ENV.get_template(
            "revision_summary.txt.j2"
        ),
        description_template=TEMPLATE_ENV.get_template(
            "revision_description.txt.j2"
        ),
    ),
    checkout=dict(
        field_json_schemas=dict(
            id=_CHECKOUT['id'],
            git_commit_hash=_CHECKOUT['git_commit_hash'],
            patchset_hash=_CHECKOUT['patchset_hash'],
            origin=_CHECKOUT['origin'],
            git_repository_url=_CHECKOUT['git_repository_url'],
            git_repository_branch=_CHECKOUT['git_repository_branch'],
            tree_name=_CHECKOUT['tree_name'],
            message_id=_CHECKOUT['message_id'],
            start_time=_CHECKOUT['start_time'],
            log_url=_CHECKOUT['log_url'],
            log_excerpt=_CHECKOUT['log_excerpt'],
            comment=_CHECKOUT['comment'],
            valid=_CHECKOUT['valid'],
            misc=_CHECKOUT['misc'],
        ),
        required_fields={'id', 'origin'},
        id_fields=("id",),
        children=dict(
            build=("checkout_id",)
        ),
        summary_template=TEMPLATE_ENV.get_template(
            "checkout_summary.txt.j2"
        ),
        description_template=TEMPLATE_ENV.get_template(
            "checkout_description.txt.j2"
        ),
    ),
    build=dict(
        field_json_schemas=dict(
            id=_BUILD['id'],
            checkout_id=_BUILD['checkout_id'],
            origin=_BUILD['origin'],
            start_time=_BUILD['start_time'],
            duration=_BUILD['duration'],
            architecture=_BUILD['architecture'],
            command=_BUILD['command'],
            compiler=_BUILD['compiler'],
            input_files=_BUILD['input_files'],
            output_files=_BUILD['output_files'],
            config_name=_BUILD['config_name'],
            config_url=_BUILD['config_url'],
            log_url=_BUILD['log_url'],
            log_excerpt=_BUILD['log_excerpt'],
            comment=_BUILD['comment'],
            valid=_BUILD['valid'],
            misc=_BUILD['misc'],
        ),
        required_fields={'id', 'origin', 'checkout_id'},
        id_fields=("id",),
        children=dict(
            test=("build_id",),
        ),
        summary_template=TEMPLATE_ENV.get_template(
            "build_summary.txt.j2"
        ),
        description_template=TEMPLATE_ENV.get_template(
            "build_description.txt.j2"
        ),
    ),
    test=dict(
        field_json_schemas=dict(
            id=_TEST['id'],
            build_id=_TEST['build_id'],
            origin=_TEST['origin'],
            path=_TEST['path'],
            environment_comment=_TEST['environment']['properties']['comment'],
            environment_misc=_TEST['environment']['properties']['misc'],
            status=_TEST['status'],
            waived=_TEST['waived'],
            start_time=_TEST['start_time'],
            duration=_TEST['duration'],
            output_files=_TEST['output_files'],
            log_url=_TEST['log_url'],
            log_excerpt=_TEST['log_excerpt'],
            comment=_TEST['comment'],
            misc=_TEST['misc'],
        ),
        required_fields={'id', 'origin', 'build_id'},
        id_fields=("id",),
        summary_template=TEMPLATE_ENV.get_template(
            "test_summary.txt.j2"
        ),
        description_template=TEMPLATE_ENV.get_template(
            "test_description.txt.j2"
        ),
    ),
))

assert all(k.endswith("s") for k in io.schema.LATEST.tree if k), \
    "Not all I/O object list names end with 's'"

assert set(SCHEMA.types) >= \
    set(k[:-1] for k in io.schema.LATEST.tree if k), \
    "OO types are not a superset of I/O types"

# A (verbose) regular expression pattern matching an unquoted ID field
_PATTERN_STRING_ID_FIELD_UNQUOTED_PATTERN = """
    [\x30-\x39\x41-\x5a\x61-\x7a_:/.?%+-]+
"""

_PATTERN_STRING_ID_FIELD_UNQUOTED_RE = re.compile(
    _PATTERN_STRING_ID_FIELD_UNQUOTED_PATTERN,
    re.ASCII | re.VERBOSE
)

# A (verbose) regular expression pattern matching characters which can
# appear unescaped in a quoted ID field
_PATTERN_STRING_ID_FIELD_QUOTED_UNESC_CHAR_PATTERN = """
    # Anything printable except doublequote/backslash
    [\x5d-\x7e\x20-\x21\x23-\x5b]
"""

# A (verbose) regular expression pattern matching characters which must be
# backslash-escaped when appearing in a quoted ID field
_PATTERN_STRING_ID_FIELD_QUOTED_ESC_CHAR_PATTERN = """
    # Doublequote/backslash
    ["\\\\]
"""

# A (verbose) regular expression pattern matching a quoted ID field
_PATTERN_STRING_ID_FIELD_QUOTED_PATTERN = f"""
    "
        (?:
            {_PATTERN_STRING_ID_FIELD_QUOTED_UNESC_CHAR_PATTERN} |
            \\\\ {_PATTERN_STRING_ID_FIELD_QUOTED_ESC_CHAR_PATTERN}
        )*
    "
"""

# A (verbose) regular expression pattern matching an ID field
_PATTERN_STRING_ID_FIELD_PATTERN = f"""
    (?:
        {_PATTERN_STRING_ID_FIELD_UNQUOTED_PATTERN} |
        {_PATTERN_STRING_ID_FIELD_QUOTED_PATTERN}
    )
"""

# A (verbose) regular expression pattern matching an ID (ID field list)
_PATTERN_STRING_ID_PATTERN = f"""
    {_PATTERN_STRING_ID_FIELD_PATTERN}
    (?:
        \\s*
        ,
        \\s*
        {_PATTERN_STRING_ID_FIELD_PATTERN}
    )*
"""

# A (verbose) regular expression pattern matching an ID list
_PATTERN_STRING_ID_LIST_PATTERN = f"""
    {_PATTERN_STRING_ID_PATTERN}
    (?:
        \\s*
        ;
        \\s*
        {_PATTERN_STRING_ID_PATTERN}
    )*
"""

# A (verbose) regular expression pattern matching an ID list spec
_PATTERN_STRING_SPEC_ID_LIST_PATTERN = f"""
    \\[
        \\s*
        {_PATTERN_STRING_ID_LIST_PATTERN}
        \\s*
    \\]
"""

# A (verbose) regular expression pattern matching a spec
_PATTERN_STRING_SPEC_PATTERN = f"""
    (?:
        # ID list placeholder
        % |
        # Inline ID list
        {_PATTERN_STRING_SPEC_ID_LIST_PATTERN}
    )
"""

# A (verbose) regular expression pattern matching a "pattern" part of the
# pattern string. Matching group names correspond to component ABNF rules.
_PATTERN_STRING_PATTERN = f"""
    \\s*
    # Relation
    (?P<relation>
        [<>]
    )
    \\s*
    # Type
    (?P<type>
        # Type name
        [a-z0-9_]+ |
        # Type branch wildcard
        [*]
    )
    \\s*
    # ID list specification
    (?P<spec>
        {_PATTERN_STRING_SPEC_PATTERN}
    )?
    \\s*
    # Matching scope
    (?P<match>
        [#$]
    )?
    \\s*
"""

# A regular expression matching a "pattern" part of the pattern string
# Matching group names correspond to component ABNF rules.
_PATTERN_STRING_RE = re.compile(
    _PATTERN_STRING_PATTERN,
    re.ASCII | re.VERBOSE
)


class Pattern:
    """A pattern matching objects in a data source"""

    # No, it's OK, pylint: disable=too-many-arguments
    def __init__(self, base, child, obj_type, obj_id_list, match):
        """
        Initialize an object pattern.

        Args:
            base:           The pattern for objects this pattern is to be
                            based on, or None, meaning the pattern is based on
                            the root object.
            child:          True if this is a pattern for a base's child type,
                            False if it's for a parent type.
            obj_type:       The type (kcidb.orm.Type) of objects referred
                            to by this pattern.
            obj_id_list:    The list of IDs of the objects to limit the
                            pattern to, or None to not limit the objects by
                            IDs.
            match:          True if the objects referenced by this pattern
                            should be matched, false if not.
        """
        assert base is None or isinstance(base, Pattern)
        assert isinstance(child, bool)
        assert isinstance(obj_type, Type)
        obj_id_fields = obj_type.id_fields
        assert obj_id_list is None or \
               isinstance(obj_id_list, list) and \
               all(
                    isinstance(obj_id, tuple) and
                    len(obj_id) == len(obj_id_fields) and
                    all(isinstance(part, (str, type(None))) for part in obj_id)
                    for obj_id in obj_id_list
               )
        assert isinstance(match, bool)
        assert base is not None or child
        assert base is None or (
            (
                child and
                obj_type.name in base.obj_type.children
            ) or
            (
                not child and
                base.obj_type.name in obj_type.children
            )
        )

        self.base = base
        self.child = child
        self.obj_type = obj_type
        self.obj_id_list = None if obj_id_list is None else obj_id_list.copy()
        self.match = match

    def __eq__(self, other):
        return \
            isinstance(other, Pattern) and \
            self.base == other.base and \
            self.child == other.child and \
            self.obj_type == other.obj_type and \
            self.obj_id_list == other.obj_id_list and \
            self.match == other.match

    @staticmethod
    def _format_id_field(id_field):
        """
        Format an ID field for a string representation of a pattern.

        Args:
            id_field:   The ID field to format.

        Returns:
            The formatted (quoted or unquoted) ID field.
        """
        # If we can leave the field unquoted
        if re.fullmatch(id_field, _PATTERN_STRING_ID_FIELD_UNQUOTED_PATTERN):
            return id_field
        part_re = re.compile(f"""
            ({_PATTERN_STRING_ID_FIELD_QUOTED_UNESC_CHAR_PATTERN}*) |
            ({_PATTERN_STRING_ID_FIELD_QUOTED_ESC_CHAR_PATTERN})
        """, re.ASCII | re.VERBOSE)
        parts = []
        pos = 0
        while True:
            match = part_re.match(id_field, pos)
            unesc, esc = match.group(1, 2)
            pos = match.end()
            if unesc:
                parts.append(unesc)
            elif esc:
                parts += ["\\", esc]
            elif pos < len(id_field):
                raise Exception(
                    f"ID field cannot be represented in a pattern string: "
                    f"{id_field}"
                )
            else:
                break
        return "".join(parts)

    @staticmethod
    def _format_id_list_spec(obj_id_list):
        """
        Format an ID list spec for a string representation of a pattern.

        Args:
            obj_id_list:    The list of IDs to format as a spec,
                            or None if missing.

        Returns:
            The string representation of the ID list spec,
            or empty string if not specified.
        """
        if obj_id_list is None:
            return ""
        return "[" + "; ".join(
            ", ".join(
                Pattern._format_id_field(obj_id_field)
                for obj_id_field in obj_id
            )
            for obj_id in obj_id_list
        ) + "]"

    def __repr__(self):
        string = ""
        if self.base is not None:
            string += repr(self.base)
        string += ">" if self.child else "<"
        string += self.obj_type.name
        string += Pattern._format_id_list_spec(self.obj_id_list)
        if self.match:
            string += "#"
        return string

    @staticmethod
    def _expand_parents(schema, base_list, obj_type_expr, obj_id_list, match):
        """
        Expand a single level of parents into a list of patterns, for a parsed
        pattern specification.

        Args:
            schema:         An object type schema to use.
            base_list:      The list of patterns to base created patterns on.
                            Empty list means patterns shouldn't be based on
                            anything (based on the "root" type).
            obj_type_expr:  Object type expression, one of:
                            "*" - all parent types,
                            or a name of the specific parent type.
            obj_id_list:    List of object IDs to limit the pattern to,
                            or None to not limit the pattern.
            match:          True, if expanded patterns should be marked for
                            matching, False if not.

        Returns:
            A list of patterns expanded from the specification, referencing
            the supplied bases.
        """
        assert isinstance(schema, Schema)
        assert isinstance(base_list, list)
        assert all(isinstance(base, Pattern) for base in base_list)
        assert isinstance(obj_type_expr, str)
        assert obj_id_list is None or \
            (isinstance(obj_id_list, list) and
             all(isinstance(obj_id, tuple) and
                 all(isinstance(part, str) for part in obj_id)
                 for obj_id in obj_id_list))
        assert isinstance(match, bool)

        pattern_list = []
        # For each base
        for base in base_list:
            base_pattern_list = []
            # For each base's parent relation
            for obj_type_name, relation in base.obj_type.parents.items():
                if obj_type_expr in ("*", obj_type_name):
                    base_pattern_list.append(
                        Pattern(base, False, relation.parent,
                                obj_id_list, match)
                    )
            # If couldn't find any parents
            if not base_pattern_list:
                if obj_type_expr == "*":
                    base_pattern_list.append(base)
                else:
                    raise Exception(
                        f"Cannot find parent type {obj_type_expr!r}"
                    )
            pattern_list += base_pattern_list
        return pattern_list

    @staticmethod
    def _expand_children(schema, base_list, obj_type_expr, obj_id_list, match):
        """
        Expand a single level of children into a list of patterns, for a parsed
        pattern specification.

        Args:
            schema:         An object type schema to use.
            base_list:      The list of patterns to base created patterns on.
                            Empty list means patterns shouldn't be based on
                            anything (based on the "root" type).
            obj_type_expr:  Object type expression, one of:
                            "*" - all children types,
                            or a name of the specific child type.
            obj_id_list:    List of object IDs to limit the pattern to,
                            or None to not limit the pattern.
            match:          True, if expanded patterns should be marked for
                            matching, False if not.

        Returns:
            A list of patterns expanded from the specification, referencing
            the supplied bases.
        """
        assert isinstance(schema, Schema)
        assert isinstance(base_list, list)
        assert all(isinstance(base, Pattern) for base in base_list)
        assert isinstance(obj_type_expr, str)
        assert obj_id_list is None or \
            (isinstance(obj_id_list, list) and
             all(isinstance(obj_id, tuple) and
                 all(isinstance(part, (str, type(None))) for part in obj_id)
                 for obj_id in obj_id_list))
        assert isinstance(match, bool)

        pattern_list = []
        # If we are based on some objects
        if base_list:
            # For each base
            for base in base_list:
                # Start with an empty per-base pattern list
                base_pattern_list = []
                # For each base's child relation
                for obj_type_name, relation in base.obj_type.children.items():
                    if obj_type_expr in ("*", obj_type_name):
                        base_pattern_list.append(
                            Pattern(base, True, relation.child,
                                    obj_id_list, match)
                        )
                # If couldn't find any children
                if not base_pattern_list:
                    if obj_type_expr == "*":
                        base_pattern_list.append(base)
                    else:
                        raise Exception(
                            f"Cannot find child type {obj_type_expr!r}"
                        )
                pattern_list += base_pattern_list
        # Else we're not based on anything (based on root)
        else:
            for obj_type_name, obj_type in schema.types.items():
                if obj_type_expr in ("*", obj_type_name):
                    pattern_list.append(
                        Pattern(None, True, obj_type, obj_id_list, match)
                    )
            if obj_type_expr != "*" and not pattern_list:
                raise Exception(
                    f"Cannot find type {obj_type_expr!r}"
                )
        return pattern_list

    @staticmethod
    def _expand(schema, base_list, child, obj_type_expr, obj_id_list,
                match_spec):
        """
        Expand a parsed pattern specification into a list of patterns.

        Args:
            schema:         An object type schema to use.
            base_list:      The list of patterns to base created patterns
                            on. Empty list means patterns shouldn't be
                            based on anything (based on the "root" object).
            child:          True if the created patterns are for children
                            of the specified bases. False for parents.
            obj_type_expr:  Object type expression, one of:
                            "*" - all children/parents,
                            or a name of the specific type.
            obj_id_list:    List of object IDs to limit the pattern to,
                            or None to not limit the pattern.
            match_spec:     The matching specification string ("#", or "$"),
                            or None, if expanded patterns shouldn't be marked
                            for matching.

        Returns:
            A list of patterns expanded from the specification, referencing
            the supplied bases.
        """
        assert isinstance(base_list, list)
        assert all(isinstance(base, Pattern) for base in base_list)
        assert isinstance(child, bool)
        assert isinstance(obj_type_expr, str)
        assert obj_id_list is None or \
            (isinstance(obj_id_list, list) and
             all(isinstance(obj_id, tuple) and
                 all(isinstance(part, (str, type(None))) for part in obj_id)
                 for obj_id in obj_id_list))
        assert match_spec in (None, "#", "$")

        # Start with an empty pattern list
        pattern_list = []

        # While we can expand
        while True:
            if child:
                pattern_list = Pattern._expand_children(
                    schema, base_list, obj_type_expr,
                    obj_id_list, match_spec == "#")
            else:
                pattern_list = Pattern._expand_parents(
                    schema, base_list, obj_type_expr,
                    obj_id_list, match_spec == "#")
            # If we are done expanding
            if not obj_type_expr == "*" or pattern_list == base_list:
                break
            # Rebase for next expansion step
            base_list = pattern_list

        # If asked to match only the furthest children/objects
        if match_spec == "$":
            for pattern in pattern_list:
                pattern.match = True

        return pattern_list

    @staticmethod
    def _parse_id(string, pos):
        """
        Parse an ID string from a pattern.

        Args:
            string: The ID string to parse.
                    Must start with a string formatted according to "id" ABNF
                    rule, possibly followed by whitespace, and optionally
                    anything but a comma.
            pos:    The position to start parsing at.

        Returns:
            A tuple containing parsed ID fields, and the stopping position at
            the end of whitespace following the ID.
        """
        assert LIGHT_ASSERTS or re.match(_PATTERN_STRING_ID_PATTERN,
                                         string[pos:],
                                         re.ASCII | re.VERBOSE)
        id_fields = []

        # NOTE: Not handling failures here, we're expecting a valid string
        while True:
            # If it's a quoted field
            if string[pos] == '"':
                pos += 1
                id_field_chars = []
                while True:
                    char = string[pos]
                    pos += 1
                    if char == '"':
                        break
                    if char == '\\':
                        char = string[pos]
                        pos += 1
                    id_field_chars.append(char)
                id_field = "".join(id_field_chars)
            # Else it's an unquoted field
            else:
                match = _PATTERN_STRING_ID_FIELD_UNQUOTED_RE.match(
                            string, pos)
                pos = match.end()
                id_field = match.group(0)
            # Add the field to the ID
            id_fields.append(id_field)
            # Skip whitespace
            while pos < len(string) and string[pos].isspace():
                pos += 1
            # If it's not an ID field separator
            if pos >= len(string) or string[pos] != ',':
                break
            # Skip ID field separator
            pos += 1
            # Skip whitespace
            while string[pos].isspace():
                pos += 1

        return tuple(id_fields), pos

    @staticmethod
    def _parse_id_list(string):
        """
        Parse an ID list from a pattern string, stopping at a closing bracket.

        Args:
            string: The ID list string to parse.
                    Must be formatted according to "id_list" ABNF rule.

        Returns:
            A list containing ID field tuples parsed from the string.
        """
        assert LIGHT_ASSERTS or re.fullmatch(_PATTERN_STRING_ID_LIST_PATTERN,
                                             string, re.ASCII | re.VERBOSE)
        # NOTE: Not handling failures here, we're expecting a valid string
        id_list = []
        pos = 0
        while True:
            # We like our "id", pylint: disable=invalid-name
            # Parse next ID
            id, pos = Pattern._parse_id(string, pos)
            id_list.append(id)
            # Stop, if we ran out of IDs
            if pos >= len(string) or string[pos] != ';':
                break
            # Skip ID separator
            pos += 1
            # Skip whitespace
            while string[pos].isspace():
                pos += 1
        return id_list

    @staticmethod
    def _parse_spec(string, obj_id_list_list):
        """
        Parse an optional ID list specification from a pattern string,
        possibly consuming an element from the supplied object ID list list.

        Args:
            string:             The ID list specification string to parse,
                                or None, meaning the pattern had no ID list
                                specification.
            obj_id_list_list:   The list of object ID lists to retrieve ID
                                lists for placeholders from, or None, meaning
                                no list was supplied with the pattern string.
                                Not modified.

        Returns:
            Two items:
                * the retrieved object ID list, or None, if no specification
                  was provided with the pattern;
                * the list of object ID lists, possibly with the first element
                  removed, if it was consumed by a placeholder.

        Raises:
            Exception with a message, if there were no, or not enough ID
            lists, when required.
        """
        assert string is None or (
            isinstance(string, str) and (
                LIGHT_ASSERTS or
                re.fullmatch(_PATTERN_STRING_SPEC_PATTERN,
                             string, re.ASCII | re.VERBOSE)
            )
        )

        # NOTE: Not handling failures here, we're expecting a valid string
        if string is None:
            return None, obj_id_list_list
        if string == "%":
            if obj_id_list_list is None:
                raise Exception(
                    "No ID list list specified to substitute the placeholder"
                )
            try:
                return obj_id_list_list[0], obj_id_list_list[1:]
            except IndexError:
                raise Exception("Not enough ID lists specified") from None
        # Parse the ID list inside brackets
        return Pattern._parse_id_list(string[1:-1].strip()), obj_id_list_list

    STRING_DOC = textwrap.dedent("""\
        The pattern string is a series of pattern specifications, each
        consisting of a relation character, followed by object type
        specification, followed by the optional ID list specification,
        followed by the optional matching specification. It could be described
        using ABNF:

        whitespace = %x09-0d / %x20 ; Whitespace characters
        relation = ">" /    ; Children of all directly-preceding types,
                            ; or root types, if there's nothing on the left.
                   "<"      ; Parents of all directly-preceding types
        type = name /       ; A parent/child type with specified name
               "*"          ; Furthest parents/children of the types on the
                            ; left, or types themselves which have none.
        name_char = %x30-39 / %x61-7a / "_"
                            ; Lower-case letters, numbers, underscore
        name = 1*name_char  ; Type name
        id_field_unquoted_char = %x30-39 / %x41-5a / %x61-7a /
                                 "_" / ":" / "/" / "." / "?" / "%" / "+" / "-"
                            ; Characters permitted in unquoted ID fields:
                            ; letters, numbers, misc characters
        id_field_quoted_token = (%x20-21 / %x23-5b / %x5d-7e) /
                                "\\" (%x22 / %x5c)
                            ; Character sequences allowed in quoted ID fields:
                            ; anything printable except backslash or
                            ; doublequote, or backslash-escaped
                            ; backslash/doublequote.
        id_field = 1*id_field_unquoted_char /
                   %x22 *id_field_quoted_token %x22
                            ; Quoted/unquoted ID field
        id = id_field *(*whitespace "," *whitespace id)
                            ; ID (a sequence of ID fields)
        id_list = id *(*whitespace ";" *whitespace id_list)
                            ; A list of IDs
        spec = "%" /        ; ID list placeholder.
                            ; Consumes one ID list from the
                            ; separately-supplied list of ID lists to limit
                            ; objects of the types traversed by this pattern
                            ; specification. Each object type gets the same ID
                            ; list. Not allowed, if the list of ID lists isn't
                            ; supplied.
               "[" *whitespace id_list *whitespace "]"
                            ; Inline ID list
        match = "#" /       ; Match objects of all types traversed by this
                            ; pattern specification.
                "$"         ; Match objects of only the furthest types
                            ; traversed by this pattern specification.
        pattern = *whitespace relation *whitespace type
                  [*whitespace spec] [*whitespace match]
        pattern_string = 1*pattern *whitespace

        Examples:
            >build%#            Match builds with IDs from the first of a
                                separately-specified list of ID lists (if
                                supplied).
            >build%$            The same.
            >build[redhat:1077837]
                                Match a build with ID "redhat:1077837".
            >checkout%>build#   Match builds of checkouts with IDs from
                                the first element of separately-specified list
                                of ID lists (if supplied).
            >test%<build#       Match builds of tests with IDs from the first
                                element of separately-specified list of ID
                                lists (if supplied).
            >test[redhat:1077834_0; redhat:1077834_1]<build#
                                Match builds of tests with IDs
                                "redhat:1077834_0" and "redhat:1077834_1".
            >test%<*#           Match tests with IDs from the first element of
                                separately-specified list of ID lists (if
                                supplied), and all their parents.
            >test%<*$           Match only the furthest (the ultimate) parents
                                of tests with IDs from the optional ID list
                                list, or tests themselves, if they have no
                                parent types.
            >revision%#>*#      Match revisions with IDs from the optional ID
                                list list, and all their children, if any.
            >revision[c763deac7ff, 932e2d61add]#>*#
                                Match the revision with ID
                                (c763deac7ff, 932e2d61add),
                                and all its children, if any.
            >test%<*$>*#        Match the root objects containing tests with
                                the IDs from the optional ID list list, along
                                with all their children.
            >*#                 Match everything in the database.
            >*$                 Match objects of all childless types.
    """)

    @staticmethod
    def parse(string, obj_id_list_list=None, schema=None):
        """
        Parse a pattern string and its parameter IDs into a chain of Pattern
        objects. See kcidb.orm.Pattern.STRING_DOC for documentation on
        pattern strings.

        Args:
            string:             The pattern string.
            obj_id_list_list:   A list of ID lists to use to filter the
                                referenced objects with, in the order
                                specified in the pattern string. Each ID is a
                                tuple with ID column value strings. If not
                                specified, or specified as None, ID list
                                placeholders are not allowed in the pattern
                                string.
            schema:             An object type schema to use, or None to use
                                kcidb.orm.SCHEMA.

        Returns:
            A list of trailing pattern objects parsed from the pattern string.
        """
        assert isinstance(string, str)
        assert obj_id_list_list is None or (
            isinstance(obj_id_list_list, list) and
            all(
                isinstance(obj_id_list, list) and
                all(isinstance(obj_id, tuple) for obj_id in obj_id_list)
                for obj_id_list in obj_id_list_list
            )
        )
        assert schema is None or isinstance(schema, Schema)
        if schema is None:
            schema = SCHEMA

        pattern_list = []
        pos = 0
        while pos < len(string):
            match = _PATTERN_STRING_RE.match(string, pos)
            if not match:
                raise Exception(f"Invalid pattern string {string!r} "
                                f"at position {pos}: {string[pos:]!r}")
            relation, obj_type_expr, spec, match_spec = \
                match.group("relation", "type", "spec", "match")
            obj_id_list, obj_id_list_list = Pattern._parse_spec(
                spec, obj_id_list_list
            )
            try:
                pattern_list = Pattern._expand(
                    schema, pattern_list, relation == ">",
                    obj_type_expr, obj_id_list, match_spec
                )
            except Exception as exc:
                raise Exception(
                    f"Failed expanding pattern specification "
                    f"at position {pos}: {string[pos:]!r}"
                ) from exc
            pos = match.end()
        if obj_id_list_list:
            raise Exception(
                f"Too many ID lists specified for pattern {string!r}"
            )
        return pattern_list

    @staticmethod
    def from_io(io_data, schema=None):
        """
        Create a pattern list matching all objects in the supplied I/O data.

        Args:
            io_data:    The I/O data to create the pattern list from.
                        Must adhere to the latest schema version.
            schema:     An object type schema to use, or None to use
                        kcidb.orm.SCHEMA.

        Returns:
            A list of Pattern objects matching the objects in the supplied I/O
            data.
        """
        assert LIGHT_ASSERTS or io.schema.is_valid_latest(io_data)
        assert schema is None or isinstance(schema, Schema)
        if schema is None:
            schema = SCHEMA
        # Assert all I/O object lists are represented in the OO schema
        assert set(schema.types) >= \
            set(k[:-1] for k in io.schema.LATEST.tree if k), \
            "Specified OO types are not a superset of I/O types"
        pattern_list = []
        # Assume each I/O object is identified by a required "id" field
        for obj_list_name in io.schema.LATEST.tree:
            if not obj_list_name:
                continue
            assert obj_list_name.endswith("s")
            obj_list = io_data.get(obj_list_name, [])
            if not obj_list:
                continue
            pattern_list.append(
                Pattern(None, True, schema.types[obj_list_name[:-1]],
                        [(o["id"],) for o in obj_list], True)
            )
        return pattern_list


class Source(ABC):
    """An abstract source of raw object-oriented (OO) data"""

    @abstractmethod
    def oo_query(self, pattern_list):
        """
        Retrieve raw data for objects specified via a pattern list.

        Args:
            pattern_list:   A list of patterns ("kcidb.orm.Pattern"
                            instances) matching objects to fetch.
        Returns:
            A dictionary of object type names and lists containing retrieved
            raw data of the corresponding type.
        """
        assert isinstance(pattern_list, list)
        assert all(isinstance(r, Pattern) for r in pattern_list)


class PatternHelpAction(argparse.Action):
    """Argparse action outputting pattern string help and exiting."""
    def __init__(self,
                 option_strings,
                 dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS,
                 help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            Pattern.STRING_DOC +
            "\n" +
            "NOTE: Specifying object ID lists separately is not "
            "supported using\n"
            "      command-line tools. "
            "Only inline ID lists are supported.\n"
        )
        parser.exit()


def argparse_add_args(parser):
    """
    Add common ORM arguments to an argument parser.

    Args:
        The parser to add arguments to.
    """
    parser.add_argument(
        'pattern_strings',
        nargs='*',
        default=[],
        metavar='PATTERN',
        help='Object-matching pattern. '
             'See pattern documentation with --pattern-help.'
    )
    parser.add_argument(
        '--pattern-help',
        action=PatternHelpAction,
        help='Print pattern string documentation and exit.'
    )


class ArgumentParser(kcidb.misc.ArgumentParser):
    """
    Command-line argument parser with common ORM arguments added.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the parser, adding common ORM arguments.

        Args:
            args:   Positional arguments to initialize ArgumentParser with.
            kwargs: Keyword arguments to initialize ArgumentParser with.
        """
        super().__init__(*args, **kwargs)
        argparse_add_args(self)


class OutputArgumentParser(kcidb.misc.OutputArgumentParser):
    """
    Command-line argument parser for tools outputting JSON,
    with common ORM arguments added.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the parser, adding JSON output arguments.

        Args:
            args:   Positional arguments to initialize ArgumentParser with.
            kwargs: Keyword arguments to initialize ArgumentParser with.
        """
        super().__init__(*args, **kwargs)
        argparse_add_args(self)