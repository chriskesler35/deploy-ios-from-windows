# deploy-ios-from-windows — Claude Context

This is a Python/Flask wizard that guides Windows users through deploying an iOS `.ipa` to the Apple App Store using a GitHub Actions macOS runner — no Mac required.

## How it works

Five phases: generate certificates (Phase 1) → Apple Developer Portal setup (Phase 2) → GitHub secrets (Phase 3) → generate workflow YAML (Phase 4) → publish GitHub release to trigger deploy (Phase 5).

The actual signing and upload happens on a GitHub-hosted macOS runner via `Apple-Actions/upload-testflight-build@v1`.

## Key constraints

- **Certificate + provisioning profile must be a matched pair.** The `.p12` and `.mobileprovision` must both reference the same Apple Distribution certificate. If they don't match, Apple rejects the upload with "Invalid Code Signing — must be signed with the certificate in the provisioning profile."
- **Apple limits iOS Distribution certificates to 2 per account.** Check before generating a new one in Phase 1.
- **Profiles and certs are NOT committed to git** (`profiles/` and `certs/` are gitignored). If moving to a new PC, run the wizard from Phase 1 to generate a fresh matched set.
- **The workflow triggers on GitHub Release published**, not on push. Publishing the release is what kicks off signing and upload.
- **Builds land in TestFlight first**, not the App Store tab. App Store Connect → TestFlight → iOS Builds. Processing takes 5–60 minutes.

## Known issues fixed

- Old generated workflows were missing the `mv signed.ipa release.ipa` line — the signed file was never renamed before upload
- Old generated workflows were missing the `Upload to App Store Connect` step entirely — fixed in `app.py`
- Generated workflow now fails fast with a clear error if the Apple Distribution identity is not found in the keychain
- Generated workflow now prints both the installed certificate and the certificate embedded in the provisioning profile so mismatches are immediately visible in the Actions log
- Generated workflow now runs `codesign --verify --deep --strict` after signing to catch bad signatures before repacking

## Active project: Alpine Advisor

- Bundle ID: `com.base69e0c4bdd31bdu8fda51775g.app`
- GitHub repo: `chriskesler35/alpine-advisor-final`
- App binary name: `WixOneApp.app` (Wix Studio internal name)
- Status: certificate mismatch blocking upload — needs full Phase 1–4 re-run to generate matched cert/profile set
- Original cert files are on the original PC; if working from a different PC, start from Phase 1
