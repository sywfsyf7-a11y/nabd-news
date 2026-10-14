# World Pulse — Publisher and image source policy

The app uses **Google News RSS only to discover publisher headlines, short excerpts and links**. It does not treat Google News thumbnails, publisher article thumbnails, Google Images results, or images embedded in an RSS feed as free-to-use assets. Google News listing a story or image does not grant World Pulse a licence to republish that image.

Each article must match a configured publisher domain for its category and source language. Arabic pages only show articles whose original source is in the Arabic source list; English pages only show articles whose original source is in the English source list. The ingestion pipeline rejects results with a publisher outside the allowlist and rejects headline language mismatches. Publisher domains are retained in the database for display-time filtering.

## 1. Politics
- Arabic: Al Jazeera (`aljazeera.net`, rights-gated), Al Arabiya (`alarabiya.net`), Sky News Arabia (`skynewsarabia.com`), Asharq Al-Awsat (`aawsat.com`), Al-Quds Al-Arabi (`alquds.co.uk`).
- English: BBC (`bbc.com`, rights-gated), Reuters (`reuters.com`, rights-gated), Associated Press (`apnews.com`, rights-gated), Politico (`politico.com`).

## 2. Economy
- Arabic: Asharq Business (`asharqbusiness.com`), CNBC Arabia (`cnbcarabia.com`), Mubasher (`mubasher.info`).
- English: Bloomberg (`bloomberg.com`), Financial Times (`ft.com`), The Wall Street Journal (`wsj.com`).

## 3. Technology
- Arabic: AIT News (`aitnews.com`), Tech-WD / عالم التقنية (`tech-wd.com`), Arab Hardware (`arabhardware.net`).
- English: The Verge (`theverge.com`), TechCrunch (`techcrunch.com`, rights-gated), WIRED (`wired.com`).

## 4. Gaming
- Arabic: Saudi Gamer (`saudigamer.com`), Arab Hardware (`arabhardware.net`), Arab Game News (`arabgamenews.com`), VGA4A (`vga4a.com`).
- English: IGN (`ign.com`), GameSpot (`gamespot.com`), Polygon (`polygon.com`).

## 5. Sports
- Arabic: FilGoal (`filgoal.com`), Kooora (`kooora.com`), beIN SPORTS (`beinsports.com`).
- English: BBC Sport (`bbc.com`, rights-gated), ESPN (`espn.com`, rights-gated), Sky Sports (`skysports.com`).

## 6. Science
- Arabic: National Geographic Abu Dhabi (`ngalarabiya.com`), Al Jazeera science (`aljazeera.net`, rights-gated).
- English: NASA (`nasa.gov`), Space.com (`space.com`), Scientific American (`scientificamerican.com`), Live Science (`livescience.com`).

## 7. Culture
- Arabic: Al-Qafilah (`alqafilah.com`), Al Jazeera culture (`aljazeera.net`, rights-gated), The New Arab (`alaraby.co.uk`), Al-Arab (`alarab.co.uk`).
- English: Literary Hub (`lithub.com`), Artsy (`artsy.net`), The Guardian (`theguardian.com`, rights-gated).

## 8. World
- Arabic: France 24 Arabic (`france24.com`), BBC Arabic (`bbc.com`, rights-gated), DW Arabic (`dw.com`).
- English: Euronews (`euronews.com`), BBC World (`bbc.com`, rights-gated), Associated Press (`apnews.com`, rights-gated).

## Rights-gated publishers

BBC, Reuters, AP News, TechCrunch, ESPN, The Guardian and Al Jazeera remain configured in the source catalog but are skipped by the app unless the host is explicitly approved in `CONTENT_LICENSE_APPROVED_DOMAINS` after rights review or written permission. Merely adding a host to that variable is an administrative action, not proof that a publisher granted permission; keep evidence of the specific licence/permission and comply with its scope.

## Image source pipeline

Images are taken only from these configured providers:

1. Wikimedia Commons assets accepted by the code's conservative filter for Public Domain Mark, CC0, or CC BY, with an image page, creator/credit and licence link where applicable.
2. Manually reviewed press-kit files listed in `approved_presskit_images.json`. Every entry must be approved for commercial use and contain the image URL, source page, credit, licence name, licence URL and matching keywords.
3. Official Pexels and Unsplash APIs when `PEXELS_API_KEY` / `UNSPLASH_ACCESS_KEY` are set and their controls are enabled; follow current provider API and attribution rules.
4. Local fallback images: `static/A.jpg` for articles whose original language is Arabic and `static/E.jpg` for articles whose original language is English. These are fallback graphics, not photos sourced from Google News.

Google News RSS images and publisher page thumbnails are intentionally not used as an image provider. No automated licence checker can guarantee legal status in every jurisdiction; review the original asset, exact licence and any additional person/property/trademark rights before commercial use.
