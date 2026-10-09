import urllib.request
import json
import time

for i in range(12):
    time.sleep(20)
    url = 'https://api.github.com/repos/OndrejVas/SuggestInvest/actions/runs?per_page=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.0'})
    r = urllib.request.urlopen(req)
    d = json.loads(r.read())
    run = d['workflow_runs'][0]
    elapsed = (i + 1) * 20
    print('[' + str(elapsed) + 's] Status: ' + str(run['status']) + ' | Conclusion: ' + str(run['conclusion']))
    if run['status'] == 'completed':
        print('DONE! Conclusion: ' + str(run['conclusion']))
        break
