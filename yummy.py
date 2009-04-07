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
__version__     = '0.2'
__copyright__   = '(c) 2008 Deepak Sarda'
__license__     = 'Public Domain'
__url__         = 'http://antrix.net/'

## Configuration
#
# config file format is as follows
# ; example ~/.yummy.cfg file
# [yummy]
# ; source_url is your public shared items feed url from Google Reader
# source_url = http://www.google.com/reader/public/atom/user/../broadcast
# [delicious]
# user = delicious-user-name
# pass = delicious-password
# [twitter]
# user = twitter-user-name
# pass = twitter-password
# ; end of config file
config_file = os.path.expanduser('~/.yummy.cfg')

# If state file doesn't exist, it will be created
state_file_prefix = os.path.expanduser('~/.yummy.state')

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

    def __str__(self):
        return self.url

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

# TODO: Refactor Delicious & Twitter classes to have 
# common base-class with save_state() related details
# moved to base-class

class Delicious(object):
    _endpoint = 'https://api.del.icio.us/v1/posts/add?'

    def __init__(self, user, pw):
        """`user` is the delicious user name
        `pw` is the delicious password
        """
        pass_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        pass_mgr.add_password(None, 'api.del.icio.us', user, pw)
        handler = urllib2.HTTPBasicAuthHandler(pass_mgr)
        self._opener = urllib2.build_opener(handler)
        self._opener.addheaders = [('User-Agent', 
                       'yummy - greader->delicious poster (%s)' % __version__)]

        self._store = state_file_prefix + '.delicious'
        try:
            self._processed = pickle.load(open(self._store))
        except:
            logging.error('Error loading state file: %s' % self._store)
            self._processed = set()

    def save_state(self):
        f = open(self._store, 'w')
        pickle.dump(self._processed, f)
        f.close()

    def update(self, post):
        """Updates delicious with the `post`"""

        if post.url in self._processed:
            logging.debug('Skipping already processed URL: %s' % post.url)
            return True

        params = urllib.urlencode(post)
        logging.debug('Posting url: %s' % self._endpoint + params)

        try:
            response = self._opener.open(self._endpoint + params)
            xml = ET.parse(response)
        except urllib2.HTTPError, exc:
            logging.error('HTTPError: %d' % (exc.code))
            return False
        except urllib2.URLError, exc:
            logging.error('URL error' % str(exc))
            return False
        except Exception:
            logging.error('Unknown exception', exc_info=True)
            return False
        else:
            result = xml.getroot()
            logging.debug('response is: %s: %s' % 
                                (result.tag, result.get('code')))

            if result.get('code') == 'done':
                self._processed.add(post.url)
                return True
            else:
                logging.error('Error posting to delicious.' \
                        'Response was: %s' % result.get('code'))
                return False
            
class Twitter(object):
    _endpoint = 'https://twitter.com/statuses/update.xml'

    def __init__(self, user, pw):
        """`user` is the delicious user name
        `pw` is the delicious password
        """
        pass_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        pass_mgr.add_password(None, 'twitter.com', user, pw)
        handler = urllib2.HTTPBasicAuthHandler(pass_mgr)
        self._opener = urllib2.build_opener(handler)
        self._opener.addheaders = [('User-Agent', 
                       'yummy - greader->twitter poster (%s)' % __version__)]

        self._store = state_file_prefix + '.twitter'
        try:
            self._processed = pickle.load(open(self._store))
        except:
            logging.error('Error loading state file: %s' % self._store)
            self._processed = set()

    def save_state(self):
        f = open(self._store, 'w')
        pickle.dump(self._processed, f)
        f.close()

    def update(self, post):
        """Updates twitter with the `post`"""

        if post.url in self._processed:
            logging.debug('Skipping already processed URL: %s' % post.url)
            return True
        
        if not post.extended:
            status = u"%s %s" % (post.description, post.url)
        else:
            status = u"%s. %s %s" % (post.description, post.extended, post.url)

        params = urllib.urlencode({'status': status, 'source': 'yummy'})

        logging.debug('Posting url: %s' % self._endpoint + '?' + params)

        try:
            response = self._opener.open(self._endpoint, params)
            response = response.read()
        except urllib2.HTTPError, exc:
            logging.error('HTTPError: %d' % (exc.code))
            return False
        except urllib2.URLError, exc:
            logging.error('URL error' % str(exc))
            return False
        except Exception:
            logging.error('Unknown exception', exc_info=True)
            return False
        else:
            if 'created_at' in response:
                self._processed.add(post.url)
                return True
            else:
                logging.error('Error posting to twitter.' \
                        'Response was: %s' % response)
                return False

class Yummy(object):
    def __init__(self, source_url, services):
        """
        `source_url` is the Google Reader feed url from which to pick items
        `services` is a list of objects with an `update` method
        """
        self._source_url = source_url
        self._services = services

    def update(self):
        """Updates services with posts sourced from source_url"""

        logging.debug('fetching source feed')
        feed = feedparser.parse(self._source_url)
        logging.debug('fetched feed. it has %s entries' % len(feed.entries))

        for post in posts(feed):
            for service in self._services:
                logging.debug('Calling service %s for item %s' % (service.__class__.__name__, post))
                try:
                    resp = service.update(post)
                except:
                    logging.error('Service %s failed posting item %s' % (service.__class__.__name__, post))
            
            time.sleep(1)

        # Done processing feed. Save state to data store before returning
        logging.debug('Done processing all urls in feed')

        for service in self._services:
            service.save_state()

if __name__ == '__main__':
    logging.basicConfig(level=LOG_LEVEL)

    config = ConfigParser.ConfigParser()
    if not config.read(config_file):
        logging.error('Could not read config file: %s' % config_file)
        sys.exit(1)

    source_url = config.get('yummy', 'source_url')

    del_username = config.get('delicious', 'user')
    del_password = config.get('delicious', 'pass')

    twit_username = config.get('twitter', 'user')
    twit_password = config.get('twitter', 'pass')

    delicious = Delicious(del_username, del_password)
    twitter = Twitter(twit_username, twit_password)

    y = Yummy(source_url, (delicious, twitter))
    y.update()
