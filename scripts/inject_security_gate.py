"""
Injects the unified SuggestInvest SHA-256 Security Gate into specified HTML pages.
Ensures zero FOUC, persistent session/local storage auth, and consistent visual styling.
"""

import os
import re

AUTH_HEAD_SNIPPET = """    <!-- 🔒 SUGGESTINVEST SECURITY GATE INITIALIZER -->
    <script>
        (function() {
            try {
                var isAuth = sessionStorage.getItem("si_authenticated") === "true" || localStorage.getItem("si_authenticated") === "true";
                if (isAuth) {
                    document.documentElement.classList.add("si-authenticated");
                } else {
                    document.documentElement.classList.add("si-locked");
                }
            } catch(e) {}
        })();
    </script>
    <style>
        /* 🔒 SECURITY GATE STYLES */
        html.si-locked #appContainer { display: none !important; }
        html.si-locked #loginOverlay { display: flex !important; }
        html.si-authenticated #loginOverlay { display: none !important; }
        html.si-authenticated #appContainer { display: block !important; }

        #loginOverlay {
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            background: radial-gradient(circle at center, #111827 0%, #030712 100%);
            display: flex; align-items: center; justify-content: center;
            z-index: 999999; padding: 1.5rem;
        }
        .login-card {
            background: rgba(17, 24, 39, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 18px;
            padding: 2.5rem 2rem;
            max-width: 430px; width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            text-align: center;
        }
        .login-badge {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(59, 130, 246, 0.15); color: #60a5fa;
            padding: 4px 12px; border-radius: 9999px;
            font-size: 0.75rem; font-weight: 700;
            letter-spacing: 0.05em; text-transform: uppercase;
            border: 1px solid rgba(59, 130, 246, 0.3); margin-bottom: 1.25rem;
        }
        .login-title {
            font-size: 1.65rem; font-weight: 800; color: #f9fafb;
            margin-bottom: 0.35rem; letter-spacing: -0.01em;
        }
        .login-subtitle {
            font-size: 0.88rem; color: #9ca3af;
            margin-bottom: 1.75rem; line-height: 1.4;
        }
        .login-form {
            display: flex; flex-direction: column; gap: 1.1rem; text-align: left;
        }
        .form-group { display: flex; flex-direction: column; gap: 0.35rem; }
        .input-label { font-size: 0.8rem; font-weight: 600; color: #cbd5e1; }
        .login-input {
            width: 100%; background: #0b0f19;
            border: 1px solid rgba(255, 255, 255, 0.15); color: #f8fafc;
            padding: 0.75rem 1rem; border-radius: 8px; font-size: 0.95rem;
            outline: none; transition: border-color 0.2s, box-shadow 0.2s; box-sizing: border-box;
        }
        .login-input:focus {
            border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
        }
        .remember-row {
            display: flex; align-items: center; gap: 8px;
            font-size: 0.82rem; color: #9ca3af; cursor: pointer; user-select: none;
        }
        .login-submit-btn {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff; border: none; padding: 0.8rem;
            border-radius: 8px; font-size: 0.95rem; font-weight: 700;
            cursor: pointer; transition: transform 0.15s, box-shadow 0.15s; margin-top: 0.4rem;
        }
        .login-submit-btn:hover {
            transform: translateY(-1px); box-shadow: 0 10px 20px -5px rgba(37, 99, 235, 0.5);
        }
        .login-error {
            display: none; background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171;
            padding: 0.65rem; border-radius: 6px; font-size: 0.82rem; text-align: center;
        }
        #appContainer { display: none; }
    </style>
"""

AUTH_OVERLAY_HTML = """    <!-- 🔒 UNIFIED SECURITY GATE OVERLAY -->
    <div id="loginOverlay">
        <div class="login-card">
            <div class="login-badge">
                <span>🔒 SuggestInvest • Security Gate</span>
            </div>
            <h2 class="login-title">Přihlášení</h2>
            <p class="login-subtitle">Zadejte přihlašovací údaje pro přístup do ekosystému SuggestInvest.</p>
            
            <form class="login-form" onsubmit="handleLoginSubmit(event)">
                <div class="form-group">
                    <label class="input-label" for="loginUser">Uživatelské jméno</label>
                    <input type="text" id="loginUser" class="login-input" placeholder="Zadejte uživatelské jméno" required autocomplete="username">
                </div>

                <div class="form-group">
                    <label class="input-label" for="loginPass">Heslo</label>
                    <input type="password" id="loginPass" class="login-input" placeholder="Zadejte heslo" required autocomplete="current-password">
                </div>

                <label class="remember-row">
                    <input type="checkbox" id="rememberMe" checked>
                    <span>Zapamatovat přihlášení na tomto zařízení</span>
                </label>

                <div id="loginError" class="login-error">
                    Neplatné uživatelské jméno nebo heslo. Zkuste to znovu.
                </div>

                <button type="submit" class="login-submit-btn">Vstoupit do aplikace</button>
            </form>
        </div>
    </div>
"""

AUTH_BODY_SCRIPT = """    <!-- 🔒 SECURITY AUTH CONTROLLER (SHA-256) -->
    <script>
        const VALID_USER_HASHES = [
            "5bff2c944e58c4b622bceab6c3794bdb49180603a080cb995acad9d136719d44",
            "493f0daa919d6a985ddcc9185d7a08378104833630911da73bd660d2a4a11621",
            "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
            "89903dfa383d1be0969942af5d088a81b1592c3b3dde153aa1dc5e2207d8835c"
        ];

        const VALID_PASS_HASHES = [
            "cb68425cfebe32bacd9b3cb624a1b99a033037eb12f9dd57c59765db0f4cf262",
            "f4bf4f16dc2d4536e70c93f6b249c24c1311792b3b2c1b79e642bba343ccbb8d",
            "4b6dc495eaaaba459d7e748c89b8ac22e1b5ad8874d66897813e8691abc0b169",
            "ef962684145f39eecf6e8bd0ab37bbfebf5a5e89040c9c576538c96884a0509c"
        ];

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
            ascii += '\\x80';
            while (ascii[lengthProperty]%64 - 56) ascii += '\\x00';
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

        async function computeSHA256(text) {
            try {
                if (window.crypto && window.crypto.subtle && window.isSecureContext) {
                    const encoder = new TextEncoder();
                    const data = encoder.encode(text);
                    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
                    const hashArray = Array.from(new Uint8Array(hashBuffer));
                    return hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
                }
            } catch(e) {}
            return pureJsSha256(text);
        }

        function checkAuthStatus() {
            var isAuth = false;
            try {
                isAuth = sessionStorage.getItem("si_authenticated") === "true" || localStorage.getItem("si_authenticated") === "true";
            } catch(e) {}

            var overlay = document.getElementById("loginOverlay");
            var app = document.getElementById("appContainer");

            if (isAuth) {
                document.documentElement.classList.add("si-authenticated");
                document.documentElement.classList.remove("si-locked");
                if (overlay) overlay.style.display = "none";
                if (app) app.style.display = "block";
            } else {
                document.documentElement.classList.remove("si-authenticated");
                document.documentElement.classList.add("si-locked");
                if (overlay) overlay.style.display = "flex";
                if (app) app.style.display = "none";
            }
        }

        async function handleLoginSubmit(e) {
            if (e && e.preventDefault) e.preventDefault();
            var userEl = document.getElementById("loginUser");
            var passEl = document.getElementById("loginPass");
            var remEl = document.getElementById("rememberMe");
            var errEl = document.getElementById("loginError");

            var rawUser = (userEl ? userEl.value : "").trim();
            var rawPass = passEl ? passEl.value : "";
            var remember = remEl ? remEl.checked : true;

            var userNorm = rawUser.toLowerCase();
            var passNorm = rawPass.trim().toLowerCase();

            var uHash = await computeSHA256(rawUser);
            var uHashNorm = await computeSHA256(userNorm);
            var isUserValid = VALID_USER_HASHES.includes(uHash) || VALID_USER_HASHES.includes(uHashNorm);

            var pHash = await computeSHA256(rawPass);
            var pHashNorm = await computeSHA256(passNorm);
            var isPassValid = VALID_PASS_HASHES.includes(pHash) || VALID_PASS_HASHES.includes(pHashNorm);

            if (isUserValid && isPassValid) {
                if (errEl) errEl.style.display = "none";
                try {
                    if (remember) {
                        localStorage.setItem("si_authenticated", "true");
                        localStorage.setItem("si_user", rawUser);
                    }
                    sessionStorage.setItem("si_authenticated", "true");
                    sessionStorage.setItem("si_user", rawUser);
                } catch(e) {}
                checkAuthStatus();
            } else {
                if (errEl) errEl.style.display = "block";
                if (passEl) {
                    passEl.value = "";
                    passEl.focus();
                }
            }
            return false;
        }

        function logout() {
            try {
                sessionStorage.removeItem("si_authenticated");
                localStorage.removeItem("si_authenticated");
                sessionStorage.removeItem("si_user");
                localStorage.removeItem("si_user");
            } catch(e) {}
            document.documentElement.classList.remove("si-authenticated");
            document.documentElement.classList.add("si-locked");
            window.location.reload();
        }

        checkAuthStatus();
        document.addEventListener("DOMContentLoaded", checkAuthStatus);
    </script>
"""

def inject_security_gate_into_file(filepath):
    if not os.path.isfile(filepath):
        print(f"Skipping non-existent: {filepath}")
        return False
    
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    # Skip if already injected
    if 'id="loginOverlay"' in html or 'VALID_PASS_HASHES' in html:
        print(f"Already protected: {filepath}")
        return False

    # 1. Insert into <head>
    head_match = re.search(r'</head>', html, re.IGNORECASE)
    if not head_match:
        print(f"No </head> tag found in {filepath}")
        return False
    
    head_idx = head_match.start()
    html = html[:head_idx] + AUTH_HEAD_SNIPPET + "\n" + html[head_idx:]

    # 2. Insert overlay after <body> and wrap body content in #appContainer
    body_match = re.search(r'<body[^>]*>', html, re.IGNORECASE)
    if not body_match:
        print(f"No <body> tag found in {filepath}")
        return False
    
    body_end_idx = body_match.end()
    
    # Find </body>
    closing_body_match = re.search(r'</body>', html, re.IGNORECASE)
    if not closing_body_match:
        print(f"No </body> tag found in {filepath}")
        return False
    
    closing_body_idx = closing_body_match.start()
    
    inner_body = html[body_end_idx:closing_body_idx]
    
    wrapped_inner_body = f"\n{AUTH_OVERLAY_HTML}\n    <div id=\"appContainer\">\n{inner_body}\n    </div>\n{AUTH_BODY_SCRIPT}\n"
    
    new_html = html[:body_end_idx] + wrapped_inner_body + html[closing_body_idx:]
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"Successfully injected security gate into: {filepath}")
    return True

def post_process_page(filepath):
    if not os.path.isfile(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    modified = False

    # 1. Hub.html: normalize links & add logout button
    if os.path.basename(filepath) == "hub.html":
        content = content.replace('http://localhost:8000/SilverInvestDemo.html', 'SilverInvestDemo.html')
        content = re.sub(r'href="/([a-zA-Z0-9_\-\.]+)"', r'href="\1"', content)
        
        # Add Logout button next to SilverEdge button if not already present
        if '🚪 Odhlásit' not in content:
            logout_btn = """<div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <a href="SilverInvestDemo.html" style="text-decoration:none;" class="filter-pill">
                🥈 Otevřít SilverEdge V3.0 ➔
            </a>
            <button onclick="logout()" class="filter-pill" style="border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; background: rgba(239, 68, 68, 0.12); cursor: pointer;" title="Odhlásit se ze systému SuggestInvest">
                🚪 Odhlásit
            </button>
        </div>"""
            content = re.sub(r'<div>\s*<a href="SilverInvestDemo\.html"[^>]*>[\s\S]*?</a>\s*</div>', logout_btn, content)
        modified = True

    # 2. FutureInvestDemo.html: add static fallback to data/future_invest_demo_state.json
    elif os.path.basename(filepath) == "FutureInvestDemo.html":
        if 'data/future_invest_demo_state.json' not in content:
            # Replace loadData() fetch
            old_fetch = 'const res = await fetch("/api/future_invest/data");'
            new_fetch = """let res;
        try {
            res = await fetch("/api/future_invest/data");
            if (!res.ok) throw new Error("API not available");
        } catch(apiErr) {
            res = await fetch("data/future_invest_demo_state.json?t=" + Date.now());
        }"""
            if old_fetch in content:
                content = content.replace(old_fetch, new_fetch)
                modified = True

    # 3. system_status.html: make data/system_report.json relative
    elif os.path.basename(filepath) == "system_status.html":
        if 'fetch("/data/system_report.json' in content:
            content = content.replace('fetch("/data/system_report.json', 'fetch("data/system_report.json')
            modified = True

    # 4. SilverInvestDemo.html: fallback to static json
    elif os.path.basename(filepath) == "SilverInvestDemo.html":
        if 'data/silver_walkforward_manifest.json' not in content:
            old_mf = "const res = await fetch('/api/silver/walkforward-manifest');"
            new_mf = """let res;
            try {
                res = await fetch('/api/silver/walkforward-manifest');
                if (!res.ok) throw new Error();
            } catch(e) {
                res = await fetch('data/silver_walkforward_manifest.json?t=' + Date.now());
            }"""
            if old_mf in content:
                content = content.replace(old_mf, new_mf)
                modified = True

        if 'data/high_alpha_silver_telemetry.json' not in content:
            old_telem = "const res = await fetch('/api/silver/telemetry');"
            new_telem = """let res;
            try {
                res = await fetch('/api/silver/telemetry');
                if (!res.ok) throw new Error();
            } catch(e) {
                res = await fetch('data/high_alpha_silver_telemetry.json?t=' + Date.now());
            }"""
            if old_telem in content:
                content = content.replace(old_telem, new_telem)
                modified = True

    if modified:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Post-processed adjustments for: {filepath}")

if __name__ == "__main__":
    targets = [
        "hub.html",
        "FutureInvestDemo.html",
        "SilverInvestDemo.html",
        "system_status.html",
        "argon_results_2026.html",
        "silver_results_2026.html",
        "argon_audit.html",
        "backtest.html",
        "scalping_v2.html",
        "pages.html",
        "sitemap.html"
    ]
    for t in targets:
        inject_security_gate_into_file(t)
        post_process_page(t)
