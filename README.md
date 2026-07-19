# Deploy iOS Apps to the App Store from Windows

A step-by-step web wizard that walks you through everything needed to publish an iOS app to the Apple App Store — entirely from a Windows machine. No Mac required for the setup process.

> **Who is this for?**  
> Developers using tools like [Base44](https://base44.com), Draftbit, or any platform that exports a ready-made `.ipa` file, who need to get that app into the App Store without owning a Mac.

---

## How it works

The wizard guides you through 5 phases:

| Phase | What happens |
|-------|-------------|
| **1 — Certificates** | Generates your private key, CSR, and `.p12` certificate bundle using OpenSSL via Git Bash |
| **2 — App Setup** | Walks you through creating your App ID, provisioning profile, and App Store Connect API key on Apple's portal |
| **3 — GitHub Secrets** | Encodes your certificate and keys as Base64 and helps you add them as GitHub Actions secrets |
| **4 — Workflow** | Generates a `ios-deploy.yml` GitHub Actions workflow file tailored to your app |
| **5 — Release** | Uploads your `.ipa` to a GitHub Release, which automatically triggers the workflow to re-sign and submit it to App Store Connect |

The actual signing and upload to Apple happens on a **GitHub-hosted macOS runner** — so you never need a Mac locally.

---

## Prerequisites

Before you start, make sure you have the following installed on your Windows machine:

### Required
- **Python 3.9+** — [python.org/downloads](https://www.python.org/downloads/)
- **Git for Windows** — [git-scm.com](https://git-scm.com/) *(includes Git Bash and OpenSSL)*
- **GitHub CLI** (`gh`) — [cli.github.com](https://cli.github.com/) *(for the release upload step)*

### Required accounts
- **Apple Developer account** ($99/year) — [developer.apple.com](https://developer.apple.com)
- **GitHub account** — [github.com](https://github.com)

### Your app
- A compiled `.ipa` file from your app builder (Base44, Draftbit, etc.)
- Your app's **Bundle ID** (e.g. `com.yourcompany.yourapp`)

---

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/chriskesler35/deploy-ios-from-windows.git
cd deploy-ios-from-windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the wizard
python app.py
```

Then open your browser at **http://localhost:5000**

> **Windows users:** You can also double-click `Start-Server.bat` instead of running the commands above — it handles everything automatically.

---

## Phase-by-phase guide

### Phase 1 — Certificates

The wizard uses **OpenSSL via Git Bash** to generate your iOS distribution certificate. Git Bash must be installed at its default path (`C:\Program Files\Git`).

Steps handled automatically:
1. Generate a 2048-bit RSA private key
2. Create a Certificate Signing Request (CSR)
3. *(Manual)* Upload the CSR to the [Apple Developer Portal](https://developer.apple.com/account/resources/certificates/list) → choose **Apple Distribution** → download the `.cer`
4. Upload the `.cer` to the wizard — it converts it to `.pem`
5. Bundle everything into a `.p12` file *(you choose a strong password — save it, you'll need it)*

---

### Phase 2 — App Setup (Apple Developer Portal)

Three manual steps in [developer.apple.com](https://developer.apple.com):

1. **App ID** — Register your Bundle ID under *Identifiers*
2. **Provisioning Profile** — Create an *App Store Distribution* profile using your App ID and certificate, then download and upload it to the wizard
3. **App Store Connect API Key** — Go to [App Store Connect → Users & Access → Integrations](https://appstoreconnect.apple.com/access/integrations/api) → create a key with *App Manager* role → download the `.p8` file and note the Key ID and Issuer ID

---

### Phase 3 — GitHub Secrets

The wizard encodes your sensitive files as Base64 and tells you exactly which secrets to add to your GitHub repo under **Settings → Secrets and variables → Actions**:

| Secret name | Value |
|-------------|-------|
| `BUILD_CERTIFICATE_BASE64` | Your `.p12` file, Base64 encoded |
| `P12_PASSWORD` | The password you chose in Phase 1 |
| `BUILD_PROVISION_PROFILE_BASE64` | Your `.mobileprovision` file, Base64 encoded |
| `KEYCHAIN_PASSWORD` | Any strong random string (used temporarily on the runner) |
| `APPSTORE_ISSUER_ID` | From your App Store Connect API key |
| `APPSTORE_KEY_ID` | From your App Store Connect API key |
| `APPSTORE_P8` | Full contents of your `.p8` file |

---

### Phase 4 — GitHub Actions Workflow

The wizard generates a `ios-deploy.yml` file customised for your app. You need to commit it to your repo at exactly this path:

```
.github/workflows/ios-deploy.yml
```

**Important:** The file must be committed to your repo's **default branch** (usually `main`) before it will run.

The workflow:
- Triggers on `release: published`
- Downloads the `.ipa` from the GitHub Release assets
- Installs your certificate and provisioning profile on a macOS runner
- Re-signs the `.ipa` with your Apple Distribution certificate
- Uploads the signed build to App Store Connect

---

### Phase 5 — Create a GitHub Release

Upload your `.ipa` file as a GitHub Release asset. Publishing the release triggers the workflow automatically.

> **Tip:** If the in-app upload hangs for large files, go to your GitHub repo → Releases → Edit the release → drag and drop the `.ipa` directly onto the assets area. This is faster and more reliable for large files.

Each future app update just needs a new GitHub Release with the updated `.ipa` — the workflow handles signing and submission automatically.

---

## After the workflow runs

1. **Check the Actions tab** in your GitHub repo to confirm the workflow succeeded
2. **Open App Store Connect** → your app → *TestFlight → iOS Builds* — the build will appear within 5–60 minutes as Apple processes it
3. **Submit for review** — go to the App Store tab, select the build, complete your listing (screenshots, description, keywords), and click *Submit for Review*
4. Apple's review typically takes **24–48 hours** for new apps

---

## Troubleshooting

**"No event triggers defined in `on`"**  
YAML treats `on` as a reserved word. The generated workflow uses `"on":` (quoted) to avoid this — make sure you're using the latest downloaded version of `ios-deploy.yml`.

**"Tag already exists" when creating a release**  
Each release needs a unique tag. Use `v1.0.1`, `v1.0.2`, etc. — you can't reuse a tag that already exists on GitHub.

**"The user name or passphrase you entered is not correct"**  
The `P12_PASSWORD` GitHub secret doesn't match the password used when creating the `.p12`. Re-run the `.p12` step in Phase 1 with a new password and update the secret.

**Workflow file not triggering**  
Make sure `ios-deploy.yml` is committed to the **root default branch** of your repo at `.github/workflows/ios-deploy.yml` (note the leading dot on `.github`).

**Build not appearing in App Store Connect**  
Processing can take up to 60 minutes. Apple will send a confirmation email when the build is ready. Check **App Store Connect → TestFlight → iOS Builds** (not the App Store tab — builds land in TestFlight first). If it never arrives, check the GitHub Actions logs for upload errors in the "Upload to App Store Connect" step. Apple also sends a separate email if a build is rejected during processing (e.g. invalid signature) — check both inbox and spam.

**Workflow completes but nothing reaches App Store Connect**  
The most common cause is a missing upload step. Open your `.github/workflows/ios-deploy.yml` and confirm the final step is:
```yaml
      - name: Upload to App Store Connect
        uses: Apple-Actions/upload-testflight-build@v1
        with:
          app-path: release.ipa
          issuer-id: ${{ secrets.APPSTORE_ISSUER_ID }}
          api-key-id: ${{ secrets.APPSTORE_KEY_ID }}
          api-private-key: ${{ secrets.APPSTORE_P8 }}
```
If it's missing, regenerate the workflow from Phase 4 and recommit.

**"Signing with:" is blank in the Actions log**  
No Apple Distribution certificate was found in the keychain. The generated workflow now fails fast with a clear error if this happens. Common causes: `BUILD_CERTIFICATE_BASE64` secret is malformed (re-encode the `.p12` in Phase 3), or `P12_PASSWORD` doesn't match the password set in Phase 1.

**"CFBundleShortVersionString must contain a higher version than the previously approved version"**  
The app builder (Wix, Base44, etc.) generates the same version string every time, so Apple rejects subsequent uploads. The generated workflow now automatically patches `CFBundleShortVersionString` and `CFBundleVersion` in `Info.plist` using your GitHub Release tag before re-signing. Use a new tag like `v1.1.0` for each release — the workflow strips the leading `v` and sets the version to `1.1.0`. Tags must always increase (e.g. `v1.0.0` → `v1.1.0` → `v1.2.0`).

**"Invalid Code Signing — must be signed with the certificate in the provisioning profile"**  
The certificate you signed with (your `.p12`) and the certificate embedded in your provisioning profile don't match — they must be a paired set. To fix: go to [developer.apple.com](https://developer.apple.com) → Profiles → open your App Store Distribution profile and check which certificate it uses. If it's not your current certificate, create a new profile selecting your Apple Distribution certificate from Phase 1, download it, re-encode it via Phase 3, and update the `BUILD_PROVISION_PROFILE_BASE64` GitHub secret. The generated workflow now prints both certificate names in the "Install certificate" step so you can spot the mismatch immediately in the Actions log.

---

## App data and privacy

The wizard stores your app configuration (bundle ID, repo name, email) in a local `profiles/` folder and your generated certificates in `certs/`. Neither folder is committed to git. Do not share these folders — they contain your private signing keys.

---

## Contributing

Pull requests welcome. If you hit an issue not covered here, open a GitHub Issue with the error message and which phase you were in.
