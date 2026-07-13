import os
import json
import subprocess
import base64
import shutil
import requests as http
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

BASE_DIR     = Path(__file__).parent
PROFILES_DIR = BASE_DIR / 'profiles'
CERTS_DIR    = BASE_DIR / 'certs'

PROFILES_DIR.mkdir(exist_ok=True)
CERTS_DIR.mkdir(exist_ok=True)

GITBASH_PATHS = [
    r'C:\Program Files\Git\bin\bash.exe',
    r'C:\Program Files (x86)\Git\bin\bash.exe',
]
GITBASH = next((p for p in GITBASH_PATHS if Path(p).exists()), None)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ── Helpers ───────────────────────────────────────────────────────────────────

def profile_path(app_id):
    return PROFILES_DIR / f'{app_id}.json'

def load_profile(app_id):
    p = profile_path(app_id)
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return None

def save_profile(profile):
    profile_path(profile['appId']).write_text(
        json.dumps(profile, indent=2), encoding='utf-8'
    )

def work_dir(app_id):
    d = CERTS_DIR / app_id
    d.mkdir(exist_ok=True)
    return d

def run_openssl(cmd, cwd):
    if not GITBASH:
        return False, 'Git Bash not found. Install Git for Windows from https://git-scm.com'
    bash_cwd = str(cwd).replace('\\', '/')
    result = subprocess.run(
        [GITBASH, '-c', f"cd '{bash_cwd}' && unset OPENSSL_CONF && {cmd}"],
        capture_output=True, text=True
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output

def step_done(profile, key):
    return profile.get('stepsComplete', {}).get(key, False)

def mark_step(profile, key):
    if 'stepsComplete' not in profile:
        profile['stepsComplete'] = {}
    profile['stepsComplete'][key] = True
    save_profile(profile)

def count_progress(profile):
    keys = [
        'p1_key', 'p1_csr', 'p1_cer', 'p1_pem', 'p1_p12',
        'p2_appid', 'p2_profile', 'p2_apikey',
        'p3_p12_secret', 'p3_profile_secret', 'p3_other_secrets',
        'p4_yaml', 'p5_release',
    ]
    done = sum(1 for k in keys if step_done(profile, k))
    return done, len(keys)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({'gitbash': bool(GITBASH), 'gitbash_path': GITBASH or ''})

@app.route('/api/profiles', methods=['GET'])
def list_profiles():
    profiles = []
    for f in PROFILES_DIR.glob('*.json'):
        try:
            p = json.loads(f.read_text(encoding='utf-8'))
            done, total = count_progress(p)
            profiles.append({**p, '_done': done, '_total': total})
        except Exception:
            pass
    return jsonify(profiles)

@app.route('/api/profiles', methods=['POST'])
def create_profile():
    data = request.json
    required = ['appName', 'bundleId', 'devEmail', 'githubRepo']
    for field in required:
        if not data.get(field, '').strip():
            return jsonify({'error': f'Missing field: {field}'}), 400

    app_id = ''.join(c if c.isalnum() or c == '_' else '_' for c in data['appName']).lower()
    if load_profile(app_id):
        return jsonify({'error': f'A profile named "{app_id}" already exists.'}), 409

    wd = work_dir(app_id)
    profile = {
        'appId':        app_id,
        'appName':      data['appName'].strip(),
        'bundleId':     data['bundleId'].strip(),
        'devName':      '',
        'devEmail':     data['devEmail'].strip(),
        'githubRepo':   data['githubRepo'].strip(),
        'workDir':      str(wd),
        'stepsComplete': {},
    }
    save_profile(profile)
    return jsonify(profile), 201

@app.route('/api/profiles/<app_id>', methods=['GET'])
def get_profile(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    done, total = count_progress(p)
    return jsonify({**p, '_done': done, '_total': total})

@app.route('/api/profiles/<app_id>/mark', methods=['POST'])
def mark_step_route(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    key = request.json.get('step')
    if not key:
        return jsonify({'error': 'Missing step key'}), 400
    mark_step(p, key)
    return jsonify({'ok': True})

# ── Phase 1 endpoints ─────────────────────────────────────────────────────────

@app.route('/api/<app_id>/p1/genkey', methods=['POST'])
def p1_genkey(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    wd = Path(p['workDir'])
    ok, out = run_openssl('openssl genrsa -out ios_distribution.key 2048', wd)
    if ok:
        mark_step(p, 'p1_key')
    return jsonify({'ok': ok, 'output': out})

@app.route('/api/<app_id>/p1/gencsr', methods=['POST'])
def p1_gencsr(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    dev_name = (request.json or {}).get('devName', '').strip() or p.get('devName', '')
    if not dev_name:
        return jsonify({'error': 'Developer full name is required'}), 400
    p['devName'] = dev_name
    save_profile(p)
    wd   = Path(p['workDir'])
    subj = f"/emailAddress={p['devEmail']}/CN={dev_name}/C=US"
    cmd  = (
        f"MSYS_NO_PATHCONV=1 openssl req -new -key ios_distribution.key "
        f"-out CertificateSigningRequest.certSigningRequest "
        f"-subj \"{subj}\""
    )
    ok, out = run_openssl(cmd, wd)
    if ok:
        mark_step(p, 'p1_csr')
    csr_path = str(wd / 'CertificateSigningRequest.certSigningRequest')
    return jsonify({'ok': ok, 'output': out, 'csrPath': csr_path if ok else None})

@app.route('/api/<app_id>/p1/download-csr')
def p1_download_csr(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    csr = Path(p['workDir']) / 'CertificateSigningRequest.certSigningRequest'
    if not csr.exists():
        return jsonify({'error': 'CSR not generated yet'}), 404
    return send_file(csr, as_attachment=True)

@app.route('/api/<app_id>/p1/upload-cer', methods=['POST'])
def p1_upload_cer(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    dest = Path(p['workDir']) / 'ios_distribution.cer'
    f.save(dest)
    mark_step(p, 'p1_cer')
    return jsonify({'ok': True, 'filename': dest.name})

@app.route('/api/<app_id>/p1/convertpem', methods=['POST'])
def p1_convertpem(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    wd  = Path(p['workDir'])
    cmd = 'openssl x509 -in ios_distribution.cer -inform DER -out ios_distribution.pem -outform PEM'
    ok, out = run_openssl(cmd, wd)
    if ok:
        mark_step(p, 'p1_pem')
    return jsonify({'ok': ok, 'output': out})

@app.route('/api/<app_id>/p1/makep12', methods=['POST'])
def p1_makep12(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    password = request.json.get('password', '').strip()
    if not password:
        return jsonify({'error': 'Password is required'}), 400
    wd  = Path(p['workDir'])
    cmd = (
        f"openssl pkcs12 -export "
        f"-inkey ios_distribution.key "
        f"-in ios_distribution.pem "
        f"-out ios_distribution.p12 "
        f"-passout pass:\"{password}\""
    )
    ok, out = run_openssl(cmd, wd)
    if ok:
        mark_step(p, 'p1_p12')
    return jsonify({'ok': ok, 'output': out})

# ── Phase 2 endpoints ─────────────────────────────────────────────────────────

@app.route('/api/<app_id>/p2/mark-appid', methods=['POST'])
def p2_mark_appid(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    mark_step(p, 'p2_appid')
    return jsonify({'ok': True})

@app.route('/api/<app_id>/p2/upload-profile', methods=['POST'])
def p2_upload_profile(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    dest = Path(p['workDir']) / f.filename
    f.save(dest)
    p['mpFilename'] = f.filename
    save_profile(p)
    mark_step(p, 'p2_profile')
    return jsonify({'ok': True, 'filename': f.filename})

@app.route('/api/<app_id>/p2/save-apikey', methods=['POST'])
def p2_save_apikey(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    if 'file' not in request.files:
        return jsonify({'error': 'No .p8 file uploaded'}), 400
    data = request.form
    issuer_id = data.get('issuerId', '').strip()
    key_id    = data.get('keyId', '').strip()
    if not issuer_id or not key_id:
        return jsonify({'error': 'Issuer ID and Key ID are required'}), 400
    f = request.files['file']
    dest = Path(p['workDir']) / f.filename
    f.save(dest)
    p['issuerId']   = issuer_id
    p['keyId']      = key_id
    p['p8Filename'] = f.filename
    save_profile(p)
    mark_step(p, 'p2_apikey')
    return jsonify({'ok': True})

# ── Phase 3 endpoints ─────────────────────────────────────────────────────────

@app.route('/api/<app_id>/p3/encode/<file_type>')
def p3_encode(app_id, file_type):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    wd = Path(p['workDir'])

    if file_type == 'p12':
        target = wd / 'ios_distribution.p12'
        step   = 'p3_p12_secret'
    elif file_type == 'profile':
        mp_name = p.get('mpFilename', '')
        target  = wd / mp_name if mp_name else None
        if not target:
            hits = list(wd.glob('*.mobileprovision'))
            target = hits[0] if hits else None
        step = 'p3_profile_secret'
    elif file_type == 'p8':
        p8_name = p.get('p8Filename', '')
        target  = wd / p8_name if p8_name else None
        step    = None
    else:
        return jsonify({'error': 'Unknown file type'}), 400

    if not target or not target.exists():
        return jsonify({'error': f'File not found: {target}'}), 404

    if file_type == 'p8':
        content = target.read_text(encoding='utf-8')
        return jsonify({'ok': True, 'content': content, 'type': 'text'})

    encoded = base64.b64encode(target.read_bytes()).decode('ascii')
    if step:
        mark_step(p, step)
    return jsonify({'ok': True, 'content': encoded, 'type': 'base64'})

@app.route('/api/<app_id>/p3/mark-secrets', methods=['POST'])
def p3_mark_secrets(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    mark_step(p, 'p3_other_secrets')
    return jsonify({'ok': True})

# ── Phase 4 endpoints ─────────────────────────────────────────────────────────

@app.route('/api/<app_id>/p4/yaml')
def p4_yaml(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404

    app_name = p['appName']

    yaml = f"""name: Deploy {app_name} to App Store

"on":
  release:
    types: [published]

jobs:
  deploy-ios:
    runs-on: macos-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Download IPA from GitHub Release
        env:
          GH_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
        run: |
          gh release download "${{{{ github.ref_name }}}}" \\
            --pattern "*.ipa" \\
            --output release.ipa

      - name: Install certificate and provisioning profile
        env:
          BUILD_CERTIFICATE_BASE64: ${{{{ secrets.BUILD_CERTIFICATE_BASE64 }}}}
          P12_PASSWORD: ${{{{ secrets.P12_PASSWORD }}}}
          BUILD_PROVISION_PROFILE_BASE64: ${{{{ secrets.BUILD_PROVISION_PROFILE_BASE64 }}}}
          KEYCHAIN_PASSWORD: ${{{{ secrets.KEYCHAIN_PASSWORD }}}}
        run: |
          CERTIFICATE_PATH=$RUNNER_TEMP/build_certificate.p12
          PP_PATH=$RUNNER_TEMP/build_pp.mobileprovision
          KEYCHAIN_PATH=$RUNNER_TEMP/app-signing.keychain-db

          echo -n "$BUILD_CERTIFICATE_BASE64" | base64 --decode -o $CERTIFICATE_PATH
          echo -n "$BUILD_PROVISION_PROFILE_BASE64" | base64 --decode -o $PP_PATH

          security create-keychain -p "$KEYCHAIN_PASSWORD" $KEYCHAIN_PATH
          security set-keychain-settings -lut 21600 $KEYCHAIN_PATH
          security unlock-keychain -p "$KEYCHAIN_PASSWORD" $KEYCHAIN_PATH
          security import $CERTIFICATE_PATH -P "$P12_PASSWORD" -A -t cert -f pkcs12 -k $KEYCHAIN_PATH
          security list-keychain -d user -s $KEYCHAIN_PATH

          echo "== Installed certificate =="
          security find-identity -v -p codesigning

          echo "== Certificate embedded in provisioning profile =="
          security cms -D -i "$PP_PATH" 2>/dev/null | grep -A1 "CN=" | grep "CN=" | sed 's/.*CN=/  CN=/' || echo "  (unable to parse)"
          echo "== If the names above do not match, the upload will fail with certificate mismatch =="

          mkdir -p ~/Library/MobileDevice/Provisioning\\ Profiles
          cp $PP_PATH ~/Library/MobileDevice/Provisioning\\ Profiles

          # Store provisioning profile UUID for re-signing
          echo "PP_PATH=$PP_PATH" >> $GITHUB_ENV

      - name: Re-sign IPA with your Apple Distribution certificate
        env:
          BUNDLE_ID: {p['bundleId']}
        run: |
          # Unpack the IPA
          mkdir -p resign_work
          cp release.ipa resign_work/original.zip
          cd resign_work && unzip -q original.zip -d unpacked

          APP_PATH=$(find unpacked/Payload -maxdepth 1 -name "*.app" | head -1)
          echo "App path: $APP_PATH"

          # Set CFBundleShortVersionString from the release tag (strip leading v), e.g. v2.1.0 -> 2.1.0
          # This MUST be higher than the previously approved version in App Store Connect
          INFO_PLIST="$APP_PATH/Info.plist"
          TAG="${{{{ github.ref_name }}}}"
          MARKETING_VERSION="${{TAG#v}}"
          /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $MARKETING_VERSION" "$INFO_PLIST"
          echo "CFBundleShortVersionString set to $MARKETING_VERSION"

          # Bump CFBundleVersion to the GitHub run number (must increase with every upload)
          /usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${{{{ github.run_number }}}}" "$INFO_PLIST"
          echo "CFBundleVersion set to ${{{{ github.run_number }}}}"

          # Remove old signature
          rm -rf "$APP_PATH/_CodeSignature"

          # Embed new provisioning profile
          cp "$PP_PATH" "$APP_PATH/embedded.mobileprovision"

          # Get signing identity from keychain
          echo "Available signing identities:"
          security find-identity -v -p codesigning
          IDENTITY=$(security find-identity -v -p codesigning | grep "Apple Distribution" | head -1 | awk -F'"' '{{print $2}}')
          echo "Signing with: $IDENTITY"
          if [ -z "$IDENTITY" ]; then
            echo "ERROR: No Apple Distribution certificate found in keychain."
            echo "Check your BUILD_CERTIFICATE_BASE64 and P12_PASSWORD secrets."
            exit 1
          fi

          # Extract entitlements from the provisioning profile
          ENTITLEMENTS_PATH=$RUNNER_TEMP/entitlements.plist
          security cms -D -i "$PP_PATH" | plutil -extract Entitlements xml1 - -o "$ENTITLEMENTS_PATH"
          echo "Entitlements extracted from provisioning profile"

          # Re-sign frameworks first, then the app
          find "$APP_PATH/Frameworks" -name "*.framework" -exec codesign --force --sign "$IDENTITY" {{}} \; 2>/dev/null || true
          find "$APP_PATH/PlugIns" -name "*.appex" -exec codesign --force --sign "$IDENTITY" {{}} \; 2>/dev/null || true
          codesign --force --sign "$IDENTITY" --entitlements "$ENTITLEMENTS_PATH" "$APP_PATH"

          # Verify the signature before repacking
          codesign --verify --deep --strict "$APP_PATH" && echo "Signature verified successfully" || {{ echo "ERROR: Signature verification failed!"; exit 1; }}

          # Repack as IPA
          cd unpacked && zip -qr ../../signed.ipa Payload
          cd ../.. && mv signed.ipa release.ipa

      - name: Upload to App Store Connect
        uses: Apple-Actions/upload-testflight-build@v1
        with:
          app-path: release.ipa
          issuer-id: ${{{{ secrets.APPSTORE_ISSUER_ID }}}}
          api-key-id: ${{{{ secrets.APPSTORE_KEY_ID }}}}
          api-private-key: ${{{{ secrets.APPSTORE_P8 }}}}
"""
    out_path = Path(p['workDir']) / 'ios-deploy.yml'
    out_path.write_text(yaml, encoding='utf-8')
    mark_step(p, 'p4_yaml')
    return jsonify({'ok': True, 'yaml': yaml, 'path': str(out_path)})

@app.route('/api/<app_id>/p4/download-yaml')
def p4_download_yaml(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    f = Path(p['workDir']) / 'ios-deploy.yml'
    if not f.exists():
        return jsonify({'error': 'YAML not generated yet'}), 404
    return send_file(f, as_attachment=True, download_name='ios-deploy.yml')

# ── Phase 5 endpoints — GitHub Releases ───────────────────────────────────────

def gh_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

@app.route('/api/<app_id>/p5/validate-token', methods=['POST'])
def p5_validate_token(app_id):
    token = request.json.get('token', '').strip()
    if not token:
        return jsonify({'error': 'Token is required'}), 400
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404

    # Verify token has repo access by fetching the repo
    owner, repo = p['githubRepo'].split('/', 1)
    r = http.get(
        f'https://api.github.com/repos/{owner}/{repo}',
        headers=gh_headers(token), timeout=10
    )
    if r.status_code == 200:
        data = r.json()
        return jsonify({'ok': True, 'repo': data.get('full_name'), 'private': data.get('private')})
    elif r.status_code == 404:
        return jsonify({'error': 'Repository not found — check the repo name and token permissions.'}), 400
    elif r.status_code == 401:
        return jsonify({'error': 'Token is invalid or expired.'}), 400
    else:
        return jsonify({'error': f'GitHub API error: {r.status_code}'}), 400

@app.route('/api/<app_id>/p5/list-releases')
def p5_list_releases(app_id):
    token = request.args.get('token', '').strip()
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    owner, repo = p['githubRepo'].split('/', 1)
    r = http.get(
        f'https://api.github.com/repos/{owner}/{repo}/releases',
        headers=gh_headers(token), timeout=10
    )
    if r.status_code != 200:
        return jsonify({'error': f'GitHub API error: {r.status_code}'}), 400
    releases = [
        {'id': rel['id'], 'tag': rel['tag_name'], 'name': rel['name'],
         'url': rel['html_url'], 'assets': len(rel['assets']),
         'created': rel['created_at'][:10]}
        for rel in r.json()
    ]
    return jsonify({'ok': True, 'releases': releases})

@app.route('/api/<app_id>/p5/create-release', methods=['POST'])
def p5_create_release(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404

    token   = request.form.get('token', '').strip()
    tag     = request.form.get('tag', '').strip()
    title   = request.form.get('title', '').strip() or tag
    notes   = request.form.get('notes', '').strip()

    if not token or not tag:
        return jsonify({'error': 'Token and version tag are required'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'No .ipa file uploaded'}), 400

    ipa_file = request.files['file']
    if not ipa_file.filename.endswith('.ipa'):
        return jsonify({'error': 'File must be a .ipa'}), 400

    owner, repo = p['githubRepo'].split('/', 1)

    # 1. Create the release
    rel_resp = http.post(
        f'https://api.github.com/repos/{owner}/{repo}/releases',
        headers=gh_headers(token),
        json={'tag_name': tag, 'name': title or tag,
              'body': notes or f'Release {tag}',
              'draft': False, 'prerelease': False},
        timeout=15
    )
    if rel_resp.status_code not in (200, 201):
        body = rel_resp.json()
        err  = body.get('message', str(rel_resp.status_code))
        if rel_resp.status_code == 422:
            err = (f'Tag "{tag}" already exists on GitHub. '
                   'Choose a different version tag (e.g. v1.0.1) or delete the existing release first.')
        return jsonify({'error': f'Failed to create release: {err}'}), 400

    release      = rel_resp.json()
    release_id   = release['id']
    release_url  = release['html_url']
    upload_url   = release['upload_url'].split('{')[0]  # strip URI template

    # 2. Save .ipa to a temp file then stream it to GitHub to avoid buffering in memory
    import tempfile, shutil
    ipa_name = ipa_file.filename
    with tempfile.NamedTemporaryFile(delete=False, suffix='.ipa') as tmp:
        ipa_file.save(tmp)
        tmp_path = tmp.name

    try:
        with open(tmp_path, 'rb') as f:
            up_resp = http.post(
                f'{upload_url}?name={ipa_name}',
                headers={**gh_headers(token), 'Content-Type': 'application/octet-stream'},
                data=f,
                timeout=600
            )
    finally:
        import os; os.unlink(tmp_path)
    if up_resp.status_code not in (200, 201):
        err = up_resp.json().get('message', str(up_resp.status_code))
        return jsonify({'error': f'Release created but .ipa upload failed: {err}',
                        'releaseUrl': release_url}), 400

    asset     = up_resp.json()
    asset_url = asset.get('browser_download_url', '')

    # Save release history to profile
    if 'releases' not in p:
        p['releases'] = []
    p['releases'].insert(0, {
        'tag': tag, 'title': title, 'url': release_url,
        'ipaName': ipa_name, 'assetUrl': asset_url
    })
    mark_step(p, 'p5_release')
    return jsonify({'ok': True, 'releaseUrl': release_url, 'assetUrl': asset_url, 'tag': tag})

@app.route('/api/<app_id>/p5/releases-history')
def p5_releases_history(app_id):
    p = load_profile(app_id)
    if not p:
        return jsonify({'error': 'Profile not found'}), 404
    return jsonify({'releases': p.get('releases', [])})

if __name__ == '__main__':
    print('iOS App Store Wizard running at http://localhost:5000')
    app.run(debug=True, port=5000, use_reloader=True)
