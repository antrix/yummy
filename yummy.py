#!/usr/bin/env python
import cPickle as pickle
import feedparser
import logging
import os
import sys
import time
import urllib
import urllib2
import xml.etree.cElementTree as ET
import ConfigParser

__author__      = 'Deepak Sarda'
__version__     = '0.1.1'
__copyright__   = '(c) 2008 Deepak Sarda'
__license__     = 'Public Domain'
__url__         = 'http://antrix.net/'

## Configuration
#
# config file format is as follows
# ; example ~/.yummy.cfg file
# [yummy]
# user = delicious-user-name
# pass = delicious-password
# ; source_url is your public shared items feed url from Google Reader
# source_url = http://www.google.com/reader/public/atom/user/../broadcast
# ; end of config file
config_file = os.path.expanduser('~/.yummy.cfg')

# If state file doesn't exist, it will be created
state_file = os.path.expanduser('~/.yummy.state')

# Set to logging.DEBUG for debug messages
LOG_LEVEL = logging.INFO

# End configuration

class Post(object):
    """Class to model a del.icio.us Post. It limits attributes 
    to a retricted subset, i.e. those used in a del.icio.us post."""

    __slots__ = ['description', 'url', 'extended', 'tags']

    def __contains__(self, key):
        try:
            getattr(self, key)
        except:
            return False
        return True

    # urllib.urlencode() just needs this beyond the basic stuff above
    def items(self):
        return [(k, getattr(self, k).encode('utf-8')) 
                        for k in self.__slots__ if k in self]

def posts(feed):
    """Iterates over a Feedparser feed object and returns Posts.
    Tailored for greader shared items feed to return title,
    link and annotation."""

    for entry in feed.entries:
        d = Post()
        d.description = entry.title
        d.url = entry.link
        d.tags = "linker via:greader" # TODO: this should be configurable
        for content in entry.content:
            if content.base.startswith(
                    'http://www.google.com/reader/public/atom/user/'):
                d.extended = content.value

        yield d

class Yummy(object):
    _endpoint = 'https://api.del.icio.us/v1/posts/add?'

    def __init__(self, statefile, source_url, user, pw):
        """`statefile` is where data about which items have already been
        posted to delicious is saved.
        `source_url` is the Google Reader feed url from which to pick items
        `user` is the delicious user name
        `pw` is the delicious password
        """

        self._store = statefile
        try:
            self._processed = pickle.load(open(statefile))
        except:
            logging.error('Error loading state file: %s' % statefile)
            self._processed = set()

        self._source_url = source_url

        pass_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        pass_mgr.add_password(None, 'api.del.icio.us', user, pw)
        handler = urllib2.HTTPBasicAuthHandler(pass_mgr)
        opener = urllib2.build_opener(handler)
        opener.addheaders = [('User-Agent', 
                       'yummy - greader->delicious poster (%s)' % __version__)]
        urllib2.install_opener(opener)

    def update(self):
        """Updates delicious with posts sourced from source_url"""

        logging.debug('fetching source feed')
        feed = feedparser.parse(self._source_url)
        logging.debug('fetched feed. it has %s entries' % len(feed.entries))

        for post in posts(feed):
            if post.url in self._processed:
                logging.debug('Skipping already processed URL: %s' % post.url)
                continue

            params = urllib.urlencode(post)
            logging.debug('Posting url: %s' % self._endpoint + params)
            try:
                response = urllib2.urlopen(self._endpoint + params)
                xml = ET.parse(response)
            except urllib2.HTTPError, exc:
                logging.error('HTTPError: %d' % (exc.code))
            except urllib2.URLError, exc:
                logging.error('URL error' % str(exc))
            else:
                result = xml.getroot()
                logging.debug('response is: %s: %s' % 
                                    (result.tag, result.get('code')))

                if result.get('code') == 'done':
                    self._processed.add(post.url)
                else:
                    logging.error('Error posting to delicious.' \
                            'Response was: %s' % result.get('code'))
            
            # delicious folks require us to wait a second between requests
            time.sleep(1)

        # Done processing feed. Save state to data store before returning
        logging.debug('Done processing all urls in feed')
        f = open(self._store, 'w')
        pickle.dump(self._processed, f)
        f.close()

if __name__ == '__main__':
    logging.basicConfig(level=LOG_LEVEL)

    config = ConfigParser.ConfigParser()
    if not config.read(config_file):
        logging.error('Could not read config file: %s' % config_file)
        sys.exit(1)

    username = config.get('yummy', 'user')
    password = config.get('yummy', 'pass')
    source_url = config.get('yummy', 'source_url')

    y = Yummy(state_file, source_url, username, password)
    y.update()
