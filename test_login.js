// Test pure JS SHA-256 implementation
function pureJsSha256(ascii) {
    function rightRotate(value, amount) { return (value>>>amount) | (value<<(32 - amount)); }
    var mathPow = Math.pow;
    var maxWord = mathPow(2, 32);
    var lengthProperty = 'length';
    var i, j;
    var result = '';
    var words = [];
    var asciiBitLength = ascii[lengthProperty]*8;
    var hash = [];
    var k = [];
    var primeCounter = 0;
    var isComposite = {};
    for (var candidate = 2; primeCounter < 64; candidate++) {
        if (!isComposite[candidate]) {
            for (i = 0; i < 313; i += candidate) { isComposite[i] = candidate; }
            hash[primeCounter] = (mathPow(candidate, .5)*maxWord)|0;
            k[primeCounter++] = (mathPow(candidate, 1/3)*maxWord)|0;
        }
    }
    ascii += '\x80';
    while (ascii[lengthProperty]%64 - 56) ascii += '\x00';
    for (i = 0; i < ascii[lengthProperty]; i++) {
        j = ascii.charCodeAt(i);
        if (j>>8) return '';
        words[i>>2] |= j << ((3 - i)%4)*8;
    }
    words[words[lengthProperty]] = ((asciiBitLength/maxWord)|0);
    words[words[lengthProperty]] = (asciiBitLength);
    for (j = 0; j < words[lengthProperty];) {
        var w = words.slice(j, j += 16);
        var oldHash = hash.slice(0);
        for (i = 0; i < 64; i++) {
            var w15 = w[i - 15], w2 = w[i - 2];
            var a = hash[0], e = hash[4];
            var temp1 = hash[7]
                + (rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25))
                + ((e & hash[5]) ^ ((~e) & hash[6]))
                + k[i]
                + (w[i] = (i < 16) ? w[i] : (
                        w[i - 16]
                        + (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15>>>3))
                        + w[i - 7]
                        + (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2>>>10))
                    )|0
                );
            var temp2 = (rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22))
                + ((a & hash[1]) ^ (a & hash[2]) ^ (hash[1] & hash[2]));
            hash = [(temp1 + temp2)|0].concat(hash);
            hash[4] = (hash[4] + temp1)|0;
        }
        for (i = 0; i < 8; i++) { hash[i] = (hash[i] + oldHash[i])|0; }
    }
    for (i = 0; i < 8; i++) {
        for (j = 3; j + 1; j--) {
            var b = (hash[i]>>(j*8))&255;
            result += ((b < 16) ? 0 : '') + b.toString(16);
        }
    }
    return result;
}

const VALID_USER_HASHES = [
    '5bff2c944e58c4b622bceab6c3794bdb49180603a080cb995acad9d136719d44',
    '493f0daa919d6a985ddcc9185d7a08378104833630911da73bd660d2a4a11621',
    '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918',
    '89903dfa383d1be0969942af5d088a81b1592c3b3dde153aa1dc5e2207d8835c'
];

const VALID_PASS_HASHES = [
    'cb68425cfebe32bacd9b3cb624a1b99a033037eb12f9dd57c59765db0f4cf262',
    'f4bf4f16dc2d4536e70c93f6b249c24c1311792b3b2c1b79e642bba343ccbb8d',
    '4b6dc495eaaaba459d7e748c89b8ac22e1b5ad8874d66897813e8691abc0b169',
    'ef962684145f39eecf6e8bd0ab37bbfebf5a5e89040c9c576538c96884a0509c'
];

// Compute actual hashes
const testUsers = ['SuggestInvest', 'suggestinvest', 'admin', 'ondrej'];
const testPasses = ['WeWillMakeMoney!', 'WeWillMakeMoney', 'wewillmakemoney!', 'wewillmakemoney'];

console.log('=== USER HASHES ===');
testUsers.forEach(function(u) {
    var h = pureJsSha256(u);
    var ok = VALID_USER_HASHES.includes(h);
    console.log((ok ? 'OK  ' : 'FAIL') + ' ' + u + ' => ' + h);
});

console.log('');
console.log('=== PASS HASHES ===');
testPasses.forEach(function(p) {
    var h = pureJsSha256(p);
    var ok = VALID_PASS_HASHES.includes(h);
    console.log((ok ? 'OK  ' : 'FAIL') + ' ' + p + ' => ' + h);
});

console.log('');
console.log('=== LOGIN SIMULATION ===');

function simulateLogin(rawUser, rawPass) {
    var uHash = pureJsSha256(rawUser.trim());
    var pHash = pureJsSha256(rawPass);
    var userNorm = rawUser.trim().toLowerCase();
    var passNorm = rawPass.trim().toLowerCase();

    var isUserValid = VALID_USER_HASHES.includes(uHash) ||
        ['suggestinvest', 'admin', 'ondrej'].includes(userNorm);

    var isPassValid = VALID_PASS_HASHES.includes(pHash) ||
        ['wewillmakemoney!', 'wewillmakemoney'].includes(passNorm);

    return { isUserValid: isUserValid, isPassValid: isPassValid, success: isUserValid && isPassValid };
}

var tests = [
    ['SuggestInvest', 'WeWillMakeMoney!'],
    ['suggestinvest', 'WeWillMakeMoney!'],
    ['SuggestInvest', 'WeWillMakeMoney'],
    ['admin', 'WeWillMakeMoney!'],
    ['ondrej', 'WeWillMakeMoney!'],
    ['wrong', 'wrong'],
    ['SuggestInvest', 'wrongpass'],
];

tests.forEach(function(pair) {
    var u = pair[0], p = pair[1];
    var res = simulateLogin(u, p);
    console.log((res.success ? 'LOGIN OK  ' : 'LOGIN FAIL') + ' | user=' + u + ' pass=' + p + ' | userOK=' + res.isUserValid + ' passOK=' + res.isPassValid);
});
