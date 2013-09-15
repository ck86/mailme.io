# -*- coding: utf-8 -*-
"""
    mailme.utils.html
    ~~~~~~~~~~~~~~~~~

    This module implements various HTML/XHTML utility functions.  Some parts
    of this module require the lxml and html5lib libraries.

    :copyright: (c) 2013 mailme, see AUTHORS for more details.
    :license: BSD.
"""
import re
from xml.sax.saxutils import quoteattr

from django.utils.encoding import force_text

import lxml.html.clean
from html5lib import HTMLParser, treewalkers, treebuilders
from .html.entities import name2codepoint
from lxml.html.defs import empty_tags
from html5lib.filters import _base as filters_base
from mailme.utils.text import increment_string
from html5lib.serializer import HTMLSerializer
from html5lib.filters.optionaltags import Filter as OptionalTagsFilter

_entity_re = re.compile(r'&([^;]+);')
_strip_re = re.compile(r'<!--.*?-->|<[^>]*>(?s)')


#: a dict of html entities to codepoints. This includes the problematic
#: &apos; character.
html_entities = name2codepoint.copy()
html_entities['apos'] = 39
del name2codepoint


def _build_html_tag(tag, attrs):
    """Build an HTML opening tag."""
    attrs = ' '.join(iter(
        '%s=%s' % (k, quoteattr(str(v)))
        for k, v in list(attrs.items())
        if v is not None))

    return '<%s%s%s>' % (
        tag, attrs and ' ' + attrs or '',
        tag in empty_tags and ' /' or '',
    ), tag not in empty_tags and '</%s>' % tag or ''


def build_html_tag(tag, class_=None, classes=None, **attrs):
    """Build an HTML opening tag."""
    if classes:
        class_ = ' '.join(x for x in classes if x)
    if class_:
        attrs['class'] = class_
    return _build_html_tag(tag, attrs)[0]


def _handle_match(match):
    name = match.group(1)
    if name in html_entities:
        return chr(html_entities[name])
    if name[:2] in ('#x', '#X'):
        try:
            return chr(int(name[2:], 16))
        except ValueError:
            return ''
    elif name.startswith('#'):
        try:
            return chr(int(name[1:]))
        except ValueError:
            return ''
    return ''


def replace_entities(string):
    """
    Replace HTML entities in a string:

    >>> replace_entities('foo &amp; bar &raquo; foo')
    u'foo & bar \\xbb foo'
    """
    if string is None:
        return ''
    return _entity_re.sub(_handle_match, string)


def striptags(string):
    """Remove HTML tags from a string."""
    if string is None:
        return ''
    if isinstance(string, str):
        string = string.decode('utf8')
    return ' '.join(_strip_re.sub('', replace_entities(string)).split())


def parse_html(string, fragment=True):
    """
    Parse a tagsoup into a tree. For cleaning up
    markup you can use the `cleanup_html` function.
    """
    parser = HTMLParser(tree=treebuilders.getTreeBuilder('lxml'))
    return (fragment and parser.parseFragment or parser.parse)(string)


def cleanup_html(string, sanitize=True, fragment=True, stream=False,
                 filter_optional_tags=False, id_prefix=None,
                 update_anchor_links=True):
    """Clean up some html and convert it to HTML."""
    if not string.strip():
        return ''
    string = force_text(string)
    if sanitize:
        string = lxml.html.clean.clean_html(string)
    tree = parse_html(string, fragment)
    walker = treewalkers.getTreeWalker('lxml')(tree)
    walker = CleanupFilter(walker, id_prefix, update_anchor_links)
    if filter_optional_tags:
        walker = OptionalTagsFilter(walker)
    serializer = HTMLSerializer(
        quote_attr_values=True,
        minimize_boolean_attributes=False,
        omit_optional_tags=False,
    )
    rv = serializer.serialize(walker, 'utf-8')
    if stream:
        return rv
    return force_text(''.join(rv))


class CleanupFilter(filters_base.Filter):
    """
    A simple filter that replaces deprecated elements with others.
    """

    tag_conversions = {
        'center': ('span', 'text-align: center'),
        'u': ('span', 'text-decoration: underline'),
        'menu': ('ul', None),
        'strike': ('del', None)
    }

    end_tags = {key: value[0] for key, value in list(tag_conversions.items())}
    end_tags['font'] = 'span'

    def __init__(self, source, id_prefix=None, update_anchor_links=False):
        self.source = source
        self.id_prefix = id_prefix
        self.update_anchor_links = update_anchor_links

    def __iter__(self):
        id_map = {}
        deferred_links = {}
        stream = self.walk(id_map, deferred_links)

        if not self.update_anchor_links:
            result = stream
        else:
            result = list(stream)
            for target_id, link in list(deferred_links.items()):
                if target_id in id_map:
                    for idx, (key, value) in enumerate(link['data']):
                        if key == 'href':
                            link['data'][idx] = [key, '#' + id_map[target_id]]
                            break
        for item in result:
            yield item

    def walk(self, id_map, deferred_links):
        tracked_ids = set()

        for token in filters_base.Filter.__iter__(self):
            if token['type'] == 'StartTag':
                attrs = token.get('data', {})
                if not isinstance(attrs, dict):
                    attrs = dict(reversed(attrs))
                # The attributes are namespaced --
                #we don't care about that, add them back later
                attrs = {k: v for (_, k), v in list(attrs.items())}
                if token['name'] in self.tag_conversions:
                    new_tag, new_style = self.tag_conversions[token['name']]
                    token['name'] = new_tag
                    if new_style:
                        style = attrs.get('style', '')
                        # this could give false positives, but the chance is
                        # quite small that this happens.
                        if new_style not in style:
                            attrs[(None, 'style')] = (
                                (style and style.rstrip(';') + '; ' or '')
                                + new_style + ';'
                            )

                elif token['name'] == 'a' and attrs.get('href', '').startswith('#'):
                    attrs.pop('target', None)
                    deferred_links[attrs['href'][1:]] = token

                elif token['name'] == 'font':
                    token['name'] = 'span'
                    attrs = token.get('data', ())
                    if not isinstance(attrs, dict):
                        attrs = dict(reversed(attrs))
                    styles = []
                    tmp = attrs.pop('color', None)
                    if tmp:
                        styles.append('color: %s' % tmp)
                    tmp = attrs.pop('face', None)
                    if tmp:
                        styles.append('font-family: %s' % tmp)
                    tmp = attrs.pop('size', None)
                    if tmp:
                        styles.append('font-size: %s' % {
                            '1': 'xx-small',
                            '2': 'small',
                            '3': 'medium',
                            '4': 'large',
                            '5': 'x-large',
                            '6': 'xx-large'
                        }.get(tmp, 'medium'))
                    if styles:
                        style = attrs.get('style')
                        attrs['style'] = (style and style.rstrip(';') + ' ;'
                                          or '') + '; '.join(styles) + ';'

                elif token['name'] == 'img':
                    attrs.pop('border', None)
                    if 'alt' not in attrs:
                        attrs['alt'] = ''

                if 'id' in attrs:
                    element_id = original_id = attrs['id']
                    while element_id in tracked_ids:
                        element_id = increment_string(element_id)
                    tracked_ids.add(element_id)
                    if self.id_prefix:
                        element_id = self.id_prefix + element_id
                    attrs['id'] = element_id
                    id_map[original_id] = element_id
                token['data'] = {}
                for k, v in list(attrs.items()):
                    # None is the namespace
                    token['data'][(None, force_text(k))] = force_text(v)
            elif token['type'] == 'EndTag' and token['name'] in self.end_tags:
                token['name'] = self.end_tags[token['name']]
            yield token
