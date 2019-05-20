from future.utils import raise_
from functools import reduce

import re

from vit import util
from vit.process import Command

REGEX_SPECIAL_CHARS_REGEX = re.compile('([!@#\$%\^\&*\)\(+=._-])')

class AutoComplete(object):

    def __init__(self, config, default_filters=None, extra_filters=None):
        self.default_filters = default_filters or ('column', 'project', 'tag')
        self.extra_filters = extra_filters or {}
        self.default_filter_config = {
            'column': {
                'suffixes': [':'],
            },
            'project': {
                'prefixes': ['project:'],
            },
            'tag': {
                'prefixes': ['+', '-'],
            },
        }
        self.config = config
        self.command = Command(self.config)
        for ac_type in self.default_filters:
            setattr(self, ac_type, [])
        for ac_type, items in list(self.extra_filters.items()):
            setattr(self, ac_type, items)
        self.reset()

    def refresh(self, filters=None):
        filters = filters or self.default_filters
        for ac_type in filters:
            setattr(self, ac_type, self.refresh_type(ac_type))

    def refresh_type(self, ac_type):
        command = 'task _%ss' % ac_type
        returncode, stdout, stderr = self.command.run(command, capture_output=True)
        if returncode == 0:
            items = list(filter(lambda x: True if x else False, stdout.split("\n")))
            if ac_type == 'project':
                items = self.create_project_entries(items)
            return items
        else:
            raise_(RuntimeError, "Error running command '%s': %s" % (command, stderr))

    def create_project_entries(self, projects):
        def projects_reducer(projects_accum, project):
            def project_reducer(project_accum, part):
                project_accum.append(part)
                project_string = '.'.join(project_accum)
                if not project_string in projects_accum:
                    projects_accum.append(project_string)
                return project_accum
            reduce(project_reducer, project.split('.'), [])
            return projects_accum
        return reduce(projects_reducer, projects, [])

    def make_entries(self, filters, filter_config):
        entries = []
        for ac_type in filters:
            items = getattr(self, ac_type)
            include_unprefixed = filter_config[ac_type]['include_unprefixed'] if ac_type in filter_config and 'include_unprefixed' in filter_config[ac_type] else False
            type_prefixes = filter_config[ac_type]['prefixes'] if ac_type in filter_config and 'prefixes' in filter_config[ac_type] else []
            type_suffixes = filter_config[ac_type]['suffixes'] if ac_type in filter_config and 'suffixes' in filter_config[ac_type] else []
            if include_unprefixed:
                for item in items:
                    entries.append((ac_type, item))
            for prefix in type_prefixes:
                for item in items:
                    entries.append((ac_type, '%s%s' % (prefix, item)))
            for suffix in type_suffixes:
                for item in items:
                    entries.append((ac_type, '%s%s' % (item, suffix)))
        entries.sort()
        return entries

    def setup(self, text_callback, filters=None, filter_config=None):
        if self.is_setup:
            self.reset()
        self.text_callback = text_callback
        if not filters:
            filters = self.default_filters
        if not filter_config:
            filter_config = self.default_filter_config
        self.refresh()
        self.entries = self.make_entries(filters, filter_config)
        self.root_only_filters = list(filter(lambda f: True if f in filter_config and 'root_only' in filter_config[f] else False, filters))
        self.is_setup = True

    def teardown(self):
        self.is_setup = False
        self.entries = []
        self.root_only_filters = []
        self.callback = None
        self.deactivate()

    def reset(self):
        self.teardown()

    def activate(self, text, edit_pos, reverse=False):
        if self.activated:
            self.send_tabbed_text(text, edit_pos, reverse)
            return
        if self.can_tab(text, edit_pos):
            self.activated = True
            self.generate_tab_options(text, edit_pos)
            self.send_tabbed_text(text, edit_pos, reverse)

    def deactivate(self):
        self.activated = False
        self.idx = None
        self.tab_options = []
        self.root_search = False
        self.search_fragment = None
        self.prefix = None
        self.suffix = None
        self.partial = None

    def send_tabbed_text(self, text, edit_pos, reverse):
        tabbed_text, final_edit_pos = self.next_tab_item(text, reverse)
        self.text_callback(tabbed_text, final_edit_pos)

    def generate_tab_options(self, text, edit_pos):
        if self.root_search:
            if self.has_root_only_filters():
                self.tab_options = list(map(lambda e: e[1], filter(lambda e: True if e[0] in self.root_only_filters else False, self.entries)))
            else:
                self.tab_options = list(map(lambda e: e[1], self.entries))
        else:
            self.parse_text(text, edit_pos)
            exp = re.compile(self.regexify(self.search_fragment))
            if self.has_root_only_filters():
                if self.search_fragment_is_root():
                    self.tab_options = list(map(lambda e: e[1], filter(lambda e: True if e[0] in self.root_only_filters and exp.match(e[1]) else False, self.entries)))
                else:
                    self.tab_options = list(map(lambda e: e[1], filter(lambda e: True if e[0] not in self.root_only_filters and exp.match(e[1]) else False, self.entries)))
            else:
                self.tab_options = list(map(lambda e: e[1], filter(lambda e: True if exp.match(e[1]) else False, self.entries)))

    def has_root_only_filters(self):
        return len(self.root_only_filters) > 0

    def search_fragment_is_root(self):
        return len(self.prefix_parts) == 0

    def regexify(self, string):
        return REGEX_SPECIAL_CHARS_REGEX.sub(r"\\\1", string)

    def parse_text(self, text, edit_pos):
        full_prefix = text[:edit_pos]
        self.prefix_parts = util.string_to_args(full_prefix)
        self.search_fragment = self.prefix_parts.pop()
        self.prefix = ' '.join(self.prefix_parts)
        self.suffix = text[(edit_pos + 1):]

    def can_tab(self, text, edit_pos):
        if edit_pos == 0:
            if text == '':
                self.root_search = True
                return True
            return False
        previous_pos = edit_pos - 1
        next_pos = edit_pos + 1
        return text[edit_pos:next_pos] in (' ', '') and text[previous_pos:edit_pos] not in (' ', '')

    def assemble(self, tab_option, solo_match=False):
        if solo_match and not tab_option.endswith(":"):
            tab_option += ' '
        parts = [self.prefix, tab_option, self.suffix]
        tabbed_text = ' '.join(filter(lambda p: True if p else False, parts))
        parts.pop()
        edit_pos_parts = ' '.join(filter(lambda p: True if p else False, parts))
        edit_pos_final = len(edit_pos_parts)
        return tabbed_text, edit_pos_final

    def partial_match(self):
        if self.partial:
            return
        ref_item = self.tab_options[0]
        ref_item_length = len(ref_item)
        tab_options_length = len(self.tab_options)
        pos = len(self.search_fragment)
        self.partial = self.search_fragment
        while pos < ref_item_length:
            pos += 1
            exp = re.compile(ref_item[:pos])
            ref_result = list(filter(lambda o: True if exp.match(o) else False, self.tab_options))
            if len(ref_result) == tab_options_length:
                self.partial = ref_item[:pos]
            else:
                break
        return self.partial != self.search_fragment

    def initial_idx(self, reverse):
        return len(self.tab_options) - 1 if reverse else 0

    def increment_index(self, reverse):
        if self.idx == None:
            self.idx = self.initial_idx(reverse)
        else:
            if reverse:
                self.idx = self.idx - 1 if self.idx > 0 else len(self.tab_options) - 1
            else:
                self.idx = self.idx + 1 if self.idx < len(self.tab_options) - 1 else 0

    def next_tab_item(self, text, reverse):
        tabbed_text = ''
        edit_pos = None
        if self.root_search:
            self.increment_index(reverse)
            tabbed_text = self.tab_options[self.idx]
        else:
            if len(self.tab_options) == 0:
                tabbed_text = text
            elif len(self.tab_options) == 1:
                tabbed_text, edit_pos = self.assemble(self.tab_options[0], solo_match=True)
            else:
                if self.partial_match():
                    tabbed_text, edit_pos = self.assemble(self.partial)
                else:
                    if self.idx == None and self.partial == self.tab_options[self.initial_idx(reverse)]:
                        self.increment_index(reverse)
                    self.increment_index(reverse)
                    tabbed_text, edit_pos = self.assemble(self.tab_options[self.idx])
        return tabbed_text, edit_pos

