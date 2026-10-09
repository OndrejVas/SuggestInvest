const fs = require('fs');

function checkFile(filename) {
    const content = fs.readFileSync(filename, 'utf8');
    const authPos = content.indexOf('handleLoginSubmit');
    const overlayPos = content.indexOf('loginOverlay');
    const appPos = content.indexOf('appContainer');
    const totalLen = content.length;
    
    console.log('=== ' + filename + ' ===');
    console.log('Size: ' + Math.round(totalLen/1024) + ' KB');
    console.log('loginOverlay at: ' + overlayPos + ' (' + Math.round(overlayPos/totalLen*100) + '%)');
    console.log('handleLoginSubmit at: ' + authPos + ' (' + Math.round(authPos/totalLen*100) + '%)');
    console.log('appContainer at: ' + appPos + ' (' + Math.round(appPos/totalLen*100) + '%)');
    console.log('Auth BEFORE appContainer: ' + (authPos < appPos ? 'YES OK' : 'NO PROBLEM!'));
    console.log('');
}

checkFile('index.html');
checkFile('trading.html');
checkFile('scalping.html');

// Also validate all scripts syntax
['index.html', 'trading.html', 'scalping.html'].forEach(function(filename) {
    var html = fs.readFileSync(filename, 'utf8');
    var matches = [];
    var re = /<script[\s\S]*?>([\s\S]*?)<\/script>/gi;
    var m;
    while ((m = re.exec(html)) !== null) {
        matches.push(m[1]);
    }
    var allOk = true;
    matches.forEach(function(src, idx) {
        try {
            new Function(src);
        } catch(e) {
            console.log(filename + ' Script ' + idx + ' SYNTAX ERROR: ' + e.message);
            allOk = false;
        }
    });
    if (allOk) {
        console.log(filename + ': All ' + matches.length + ' scripts OK');
    }
});
