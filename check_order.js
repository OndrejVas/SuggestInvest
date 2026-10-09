const fs = require('fs');
const h = fs.readFileSync('index.html', 'utf8');

// Find positions of key elements
var items = [
    ['loginOverlay (div)', h.indexOf('<div id="loginOverlay"')],
    ['loginOverlay (script tag opens)', h.indexOf('<script>', h.indexOf('<div id="loginOverlay"'))],
    ['handleLoginSubmit function', h.indexOf('function handleLoginSubmit')],
    ['appContainer (first)', h.indexOf('<div id="appContainer"')],
];

items.sort(function(a, b) { return a[1] - b[1]; });
console.log('=== index.html KEY ELEMENTS IN ORDER ===');
items.forEach(function(item) {
    console.log('  Char ' + item[1] + ': ' + item[0]);
});

// Print the snippet around loginOverlay to see ordering
var overlayPos = h.indexOf('<div id="loginOverlay"');
console.log('\n=== Context around loginOverlay (chars ' + (overlayPos-50) + ' to ' + (overlayPos+500) + ') ===');
console.log(h.substring(overlayPos - 50, overlayPos + 500));
