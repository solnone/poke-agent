import requests
import re

r = requests.get('https://localhost.psim.us/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
r.raise_for_status()
html = r.text

# Replace protocol-relative URLs with https://
html = html.replace('src="//', 'src="https://')
html = html.replace('href="//', 'href="https://')
html = html.replace("src='//", "src='https://")
html = html.replace("href='//", "href='https://")

# Replace framebust
old_framebust = """<script>
	// framebust - see https://owasp.org/www-pdf-archive/OWASP_AppSec_Research_2010_Busting_Frame_Busting_by_Rydstedt.pdf
	// should be robust against reflective XSS filters and navigation interception
	var app;
	if (self === top) {
		app = new App();
	} else {
		LM.innerHTML += ' IN FRAME<br />Please visit Showdown directly.';
		top.location = self.location;
	}
</script>"""

new_framebust = """<script>
	var app = new App();
</script>"""

if old_framebust in html:
    html = html.replace(old_framebust, new_framebust)
    print("Exact match replaced!")
else:
    # Use regex
    html = re.sub(
        r'// framebust.*?(var app;.*?top\.location = self\.location;\s*\})',
        'var app = new App();',
        html,
        flags=re.DOTALL
    )
    print("Regex replaced!")

# Ensure Config.server is pointing to localhost:8000
# We inject right after config.js
target_script = '<script src="https://play.pokemonshowdown.com/config/config.js?27a14913"></script>'
server_inject = """<script src="https://play.pokemonshowdown.com/config/config.js?27a14913"></script>
<script>
	Config.server = {
		id: 'localhost',
		host: 'localhost',
		port: 8000,
		httpport: 8000,
		altport: 80,
		registered: false
	};
</script>"""

if target_script in html:
    html = html.replace(target_script, server_inject)
    print("Config.server injected after config.js!")
else:
    # Regex search for config.js
    html = re.sub(
        r'<script src="https://play\.pokemonshowdown\.com/config/config\.js[^"]*"></script>',
        lambda _: server_inject,
        html
    )
    print("Config.server injected via regex!")

with open('showdown_client.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Saved showdown_client.html successfully! Size:", len(html))
