import urllib.request, sys

req = urllib.request.Request('https://ondrejvas.github.io/SuggestInvest/scalping.html', headers={'User-Agent': 'curl/7.0'})
r = urllib.request.urlopen(req, timeout=15)
content = r.read().decode('utf-8', errors='replace')

overlay_pos = content.find('loginOverlay')
auth_pos = content.find('handleLoginSubmit')
app_pos = content.find('appContainer')

out = sys.stdout
sys.stdout = open('check_live_out.txt', 'w', encoding='utf-8')

print('loginOverlay at: ' + str(overlay_pos))
print('handleLoginSubmit at: ' + str(auth_pos))
print('appContainer at: ' + str(app_pos))
print('Auth BEFORE appContainer: ' + str(auth_pos < app_pos))
print('')

ctx = content[app_pos-300:app_pos+300]
print('=== Context around appContainer ===')
print(ctx)

sys.stdout.close()
sys.stdout = out
print('Done - output written to check_live_out.txt')
