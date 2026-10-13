# World Pulse — news-source catalogue and rights gates

This catalogue is used for domain-targeted Google News RSS discovery. A result is saved only if the publisher domain reported in the RSS entry (or the direct article host) matches a domain assigned to that exact category and language. Broad Google News results are filtered by the same rule; unknown publishers are discarded.

## Sources by section

| Section | Arabic source domains | English source domains |
|---|---|---|
| Politics | Al Jazeera (`aljazeera.net`), Al Arabiya (`alarabiya.com`, `alarabiya.net`), Sky News Arabia (`skynewsarabia.com`), Asharq Al-Awsat (`aawsat.com`), Al-Quds Al-Arabi (`alquds.co.uk`) | BBC (`bbc.com`, `bbc.co.uk`), Reuters (`reuters.com`), AP (`apnews.com`), Politico (`politico.com`) |
| Economy | Asharq Business (`asharqbusiness.com`), CNBC Arabia (`cnbcarabia.com`), Mubasher (`mubasher.info`), Al Arabiya (`alarabiya.com`, `alarabiya.net`) | Bloomberg (`bloomberg.com`), Financial Times (`ft.com`), WSJ (`wsj.com`), CNBC (`cnbc.com`), Reuters (`reuters.com`) |
| Technology | AIT News (`aitnews.com`), Tech-WD (`tech-wd.com`), Arab Hardware (`arabhardware.net`) | The Verge (`theverge.com`), TechCrunch (`techcrunch.com`), WIRED (`wired.com`), Ars Technica (`arstechnica.com`) |
| Gaming | Saudi Gamer (`saudigamer.com`), Arabian Gamer (`arabiangamer.net`), Arab Hardware (`arabhardware.net`) | IGN (`ign.com`), GameSpot (`gamespot.com`), Polygon (`polygon.com`), PC Gamer (`pcgamer.com`) |
| Sports | FilGoal (`filgoal.com`), Kooora (`kooora.com`), beIN SPORTS (`beinsports.com`) | BBC Sport (`bbc.com`, `bbc.co.uk`), ESPN (`espn.com`), Sky Sports (`skysports.com`), Reuters (`reuters.com`) |
| Science | National Geographic Arabic/Abu Dhabi (`natgeotv.com`, official regional site), Al Jazeera (`aljazeera.net`), Al Arabiya (`alarabiya.com`, `alarabiya.net`), DW (`dw.com`) | NASA (`nasa.gov`), Space.com (`space.com`), Scientific American (`scientificamerican.com`), Live Science (`livescience.com`) |
| Culture | Al-Qafilah (`alqafilah.com`), Thifaf/ضفاف (`thifaf.com`), Al Jazeera Culture (`aljazeera.net`), The New Arab (`alaraby.co.uk`), Al-Arab (`alarab.co.uk`) | Literary Hub (`lithub.com`), Artsy (`artsy.net`), The Guardian (`theguardian.com`) |
| World | France 24 Arabic (`france24.com`), BBC Arabic (`bbc.com`, `bbc.co.uk`), DW Arabic (`dw.com`), Al Jazeera (`aljazeera.net`), Euronews (`euronews.com`) | Euronews (`euronews.com`), BBC World (`bbc.com`, `bbc.co.uk`), AP (`apnews.com`), Reuters (`reuters.com`) |

The specific YouTube channel “شبكة ألعاب العرب” is not treated as a text-news publisher. The verified culture-literature site ضفاف is included at `thifaf.com`. “اسأل مجرب” is not added because an unambiguous official general-science/news domain could not be verified. `journals.imamu.edu.sa` was not added as a general science source because the found “مجلة العلوم العربية” describes itself as a journal focused on Arabic language and literature, not general science reporting.

## Rights gate

Some source domains remain in the catalogue for visibility but are blocked from automatic collection until World Pulse has appropriate written permission or a commercial syndication/API licence. The list currently includes BBC, Reuters, AP, TechCrunch, ESPN, ScienceDaily, The Guardian, Al Jazeera, Bloomberg, Financial Times, WSJ and Al Arabiya. This is deliberately conservative and is not a claim that every possible use of every listed source is forbidden. Keep these blocked unless your review confirms that your intended use is permitted or a licence explicitly covers commercial use and AI processing.

To activate a blocked publisher only after appropriate permission is obtained, set the optional Render environment variable `PUBLISHER_LICENSED_DOMAINS` to its exact domain(s), comma-separated, for example `bloomberg.com,bbc.com`. This override does not add a domain that is absent from the category catalogue and does not override the category/language allowlist.

The code stores only the headline, publisher label, link and a short RSS discovery excerpt (max 500 characters), does not crawl article bodies, and does not save unknown domains. This is risk reduction, not a legal guarantee; confirm each publisher's terms before monetized use. Attribution or linking alone does not grant a reuse licence.

## Image providers

1. Wikimedia Commons: accept only machine-readable Public Domain Mark 1.0, CC0 1.0, or plain CC BY 2.0/3.0/4.0 licence URLs. CC BY-SA, NC and ND are rejected. Show creator, file-page link and licence.
2. Manually reviewed press-kit images in `approved_presskit_images.json` only when the exact asset and commercial permission are verified. It starts empty.
3. Pexels API (`PEXELS_API_KEY`) and Unsplash API (`UNSPLASH_ACCESS_KEY`) are optional. The code preserves provider-returned image URLs and shows attribution/provider links required by the relevant API guidelines.
4. CSS placeholder when no suitable licensed image is found.

Publisher RSS thumbnails and `og:image` are not automatically reused. Old image records from earlier builds are cleared unless marked rights-checked by this pipeline. Stock imagery is labelled illustrative; do not imply it depicts the event itself. No automated process can guarantee zero copyright claims.
