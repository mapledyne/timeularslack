import datetime
import logging

import azure.functions as func

import os
import requests
import random
import ftfy

from functools import wraps
from slackclient import SlackClient

def slack_status_emoji(status):
    if (status == "Mystery"):
        return random.choice([':leopard:',
                              ':pear:',
                              ':sparkles:',
                              ':blossom:',
                              ':lollipop:',
                              ':candy:'])
    return {
        'Lunch': ':sandwich:',
        'Meeting': ':man-man-girl-girl:',
        'Office': ':office:',
        'Out of Office': ':bike:',
        'Phone': ':telephone_receiver:'
    }.get(status, ":question:")


def random_status():
    # return random.choice(['CAPS LOCK - preventing logins since 1980',
    #                         'Enter any 11-digit prime number to continue',
    #                         'A bad random number generator: 1, 1, 1, 1, 1, 4.33e+67, 1, 1, 1...',
    #                         'A core dump is your computer\'s way of saying "Here\'s what\'s on my mind, what\'s on yours?"',
    #                         'Behind every good computer... is a jumble of wires \'n stuff.',
    #                         'Error: Keyboard not attached. Press F1 to continue.'])
    url = 'https://icanhazdadjoke.com/'
    headers = {'user-agent': 'slack-updater michael@mapledyne.com', 'Accept': 'text/plain'}

    r = requests.get(url, headers=headers)
    return ftfy.fix_text(r.text) + " (icanhazdadjoke.com)"


def slack_status_text(status):
    if (status == "Mystery"):
        return random_status()
    return {
        'Lunch': 'Eating lunch. Om nom nom.',
        'Meeting': 'At a meeting.',
        'Office': 'In the office or nearby.',
        'Out of Office': 'Out of office.',
        'Phone': 'On the phone.'
    }.get(status, "Status goes here")


def check_token(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if self._access_token == None:
            return False
        return f(self, *args, **kwargs)

    return wrapper


def get_current_time():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]



class API(object):
    _METHODS = ['get', 'post', 'patch', 'delete']
    _CLASS_STATUS_CODES = (200, 226) # https://en.wikipedia.org/wiki/List_of_HTTP_status_codes#2xx_Success

    _access_token = None
    _base_url = None

    def __init__(self, base_url, access_token=None):
        self._base_url = base_url
        self._access_token = access_token

    def _make_response(self, route='', method='get', json={}, need_auth=True, headers={}):
        if method not in self._METHODS:
            print('[%s] is not allowed' % method)
            return False
        url = self._base_url + route
        if need_auth:
            headers['Authorization'] = 'Bearer ' + self._access_token
        response = getattr(requests, method)(url, json=json, headers=headers)
        if response.status_code < self._CLASS_STATUS_CODES[0] or response.status_code > self._CLASS_STATUS_CODES[1]:
            print('code error: %d' % response.status_code)
            print('_make_response error for url [%s]: %s' % (url, response.text))
            return False
        return response.json()


class Timeular(API):
    activities = None
    devices = None
    tracking = None
    time_entries = None
    _api_key = None
    _api_secret = None

    def __init__(self, base_url='https://api.timeular.com/api/v2', api_key='', api_secret=''):
        super(Timeular, self).__init__(base_url)
        self._api_key = api_key
        self._api_secret = api_secret
        if not self.get_access_token():
            raise ValueError('Check base_url and the route to get your access token')
        self.activities = Activities(base_url, self._access_token)
        self.devices = Devices(base_url, self._access_token)
        self.tracking = Tracking(base_url, self._access_token)

    def set_api_key(self, api_key):
        self._api_key = api_key

    def set_api_secret(self, api_secret):
        self._api_secret = api_secret

    def get_access_token(self):
        result = self._make_response('/developer/sign-in', method="post", json={'apiKey': self._api_key, 'apiSecret': self._api_secret}, need_auth=False)
        if not result:
            return False
        self._access_token = result['token']
        return result


class Activities(API):
    _BASE_URL = '/activities'

    def __init__(self, base_url, access_token):
        super(Activities, self).__init__(base_url + self._BASE_URL, access_token)

    @check_token
    def get(self):
        return self._make_response()


class Devices(API):
    _BASE_URL = '/devices'

    def __init__(self, base_url, access_token):
        super(Devices, self).__init__(base_url + self._BASE_URL, access_token)

    @check_token
    def get(self):
        return self._make_response()

class Tracking(API):
    _BASE_URL = '/tracking'

    def __init__(self, base_url, access_token):
        super(Tracking, self).__init__(base_url + self._BASE_URL, access_token)

    @check_token
    def get(self):
        return self._make_response()



def main(mytimer: func.TimerRequest) -> None:
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    ## Only fires if a scheduled run was missed or similar. Not generally interesting in this case:
    # if mytimer.past_due:
    #     logging.info('The timer is past due!')

    config = {}
    config['TIMEULAR_KEY'] = os.environ.get('TIMEULAR_KEY')
    config['TIMEULAR_SECRET'] = os.environ.get('TIMEULAR_SECRET')
    config['SLACK_API_TOKEN'] = os.environ.get('SLACK_API_TOKEN')
            
    # very simple validation for expected env variables:    
    for c in config:
        if config[c] is None:
            logging.error('Environment variable {} not found.'.format(c))
            return

    api = Timeular(api_key=config['TIMEULAR_KEY'], api_secret=config['TIMEULAR_SECRET'])

    tracking = api.tracking.get()['currentTracking']
    activity = tracking['activity']
    activity_name = activity['name']

    sc = SlackClient(config['SLACK_API_TOKEN'])
    new_status = slack_status_text(activity_name)
    new_emoji = slack_status_emoji(activity_name)
    logging.info('Setting Slack status to "{} => {}" at {}'.format(new_emoji, new_status, utc_timestamp))
    sc.api_call("users.profile.set", profile={"status_text": new_status,"status_emoji": new_emoji})
