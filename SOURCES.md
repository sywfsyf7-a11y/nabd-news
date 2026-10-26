# Nabd News / نبض نيوز — publisher and image-source policy

Google News RSS is the discovery transport. The publisher named on a story and the verified publisher URL are the attribution; Google News is not presented as the reporter. Only the curated publisher lists below are eligible. Results are checked against the article's native language and section before they enter the permanent Supabase queue.

## One combined bilingual feed

The Arabic and English editions share the same stories and section filters. Each story retains its native source language. The site uses a complete, language-checked translation when one is available; otherwise, it labels the source language and displays the native story rather than inventing a translation. Politics, economy, technology, gaming, sports, science, culture, and world sections remain separate.

## Curated publisher list

### 1. Politics
- Arabic: `aljazeera.net`, `alarabiya.net`, `skynewsarabia.com`, `aawsat.com`, `alquds.co.uk`, `wam.ae`, `spa.gov.sa`
- English: `bbc.com`, `reuters.com`, `apnews.com`, `politico.com`, `theguardian.com`

### 2. Economy and finance
- Arabic: `asharqbusiness.com`, `cnbcarabia.com`, `mubasher.info`, `argaam.com`
- English: `bloomberg.com`, `ft.com`, `wsj.com`, `cnbc.com`, `marketwatch.com`

### 3. Technology and AI
- Arabic: `aitnews.com`, `tech-wd.com`, `arabhardware.net`
- English: `theverge.com`, `techcrunch.com`, `wired.com`, `arstechnica.com`

### 4. Gaming
- Arabic: `saudigamer.com`, `arabhardware.net`
- English: `ign.com`, `gamespot.com`, `polygon.com`, `eurogamer.net`, `kotaku.com`

### 5. Sports
- Arabic: `filgoal.com`, `kooora.com`, `beinsports.com`, `yallakora.com`
- English: `bbc.com`, `espn.com`, `skysports.com`, `theathletic.com`

### 6. Science and space
- Arabic: `nationalgeographic.com`, `aljazeera.net`
- English: `nasa.gov`, `jpl.nasa.gov`, `space.com`, `livescience.com`, `scientificamerican.com`, `nature.com`

### 7. Culture and arts
- Arabic: `alaraby.co.uk`, `alarab.co.uk`
- English: `lithub.com`, `artsy.net`, `theguardian.com`, `newyorker.com`

### 8. World news
- Arabic: `bbc.com`, `france24.com`, `dw.com`
- English: `bbc.com`, `euronews.com`, `apnews.com`, `cnn.com`

A domain being listed means that the system may discover its eligible headlines in the section above; it does not guarantee that a publisher offers an RSS result, that a result is new, or that every form of republication is permitted. Each item still passes language, source-host, duplicate, category, and rights checks.

## Copyright-conscious editorial workflow

- RSS discovery uses publisher-targeted Google News queries and official RSS endpoints only where configured. It stores the original publisher URL, publisher identity, category, language, source excerpt, and publication time when available.
- The newsroom does **not** download full copyrighted articles in order to rewrite them to evade copyright. Gemini works from a limited headline and short source excerpt where that source's policy allows it, and produces a concise, independent brief with a separate headline, executive summary, and details supported by the supplied evidence. It must not invent facts or add unsupported background.
- A short excerpt is not enough evidence for a long report. When the feed material cannot support a reliable summary, the item stays concise and points readers to the publisher for details.
- BBC, Al Jazeera, Reuters, Associated Press, TechCrunch, ESPN, ScienceDaily, The Guardian, and The Athletic are configured headline-and-source-link-only by default unless the deployment records a separately reviewed licence in `CONTENT_LICENSE_APPROVED_DOMAINS`. For these sources, RSS descriptions are not passed to the editorial model. Legacy stored text from those publishers is not used to create a new summary.
- The headline-only setting is a conservative site rule, not legal confirmation that every publisher permits any reuse of its headline. A deployment override is not proof of permission. Keep written licence/permission evidence and check its scope before enabling broader use.
- The original publisher link appears on the story page. Attribution and a link are good practice, but neither alone grants permission to republish protected article text or photographs.

Google's publisher policies disallow serving ads on screens that contain copied or embedded material without additional commentary, curation, or other added value. Originality and useful editorial context therefore matter for monetization as well as reader trust; compliance with these safeguards cannot guarantee AdSense approval. Policy reference: https://support.google.com/adsense/answer/10502938

## Publishing cadence and resilience

- **Every 15 minutes:** perform one bounded discovery scan over the approved publisher list, prioritizing requested sources and rotating eligible groups. The scan may queue up to three new candidates and never broadens to the whole internet if a source group fails.
- **Every 5 minutes:** publish at most one queued new story from the persistent Supabase queue. Each story gets its own editorial and image step, with up to two bounded Gemini calls for the story. A source-language brief remains possible during a Gemini outage.
- Each story is saved in Supabase before any optional image lookup. Temporary image-provider failure must not block the article from being saved. Queue items are acknowledged only after the story is persisted and are deduplicated against the archive.
- Queue processing and image revalidation do not delete old published articles or catalogued image records. Image cache/recheck age determines when a match can be reviewed again; it is not an article-retention period.

## Image catalogue and reuse rules

The image catalogue is broader than the publisher list because it searches public-domain and openly licensed imagery, not other publishers' article photographs. Searches derive short, topic-aware terms from the story headline and category. A provider result is accepted only after relevance and item-level reuse checks. If no adequate story-specific image is found for technology, gaming, sports, science, or culture, the last bounded search tries a category-themed image through the same open catalogues; the image is visibly labelled as illustrative on both card and article page, with its credit and licence metadata underneath. If that attempt fails, the site keeps its local category-specific SVG. The selected image keeps an item/source page, creator or credit, licence URL, and verification time in the story metadata.

### Providers used by the newsroom
1. **Wikimedia Commons** — public-domain, CC0, CC BY, and CC BY-SA files. Attribution and licence links are saved for CC BY/CC BY-SA. Noncommercial and no-derivatives licences are rejected.
2. **Openverse** — openly licensed images. Only CC0, Public Domain Mark, CC BY, and CC BY-SA items are accepted. Openverse warns that indexed licence metadata may be inaccurate, so item-level records must be retained and reviewed.
3. **Library of Congress** — only records explicitly marked public domain, CC0, free-to-use/reuse, or no-known-restrictions under the provider's item-level metadata. “No known restrictions” is not treated as a blanket licence.
4. **Art Institute of Chicago** — culture-related works only, and only artwork items identified as public domain. Its API asks developers to respect its image guidance and avoid excessive parallel image scraping.
5. **The Metropolitan Museum of Art (The Met)** — culture-related works in its Open Access collection only; item records must identify the image as open access/public domain.
6. **Cleveland Museum of Art Open Access** — culture-related works only; the adapter requires the specific artwork's CC0/open-access status and a verified item/image host. Its open-access terms do not make every image in its collection free to use.
7. **Wellcome Collection** — science/culture matches only. The adapter checks the individual image location, licence identifier, licence URL, item page, and credit; items without an allowed item-level licence are rejected.
8. **NASA Image and Video Library** — science, space, technology, and Earth/climate topics only. Explicit third-party/restricted/copyright notices are rejected; NASA's own use guidance and item provenance are retained.
9. **Administrator-approved press-kit assets** — only if the manifest explicitly documents approval for the planned use and includes the source, credit, and licence information.

The code does not use Unsplash or Pexels API keys. Google News thumbnails, publisher-page thumbnails, and generic unverified image-search results are not treated as licensed re-usable photographs. If no suitable item passes the checks, the site displays a topic-matched, labelled editorial SVG illustration rather than pretending that an unrelated photograph is documentary evidence.

### Official provider references
- Openverse API: https://api.openverse.org/v1/ and https://docs.openverse.org/
- Wikimedia reuse guidance: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia/en
- Library of Congress API: https://www.loc.gov/apis/json-and-yaml/requests/
- NASA media guidance: https://www.nasa.gov/nasa-brand-center/images-and-media/
- Art Institute of Chicago API: https://api.artic.edu/docs/
- The Met Collection API: https://metmuseum.github.io/
- Cleveland Museum of Art Open Access API: https://www.clevelandart.org/open-access-api
- Wellcome Collection APIs: https://api.wellcomecollection.org/
