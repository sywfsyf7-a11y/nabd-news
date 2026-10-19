# Google AdSense and consent readiness

Ad serving is deliberately disabled unless all three Render environment settings are explicitly configured. This prevents a placeholder publisher ID, an unpublished consent message, or an unreviewed ad setup from accidentally turning on ad requests.

## Required account-side steps

1. Add and verify `https://nabd-news.onrender.com` in the AdSense account.
2. In AdSense, open **Privacy & messaging** and create and publish the **European regulations** message for the site. Google states that its Privacy & messaging European regulations message supports the IAB TCF requirements. See the official guides:
   - https://support.google.com/adsense/answer/10960768
   - https://support.google.com/adsense/answer/13554116
3. Confirm the published message is associated with this site and test it using Google's account preview/tools. Do not mark consent as ready before the message has been published and verified.

## Render environment variables

Set these values on the web service only after the corresponding account steps are complete:

- `ADSENSE_PUBLISHER_ID`: the exact publisher ID shown by Google, in the form `ca-pub-1234567890123456`. Never use an example or guessed value.
- `ADSENSE_CONSENT_READY`: leave `false` until the site's European regulations message is published and verified; then set `true`.
- `ADSENSE_ENABLED`: leave `false` during setup and site review; set `true` only when ready to load the Google AdSense script.

The page loads Google's AdSense script only if `ADSENSE_ENABLED=true`, `ADSENSE_CONSENT_READY=true`, and the publisher ID has the expected format. The `/ads.txt` endpoint is separate: it returns the Google seller record whenever `ADSENSE_PUBLISHER_ID` is a valid real ID, even while ads and consent-dependent ad code remain disabled. If no valid publisher ID is configured, `/ads.txt` returns 404 rather than publishing a placeholder.

## Important limitation

This code does **not** create a consent message or certify a CMP by itself. The required message must be configured in the Google account. A certified CMP integrated with IAB TCF is required for personalized ads to eligible users in the EEA/UK and Switzerland; a local cookie banner is not a substitute. Follow Google's current guidance and review other applicable privacy requirements for the site's actual audience.
