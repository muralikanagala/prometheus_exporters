#!/usr/bin/env python

import json
import os
import requests

from flask import Flask
from flask import Response
from flask import abort
from flask import request


class AzureHealth:
    def __init__(self, target):
        self.all_metrics = []
        self.health_metrics = []
        self.resp_code = ''
        self.resp_msg = ''

        self.auth_url = 'http://169.254.169.254/metadata/identity/oauth2/token'
        self.auth_params = {'api-version': '2018-02-01', 'resource': 'https://management.azure.com/'}
        self.auth_header = {'Metadata': 'true'}
        self.health_url = 'https://management.azure.com/subscriptions/' + target + '/providers/Microsoft.ResourceHealth/availabilityStatuses'
        self.health_params = {'api-version': '2017-07-01'}

    def log(self, lev, *data):
        for item in data:
            if lev == 'd':
                print 'Debug: ' + str(item)
            elif lev == 'e':
                print 'Error: ' + str(item)
            elif lev == 'i':
                print 'Info: ' + str(item)

    def getData(self, url, params={}, headers={}):
        self.log('d', 'Hitting api:', url)
        try:
            r = requests.get(url, headers=headers, params=params)
            output = r.content
            self.resp_code = str(r.status_code)
            self.resp_msg = str(r.reason)
            if not r.ok:
                self.log('e', 'Failed to get data from ' + url, r.status_code)
                output = ''
        except requests.exceptions.ConnectionError as e:
            self.log('e', 'Failed to get data from ' + url, e)
            self.resp_code = 404
            self.resp_msg = 'Failed to establish a new connection'
            output = ''
        try:
            data = json.loads(output)
        except ValueError:
            data = {}
            pass
        return data

    def metricFormat(self, met_name, met_val, labels={}):
        if isinstance(met_val, list):
            met_val = len(met_val)
        if isinstance(met_val, bool):
            met_val = int(met_val)
        entry = 'azure_resource_health_' + met_name
        i = 1
        labels_len = len(labels)
        for k, v in labels.iteritems():
            if i == 1:
                entry = entry + '{'
            entry = entry + ('%s="%s"' % (k, str(v)))
            if i != labels_len:
                entry = entry + ','
            else:
                entry = entry + '} '
            i = i + 1
        return entry + ' ' + str(met_val)

    def health_parser(self):
        token_data = self.getData(self.auth_url, self.auth_params, self.auth_header)
        if len(token_data) > 0:
            token = token_data['access_token']

            health_header = {
                'Authorization': 'Bearer ' + token
            }
            health_data = self.getData(self.health_url, self.health_params, health_header)
            if len(health_data) > 0:
                for item in health_data['value']:
                    prop = item['properties']
                    state = prop.get('availabilityState')

                    if state:
                        if state == 'Available':
                            val = 0
                        elif state == 'Degraded':
                            val = 1
                        elif state == 'Unavailable':
                            val = 2
                        elif state == 'Unknown':
                            val = 3
                    else:
                        val = 4
                    raw_met = {
                        'state': val
                    }
                    labels = {
                        'resourcegroup': item['id'].split('/')[4],
                        'resourcetype': item['id'].split('/')[7],
                        'resource': item['id'].split('/')[8],
                        'region': item['location'].title().replace('us', 'US')
                    }
                    for k, v in raw_met.iteritems():
                        if v is not None:
                            self.health_metrics.append(self.metricFormat(k, v, labels))

    def up_parser(self):
        labels = {
            "response_code": self.resp_code,
            "response_message": self.resp_msg
        }
        if len(self.all_metrics) == 0:
            self.all_metrics.append(self.metricFormat('up', 0, labels))
        else:
            self.all_metrics.append(self.metricFormat('up', 1, labels))

    def collector(self):
        help_text = '# State to Value mapping: 0-Healthy, 1-Degraded, 2-Unavailable, 3-Unknown, 4-Failed'
        self.health_parser()
        self.all_metrics = self.health_metrics
        self.up_parser()
        self.all_metrics.sort()
        self.all_metrics.insert(0, help_text)
        return "\n".join(self.all_metrics)


app = Flask("Azure Health Status")


@app.route('/metrics', methods=['GET'])
def getMetrics():
    target = request.args.get('target')
    if target is None:
        abort(400, "Target parameter is required")
    metrics = AzureHealth(target)
    return Response(metrics.collector(), mimetype='text/plain')


if __name__ == '__main__':
    if os.environ.get("PUBLISH_PORT") is not None:
        port = os.environ["PUBLISH_PORT"]
    else:
        port = 10500

    app.run(host='0.0.0.0', threaded=True, debug=False, port=port)
