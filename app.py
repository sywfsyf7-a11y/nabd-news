<!doctype html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#111827">
  <meta name="description" content="{% if page == 'article' and article %}{{ article.summary|striptags|truncate(155, True, '…') }}{% elif page == 'legal' %}{{ legal_body|striptags|truncate(155, True, '…') }}{% elif page == 'search' %}{{ ('نتائج البحث عن ' if lang == 'ar' else 'Search results for ') ~ (search_query or '') }}{% else %}{{ ui.hero_text }}{% endif %}">
  {% if page == 'search' %}<meta name="robots" content="noindex,follow">{% else %}<meta name="robots" content="index,follow,max-image-preview:large">{% endif %}
  <meta property="og:site_name" content="{{ site_name }}">
  <meta property="og:type" content="{% if page == 'article' %}article{% else %}website{% endif %}">
  <meta property="og:title" content="{% if page == 'article' and article %}{{ article.title }} — {% elif page == 'legal' %}{{ legal_title }} — {% endif %}{{ site_name }}">
  <meta property="og:description" content="{% if page == 'article' and article %}{{ article.summary|striptags|truncate(155, True, '…') }}{% else %}{{ ui.hero_text }}{% endif %}">
  {% if page == 'article' and article and article.image_url %}<meta property="og:image" content="{{ article.image_url }}">{% endif %}
  <title>{% if page == 'article' and article %}{{ article.title }} — {% elif page == 'legal' %}{{ legal_title }} — {% elif page == 'search' %}{{ 'نتائج البحث' if lang == 'ar' else 'Search results' }} — {% endif %}{{ site_name }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            ink: '#111827',
            paper: '#F7F7F5',
            pulse: '#E53945',
            muted: '#64748B'
          },
          boxShadow: {
            soft: '0 16px 45px rgba(15, 23, 42, 0.07)'
          }
        }
      }
    };
  </script>
  <script>
    try {
      document.documentElement.dataset.theme = localStorage.getItem('world-pulse-theme') || 'light';
    } catch (_) {
      document.documentElement.dataset.theme = 'light';
    }
  </script>
  <style>
    body { font-family: {% if lang == 'ar' %}'Cairo', sans-serif{% else %}'Inter', sans-serif{% endif %}; }
    .editorial-grid { background-image: radial-gradient(#cbd5e1 0.6px, transparent 0.6px); background-size: 13px 13px; }
    .ticker-track { min-width: 0; }
    .article-copy { white-space: pre-line; line-height: 2; }
    .nav-scroll::-webkit-scrollbar { display: none; }
    .nav-scroll { scrollbar-width: none; }
    @media (prefers-reduced-motion: no-preference) {
      .ticker-dot { animation: pulse-dot 1.8s ease-in-out infinite; }
      @keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
    }
    html[data-theme="dark"] { color-scheme: dark; }
    html[data-theme="dark"] body { background: #0b1120; color: #edf2f7; }
    html[data-theme="dark"] .bg-paper { background-color: #0b1120 !important; }
    html[data-theme="dark"] header,
    html[data-theme="dark"] footer { background-color: rgba(15, 23, 42, .97) !important; border-color: #293548 !important; }
    html[data-theme="dark"] .bg-white { background-color: #111b2d !important; }
    html[data-theme="dark"] .bg-slate-50 { background-color: #172235 !important; }
    html[data-theme="dark"] .bg-slate-100 { background-color: #1e293b !important; }
    html[data-theme="dark"] .text-ink { color: #f8fafc !important; }
    html[data-theme="dark"] .text-slate-700,
    html[data-theme="dark"] .text-slate-600 { color: #d5deea !important; }
    html[data-theme="dark"] .text-slate-500,
    html[data-theme="dark"] .text-slate-400 { color: #aab7ca !important; }
    html[data-theme="dark"] .border-slate-100,
    html[data-theme="dark"] .border-slate-200,
    html[data-theme="dark"] .border-slate-200\/70,
    html[data-theme="dark"] .border-slate-200\/80,
    html[data-theme="dark"] .border-slate-300 { border-color: #293548 !important; }
    html[data-theme="dark"] .ring-slate-200 { --tw-ring-color: #293548 !important; }
    html[data-theme="dark"] .hover\:bg-white:hover { background-color: #1e293b !important; }
    html[data-theme="dark"] .shadow-soft,
    html[data-theme="dark"] .shadow-sm { box-shadow: 0 16px 45px rgba(0,0,0,.2) !important; }
    .story-image-placeholder { display: flex; align-items: center; justify-content: center; overflow: hidden; background: #253047; color: rgba(255,255,255,.85); }
    .story-image-placeholder[data-category="politics"] { background: linear-gradient(135deg, #18253a, #65323e); }
    .story-image-placeholder[data-category="economy"] { background: linear-gradient(135deg, #153b37, #34465d); }
    .story-image-placeholder[data-category="technology"] { background: linear-gradient(135deg, #192b4a, #3b3a70); }
    .story-image-placeholder[data-category="gaming"] { background: linear-gradient(135deg, #33204c, #762d53); }
    .story-image-placeholder[data-category="sports"] { background: linear-gradient(135deg, #164638, #425c35); }
    .story-image-placeholder[data-category="science"] { background: linear-gradient(135deg, #183a53, #31616d); }
    .story-image-placeholder[data-category="culture"] { background: linear-gradient(135deg, #4c2d32, #7a5838); }
    .story-image-placeholder[data-category="world"] { background: linear-gradient(135deg, #273448, #4b5870); }
    html[data-theme="dark"] .story-image-placeholder { filter: saturate(.82) brightness(.9); }
  </style>
</head>
<body class="min-h-screen bg-paper text-ink antialiased">
  <div class="bg-ink text-white">
    <div class="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-2.5 sm:px-6 lg:px-8">
      <div class="flex min-w-0 items-center gap-3 text-xs sm:text-sm">
        <span class="inline-flex shrink-0 items-center gap-2 font-bold tracking-wide text-rose-400">
          <span class="h-2 w-2 rounded-full bg-pulse ticker-dot"></span>{{ ui.live }}
        </span>
        <span class="hidden h-4 w-px bg-white/20 sm:block"></span>
        <span class="truncate text-white/70">{{ ui.tagline }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <button id="themeToggle" type="button" aria-pressed="false" aria-label="{{ ui.theme_toggle }}" title="{{ ui.theme_toggle }}"
                class="inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-2 text-xs font-bold transition hover:border-white/60 hover:bg-white/10">
          <svg id="sunIcon" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" stroke-linecap="round"/></svg>
          <svg id="moonIcon" viewBox="0 0 24 24" class="hidden h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20.5 14.3A8.5 8.5 0 0 1 9.7 3.5 8.6 8.6 0 1 0 20.5 14.3Z" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="hidden sm:inline">{{ ui.theme_toggle }}</span>
        </button>
        <button id="refreshNews" type="button" aria-label="{{ ui.refresh_news }}" title="{{ ui.refresh_news }}"
                class="inline-flex items-center gap-2 rounded-full bg-pulse px-3 py-2 text-xs font-extrabold text-white transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70">
          <svg id="refreshIcon" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" stroke-linecap="round" stroke-linejoin="round"/><path d="M5.6 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12.4-3" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span id="refreshButtonText" class="hidden sm:inline">{{ ui.refresh_news }}</span>
        </button>
        <a href="{{ url_for('index', lang='en' if lang == 'ar' else 'ar') }}"
           class="shrink-0 rounded-full border border-white/20 px-3 py-2 text-xs font-bold transition hover:border-white/60 hover:bg-white/10"
           aria-label="{{ 'Switch language' if lang == 'ar' else 'تغيير اللغة' }}">
          {{ 'EN' if lang == 'ar' else 'عربي' }}
        </a>
      </div>
    </div>
  </div>

  <header class="sticky top-0 z-30 border-b border-slate-200/80 bg-paper/95 backdrop-blur-xl">
    <div class="mx-auto flex max-w-7xl items-center justify-between gap-5 px-4 py-4 sm:px-6 lg:px-8">
      <a href="{{ url_for('index', lang=lang) }}" class="group flex shrink-0 items-center gap-3" aria-label="{{ site_name }} — home">
        <span class="grid h-11 w-11 place-items-center rounded-2xl bg-pulse text-white shadow-lg shadow-rose-500/20 transition group-hover:-rotate-3">
          <svg viewBox="0 0 32 32" class="h-7 w-7" fill="none" aria-hidden="true">
            <path d="M4 17h5l3-8 5 15 3-9 2 4h6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <span class="block">
          <span class="block text-xl font-extrabold leading-tight tracking-tight sm:text-2xl">{{ site_name }}</span>
          <span class="mt-0.5 block text-[10px] font-semibold uppercase tracking-[.22em] text-slate-500">{{ 'WORLD PULSE' if lang == 'ar' else 'NEWS · CONTEXT · PERSPECTIVE' }}</span>
        </span>
      </a>
      <form action="{{ url_for('search', lang=lang) }}" method="get" role="search" class="hidden min-w-0 max-w-sm flex-1 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 md:flex">
        <label for="siteSearch" class="sr-only">{{ 'ابحث في الأخبار' if lang == 'ar' else 'Search news' }}</label>
        <input id="siteSearch" name="q" value="{{ search_query if search_query is defined else '' }}" type="search" maxlength="160" required placeholder="{{ 'ابحث في الأخبار...' if lang == 'ar' else 'Search news...' }}" class="min-w-0 flex-1 bg-transparent text-sm outline-none" />
        <button type="submit" aria-label="{{ 'بحث' if lang == 'ar' else 'Search' }}" class="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-pulse text-white"><svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="7"/><path d="m16 16 4 4" stroke-linecap="round"/></svg></button>
      </form>
    </div>
    <nav class="border-t border-slate-200/70" aria-label="{{ 'الأقسام' if lang == 'ar' else 'News sections' }}">
      <div class="nav-scroll mx-auto flex max-w-7xl items-center gap-2 overflow-x-auto px-4 py-2.5 sm:px-6 lg:px-8">
        <a href="{{ url_for('index', lang=lang, category='all') }}"
           class="shrink-0 rounded-full px-4 py-2 text-sm font-bold transition {{ 'bg-ink text-white' if active_category == 'all' else 'text-slate-600 hover:bg-white hover:text-ink' }}">{{ ui.all_news }}</a>
        {% for item in categories %}
          <a href="{{ url_for('index', lang=lang, category=item.key) }}"
             class="shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition {{ 'bg-ink text-white' if active_category == item.key else 'text-slate-600 hover:bg-white hover:text-ink' }}">{{ item.label }}</a>
        {% endfor %}
      </div>
    </nav>
    <div class="border-t border-slate-200/60">
      <div class="mx-auto flex max-w-7xl items-center justify-end px-4 py-2 sm:px-6 lg:px-8">
        <p id="newsStatusText" role="status" aria-live="polite" class="text-[11px] font-medium text-slate-500">{{ ui.auto_refresh.replace('{minutes}', news_refresh_interval|string) }}</p>
      </div>
    </div>
  </header>

  <form action="{{ url_for('search', lang=lang) }}" method="get" role="search" class="mx-auto flex max-w-7xl items-center gap-2 px-4 pt-4 md:hidden sm:px-6 lg:px-8">
    <label for="mobileSiteSearch" class="sr-only">{{ 'ابحث في الأخبار' if lang == 'ar' else 'Search news' }}</label>
    <input id="mobileSiteSearch" name="q" value="{{ search_query if search_query is defined else '' }}" type="search" maxlength="160" required placeholder="{{ 'ابحث في الأخبار...' if lang == 'ar' else 'Search news...' }}" class="min-w-0 flex-1 rounded-full border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-pulse" />
    <button type="submit" class="rounded-full bg-pulse px-4 py-3 text-sm font-bold text-white">{{ 'بحث' if lang == 'ar' else 'Search' }}</button>
  </form>
  <main class="mx-auto max-w-7xl px-4 pb-16 pt-5 sm:px-6 sm:pt-8 lg:px-8">
    {% if page == 'legal' %}
      <section class="mx-auto max-w-3xl rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10">
        <h1 class="mb-5 text-3xl font-extrabold">{{ legal_title }}</h1>
        <p class="whitespace-pre-line text-base leading-8 text-slate-600">{{ legal_body }}</p>
        {% if legal_slug == 'contact' and contact_status is defined and contact_status %}
          <div role="status" aria-live="polite" class="mt-5 rounded-2xl border px-4 py-3 text-sm leading-7 {% if contact_status == 'sent' %}border-emerald-200 bg-emerald-50 text-emerald-800{% elif contact_status == 'invalid' %}border-amber-200 bg-amber-50 text-amber-900{% else %}border-rose-200 bg-rose-50 text-rose-800{% endif %}">
            {% if contact_status == 'sent' %}{{ 'تم إرسال رسالتك بنجاح، شكرًا لتواصلك.' if lang == 'ar' else 'Your message was sent successfully. Thank you.' }}
            {% elif contact_status == 'invalid' %}{{ 'يرجى تعبئة الحقول والتأكد من صحة البريد الإلكتروني.' if lang == 'ar' else 'Please complete all fields and provide a valid email address.' }}
            {% elif contact_status == 'failed' %}{{ 'تعذر إرسال الرسالة الآن. يرجى التواصل عبر syfsywf86@gmail.com.' if lang == 'ar' else 'We could not send your message. Please email syfsywf86@gmail.com.' }}{% endif %}
          </div>
        {% endif %}
        {% if legal_slug == 'contact' %}
          <form id="contact-form" action="{{ url_for('contact_submit', lang=lang) }}" method="post" class="mt-8 space-y-4">
            <input type="hidden" name="csrf_token" value="{{ contact_csrf_token }}">
            <div><label for="contactName" class="mb-1 block text-sm font-bold">{{ 'الاسم' if lang == 'ar' else 'Name' }}</label><input id="contactName" name="name" maxlength="100" required class="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm" /></div>
            <div><label for="contactEmail" class="mb-1 block text-sm font-bold">{{ 'البريد الإلكتروني' if lang == 'ar' else 'Email' }}</label><input id="contactEmail" type="email" name="email" maxlength="160" required class="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm" /></div>
            <div><label for="contactMessage" class="mb-1 block text-sm font-bold">{{ 'الرسالة' if lang == 'ar' else 'Message' }}</label><textarea id="contactMessage" name="message" maxlength="3000" rows="5" required class="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"></textarea></div>
            <p class="text-xs leading-6 text-slate-500">{% if contact_smtp_enabled %}{{ 'سيتم إرسال رسالتك مباشرة من الموقع إلى syfsywf86@gmail.com.' if lang == 'ar' else 'Your message will be sent directly to syfsywf86@gmail.com.' }}{% else %}{{ 'سيُفتح تطبيق البريد لديك لإكمال الإرسال إلى syfsywf86@gmail.com. يمكن تفعيل الإرسال المباشر بإعداد SMTP في Render.' if lang == 'ar' else 'Your email app will open to complete sending to syfsywf86@gmail.com. Direct sending can be enabled with SMTP settings in Render.' }}{% endif %}</p>
            <button type="submit" class="rounded-full bg-pulse px-5 py-3 text-sm font-bold text-white">{{ 'متابعة الإرسال' if lang == 'ar' else 'Continue to email' }}</button>
          </form>
        {% endif %}
      </section>
    {% elif page == 'search' %}
      <section class="mb-6"><h1 class="text-3xl font-extrabold">{{ 'نتائج البحث' if lang == 'ar' else 'Search results' }}</h1><p class="mt-2 text-sm text-slate-500">{{ 'عبارة البحث: ' if lang == 'ar' else 'Search query: ' }}{{ search_query }}</p></section>
      {% if stories %}<div class="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">{% for story in stories %}<article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><p class="mb-2 text-xs font-bold text-pulse">{{ story.category_label }} · {{ story.source_name or ui.source }}</p><h2 class="text-lg font-extrabold leading-8"><a href="{{ url_for('article', slug=story.slug, lang=lang) }}">{{ story.title }}</a></h2><p class="mt-3 line-clamp-4 text-sm leading-7 text-slate-600">{{ story.summary }}</p><a class="mt-4 inline-block text-sm font-bold text-pulse" href="{{ url_for('article', slug=story.slug, lang=lang) }}">{{ 'اقرأ الخبر' if lang == 'ar' else 'Read story' }} ←</a></article>{% endfor %}</div>{% else %}<p class="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">{{ 'لا توجد نتائج مطابقة. جرّب كلمات أخرى.' if lang == 'ar' else 'No matching results. Try different keywords.' }}</p>{% endif %}
    {% elif page == 'home' %}
      <section class="mb-6 overflow-hidden rounded-[2rem] bg-ink text-white shadow-soft">
        <div class="relative grid gap-8 px-6 py-9 sm:px-10 sm:py-12 lg:grid-cols-[1.1fr_.9fr] lg:items-center lg:px-14 lg:py-14">
          <div class="pointer-events-none absolute inset-y-0 {{ 'left-0' if lang == 'ar' else 'right-0' }} hidden w-2/5 opacity-20 lg:block editorial-grid"></div>
          <div class="relative z-10 max-w-2xl">
            <div class="mb-5 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-bold text-rose-300">
              <span class="h-1.5 w-1.5 rounded-full bg-rose-400"></span>{{ ui.latest }}
            </div>
            <h1 class="max-w-2xl text-3xl font-extrabold leading-[1.35] tracking-tight sm:text-4xl lg:text-5xl">{{ ui.hero_title }}</h1>
            <p class="mt-5 max-w-xl text-sm leading-7 text-slate-300 sm:text-base sm:leading-8">{{ ui.hero_text }}</p>
            <a href="#latest-stories" class="mt-7 inline-flex items-center gap-2 rounded-full bg-pulse px-5 py-3 text-sm font-bold text-white shadow-lg shadow-rose-900/20 transition hover:-translate-y-0.5 hover:bg-rose-500">
              {{ ui.latest }}
              <svg viewBox="0 0 20 20" class="h-4 w-4 {{ 'rotate-180' if lang == 'ar' else '' }}" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 10h13M10 4l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </a>
          </div>
          <div class="relative z-10 hidden lg:block">
            <div class="ml-auto max-w-sm rounded-3xl border border-white/10 bg-white/[.06] p-5 backdrop-blur-sm">
              <div class="mb-5 flex items-center justify-between text-xs font-semibold text-slate-300">
                <span>{{ site_name }}</span><span class="rounded-full bg-rose-400/15 px-2.5 py-1 text-rose-300">{{ 'ثمانية أقسام' if lang == 'ar' else '8 sections' }}</span>
              </div>
              <div class="grid grid-cols-2 gap-3">
                {% for item in categories[:4] %}
                  <a href="{{ url_for('index', lang=lang, category=item.key) }}" class="rounded-2xl border border-white/10 bg-ink/30 p-4 transition hover:border-rose-400/60 hover:bg-white/10">
                    <span class="mb-4 block h-1 w-8 rounded-full bg-pulse"></span>
                    <span class="text-sm font-bold">{{ item.label }}</span>
                    <span class="mt-1 block text-xs text-slate-400">{{ 'اقرأ آخر التغطيات' if lang == 'ar' else 'Explore coverage' }}</span>
                  </a>
                {% endfor %}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="mb-9 flex items-stretch gap-3 rounded-2xl border border-rose-100 bg-white p-3 shadow-sm sm:items-center sm:p-4" aria-label="{{ ui.breaking }}">
        <div class="flex shrink-0 items-center gap-2 rounded-xl bg-pulse px-3 py-2.5 text-xs font-extrabold text-white sm:px-4 sm:text-sm">
          <span class="h-2 w-2 rounded-full bg-white"></span>{{ ui.breaking }}
        </div>
        {% if breaking_story %}
          <a href="{{ url_for('article', slug=breaking_story.slug, lang=lang) }}" class="ticker-track flex min-w-0 flex-1 items-center justify-between gap-3 px-1 py-1 text-sm font-semibold leading-6 transition hover:text-pulse sm:text-base">
            <span class="line-clamp-2">{{ breaking_story.title }}</span>
            <span class="hidden shrink-0 text-xs font-medium text-slate-400 sm:inline">{{ breaking_story.published_label }}</span>
          </a>
        {% else %}
          <p class="ticker-track flex min-w-0 flex-1 items-center px-1 text-sm leading-6 text-slate-500">{{ ui.no_breaking }}</p>
        {% endif %}
      </section>

      <section id="latest-stories" class="scroll-mt-40">
        <div class="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p class="mb-2 text-xs font-extrabold uppercase tracking-[.18em] text-pulse">{{ ui.live }}</p>
            <h2 class="text-2xl font-extrabold tracking-tight sm:text-3xl">{% if active_category == 'all' %}{{ ui.latest }}{% else %}{{ category_names[active_category][lang] }}{% endif %}</h2>
          </div>
          <span class="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-slate-500 ring-1 ring-slate-200">{{ stories|length }} {{ 'مادة' if lang == 'ar' else ('stories' if stories|length != 1 else 'story') }}</span>
        </div>

        {% if stories %}
          <div class="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {% for story in stories %}
              <article class="group flex h-full flex-col overflow-hidden rounded-3xl border border-slate-200/80 bg-white shadow-sm transition duration-300 hover:-translate-y-1 hover:border-slate-300 hover:shadow-soft">
                <a href="{{ url_for('article', slug=story.slug, lang=lang) }}" class="relative block aspect-[16/9] overflow-hidden bg-slate-200" tabindex="-1" aria-hidden="true">
                  <div class="story-image-placeholder absolute inset-0" data-category="{{ story.category }}" aria-label="{{ story.category_label }} image placeholder">
                    <span class="select-none text-6xl font-black tracking-widest opacity-35">WP</span>
                  </div>
                  {% if story.image_url %}
                    <img src="{{ story.image_url }}" alt="{{ story.title }}" loading="lazy" decoding="async" class="absolute inset-0 z-[1] h-full w-full object-cover transition duration-700 group-hover:scale-105" onerror="this.onerror=null;this.style.display='none';">
                  {% endif %}
                  <span class="absolute {{ 'right-4' if lang == 'ar' else 'left-4' }} top-4 rounded-full border border-white/25 bg-ink/80 px-3 py-1.5 text-xs font-bold text-white backdrop-blur">{{ story.category_label }}</span>
                  {% if story.is_demo %}<span class="absolute bottom-3 {{ 'right-3' if lang == 'ar' else 'left-3' }} rounded-md bg-amber-100 px-2 py-1 text-[9px] font-extrabold text-amber-900">{{ ui.sample_badge }}</span>{% endif %}
                </a>
                <div class="flex flex-1 flex-col p-5 sm:p-6">
                  {% if story.image_source != 'category' and story.image_credit %}
                    <p class="mb-2 text-[10px] leading-5 text-slate-400">{{ ui.photo_credit }}:
                      {% if story.image_credit_url %}<a href="{{ story.image_credit_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ story.image_credit }}</a>{% else %}{{ story.image_credit }}{% endif %}
                      {% if story.image_license_name %} · {{ story.image_license_name }}{% endif %}{% if story.image_license_url %} · <a href="{{ story.image_license_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ ui.photo_license }}</a>{% endif %}
                    </p>
                  {% endif %}
                  <div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium text-slate-500">
                    <span>{{ story.source_name or ui.source }}</span>
                    <span class="h-1 w-1 rounded-full bg-slate-300"></span>
                    <time>{{ story.published_label }}</time>
                  </div>
                  <h3 class="mb-3 text-lg font-extrabold leading-8 tracking-tight transition group-hover:text-pulse sm:text-xl">
                    <a href="{{ url_for('article', slug=story.slug, lang=lang) }}">{{ story.title }}</a>
                  </h3>
                  <p class="mb-6 line-clamp-3 text-sm leading-7 text-slate-600">{{ story.summary }}</p>
                  <div class="mt-auto flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
                    <span class="text-xs font-medium text-slate-400">{{ story.read_minutes }} {{ ui.read_time }}</span>
                    <a href="{{ url_for('article', slug=story.slug, lang=lang) }}" class="inline-flex items-center gap-2 text-sm font-extrabold text-pulse transition hover:gap-3">
                      {{ ui.read_full }}
                      <svg viewBox="0 0 20 20" class="h-4 w-4 {{ 'rotate-180' if lang == 'ar' else '' }}" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 10h13M10 4l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </a>
                  </div>
                </div>
              </article>
            {% endfor %}
          </div>
        {% else %}
          <div class="rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
            <p class="text-base font-semibold text-slate-500">{{ ui.empty }}</p>
            <a href="{{ url_for('index', lang=lang, category='all') }}" class="mt-4 inline-flex rounded-full bg-ink px-4 py-2 text-sm font-bold text-white">{{ ui.all_news }}</a>
          </div>
        {% endif %}
      </section>

    {% elif page == 'article' and article %}
      <div class="mb-5 flex items-center justify-between gap-4">
        <a href="{{ url_for('index', lang=lang) }}" class="inline-flex items-center gap-2 text-sm font-bold text-slate-500 transition hover:text-pulse">
          <svg viewBox="0 0 20 20" class="h-4 w-4 {{ 'rotate-180' if lang == 'ar' else '' }}" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 10H3m6 6-6-6 6-6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          {{ ui.back_home }}
        </a>
        <span class="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-slate-500 ring-1 ring-slate-200">{{ article.category_label }}</span>
      </div>

      <article class="overflow-hidden rounded-[2rem] border border-slate-200/80 bg-white shadow-soft">
        <div class="relative aspect-[16/8] max-h-[540px] overflow-hidden bg-slate-200 sm:aspect-[16/7]">
          <div class="story-image-placeholder absolute inset-0" data-category="{{ article.category }}" aria-hidden="true"><span class="select-none text-8xl font-black tracking-widest opacity-35">WP</span></div>
          {% if article.image_url %}
            <img src="{{ article.image_url }}" alt="{{ article.title }}" decoding="async" class="absolute inset-0 z-[1] h-full w-full object-cover" onerror="this.onerror=null;this.style.display='none';">
          {% endif %}
          <div class="absolute inset-0 bg-gradient-to-t from-ink/75 via-ink/10 to-transparent"></div>
          {% if article.is_demo %}<span class="absolute {{ 'right-6' if lang == 'ar' else 'left-6' }} top-6 rounded-full bg-amber-100 px-3 py-1.5 text-[10px] font-extrabold text-amber-900">{{ ui.sample_badge }}</span>{% endif %}
          <div class="absolute inset-x-0 bottom-0 p-6 text-white sm:p-10 lg:p-12">
            <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs font-semibold text-white/80 sm:text-sm">
              <span>{{ article.source_name or ui.source }}</span><span class="h-1 w-1 rounded-full bg-white/60"></span><time>{{ article.published_label }}</time><span class="h-1 w-1 rounded-full bg-white/60"></span><span>{{ article.read_minutes }} {{ ui.read_time }}</span>
            </div>
            <h1 class="max-w-4xl text-2xl font-extrabold leading-[1.45] tracking-tight sm:text-3xl lg:text-5xl">{{ article.title }}</h1>
          </div>
        </div>
        {% if article.image_credit %}
          <div class="border-b border-slate-100 px-6 py-3 text-[11px] leading-5 text-slate-400 sm:px-9 lg:px-12">
            {{ ui.photo_credit }}:
            {% if article.image_credit_url %}<a href="{{ article.image_credit_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ article.image_credit }}</a>{% else %}{{ article.image_credit }}{% endif %}
            {% if article.image_license_name %} · {{ article.image_license_name }}{% endif %}{% if article.image_license_url %} · <a href="{{ article.image_license_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ ui.photo_license }}</a>{% endif %}
          </div>
        {% endif %}

        <div class="grid gap-10 p-6 sm:p-9 lg:grid-cols-[minmax(0,1fr)_270px] lg:gap-14 lg:p-12">
          <div class="min-w-0">
            <div class="mb-8 rounded-2xl border-s-4 border-pulse bg-slate-50 p-5 sm:p-6">
              <p class="mb-2 text-xs font-extrabold uppercase tracking-wider text-pulse">{{ 'ملخص تنفيذي' if lang == 'ar' else 'Executive summary' }}</p>
              <p class="text-base font-semibold leading-8 text-slate-700">{{ article.summary }}</p>
              {% if not article.is_demo %}<p class="mt-3 text-xs leading-6 text-slate-500">{{ 'ملخص وسياق تحريري بمساعدة الذكاء الاصطناعي استناداً إلى المعلومات المتاحة من المصدر؛ راجع المصدر الأصلي للتفاصيل والتحديثات.' if lang == 'ar' else 'AI-assisted editorial summary and context based on available source information; consult the original publisher for full details and updates.' }}</p>{% endif %}
            </div>
            {% if article.content %}
              <h2 class="mb-4 text-xl font-extrabold tracking-tight sm:text-2xl">{{ ui.article_details }}</h2>
              <div class="article-copy text-base leading-8 text-slate-700 sm:text-lg">{{ article.content }}</div>
            {% elif not article.is_demo %}
              <p class="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-500">{{ ui.body_unavailable }}</p>
            {% endif %}
            {% if not article.is_demo %}
              <section id="articleAsk" class="mt-9 rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:p-6">
                <div class="mb-4 flex items-start gap-3">
                  <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-pulse text-white" aria-hidden="true">
                    <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 14.3 9.7 21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Z" stroke-linejoin="round"/><path d="m19 3 .8 2.2L22 6l-2.2.8L19 9l-.8-2.2L16 6l2.2-.8L19 3Z" stroke-linejoin="round"/></svg>
                  </span>
                  <div>
                    <h2 class="text-lg font-extrabold">{{ ui.ai_ask_title }}</h2>
                    <p class="mt-1 text-sm leading-7 text-slate-500">{{ ui.ai_ask_desc }}</p>
                  </div>
                </div>
                <form id="articleAskForm" class="space-y-3">
                  <label for="articleQuestion" class="sr-only">{{ ui.ai_question_placeholder }}</label>
                  <textarea id="articleQuestion" name="question" rows="3" maxlength="500" required placeholder="{{ ui.ai_question_placeholder }}" class="w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-7 text-ink outline-none transition focus:border-pulse focus:ring-2 focus:ring-rose-500/15"></textarea>
                  <div class="flex flex-wrap items-center gap-3">
                    <button id="articleAskButton" type="submit" {% if not ai_ask_enabled %}disabled{% endif %} class="inline-flex items-center gap-2 rounded-full bg-pulse px-5 py-3 text-sm font-extrabold text-white transition hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-50"><svg id="askSpinner" class="hidden h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity=".25" stroke-width="3"/><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg><span>{{ ui.ai_ask_button }}</span></button>
                    <span id="articleAskStatus" role="status" aria-live="polite" class="text-xs leading-6 text-slate-500">{% if not ai_ask_enabled %}{{ ui.ai_disabled }}{% endif %}</span>
                  </div>
                </form>
                <div id="articleAskAnswer" class="article-copy mt-4 hidden rounded-xl border border-slate-200 bg-white p-4 text-sm leading-7 text-slate-700" aria-live="polite"></div>
                <p class="mt-3 text-[11px] leading-5 text-slate-400">{{ ui.ai_disclaimer }}</p>
                <div class="mt-4 flex flex-wrap gap-2">
                  <a id="askChatGPT" href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer" class="inline-flex items-center rounded-full border border-slate-300 px-4 py-2 text-xs font-bold text-slate-600 transition hover:border-pulse hover:text-pulse">{{ ui.ask_chatgpt }}</a>
                  <a id="askGemini" href="https://gemini.google.com/app" target="_blank" rel="noopener noreferrer" class="inline-flex items-center rounded-full border border-slate-300 px-4 py-2 text-xs font-bold text-slate-600 transition hover:border-pulse hover:text-pulse">{{ ui.ask_gemini }}</a>
                </div>
              </section>
              <p class="mt-8 border-t border-slate-100 pt-5 text-xs leading-6 text-slate-400">{{ ui.ai_note }}</p>
              {% if article.source_url %}
                <a href="{{ article.source_url }}" target="_blank" rel="noopener noreferrer" class="mt-6 inline-flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-bold text-white transition hover:bg-pulse">
                  {{ ui.open_source }}
                  <svg viewBox="0 0 20 20" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 3h6v6M17 3 9 11" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 11v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" stroke-linecap="round"/></svg>
                </a>
              {% endif %}
            {% endif %}
          </div>
          <aside class="border-t border-slate-100 pt-8 lg:border-t-0 lg:border-s {{ 'lg:ps-8' if lang == 'ar' else 'lg:pl-8' }} lg:pt-0">
            <p class="mb-5 text-xs font-extrabold uppercase tracking-[.16em] text-pulse">{{ ui.recommended }}</p>
            <div class="space-y-5">
              {% for story in related_stories %}
                <a href="{{ url_for('article', slug=story.slug, lang=lang) }}" class="group flex gap-3">
                  <span class="relative block h-20 w-24 shrink-0 overflow-hidden rounded-xl bg-slate-200">
                    <span class="story-image-placeholder absolute inset-0" data-category="{{ story.category }}" aria-hidden="true"><span class="text-lg font-black opacity-40">WP</span></span>
                    {% if story.image_url %}
                      <img src="{{ story.image_url }}" alt="{{ story.title }}" loading="lazy" decoding="async" class="absolute inset-0 z-[1] h-full w-full object-cover" onerror="this.onerror=null;this.style.display='none';">
                    {% endif %}
                  </span>
                  <span class="min-w-0">
                    <span class="mb-1 block text-[10px] font-extrabold text-pulse">{{ story.category_label }}</span>
                    <span class="line-clamp-3 block text-sm font-bold leading-6 transition group-hover:text-pulse">{{ story.title }}</span>
                  </span>
                </a>
                {% if story.image_source in ['wikimedia', 'wikimedia_relevant'] and story.image_credit %}
                  <p class="{{ 'mr-28' if lang == 'ar' else 'ml-28' }} -mt-3 text-[10px] leading-4 text-slate-400">
                    {{ ui.photo_credit }}:
                    {% if story.image_credit_url %}<a href="{{ story.image_credit_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ story.image_credit }}</a>{% else %}{{ story.image_credit }}{% endif %}
                    {% if story.image_license_name %} · {{ story.image_license_name }}{% endif %}{% if story.image_license_url %} · <a href="{{ story.image_license_url }}" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">{{ ui.photo_license }}</a>{% endif %}
                  </p>
                {% endif %}
              {% else %}
                <p class="text-sm leading-7 text-slate-500">{{ ui.empty }}</p>
              {% endfor %}
            </div>
          </aside>
        </div>
      </article>

    {% else %}
      <section class="mx-auto max-w-xl rounded-3xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
        <p class="mb-3 text-6xl font-black text-pulse">404</p>
        <h1 class="text-2xl font-extrabold">{{ 'الصفحة غير موجودة' if lang == 'ar' else 'Page not found' }}</h1>
        <p class="mt-3 text-sm leading-7 text-slate-500">{{ 'قد يكون الرابط قديماً أو أن المقال غير متاح باللغة المختارة.' if lang == 'ar' else 'The link may be outdated, or this story is not available in the selected language.' }}</p>
        <a href="{{ url_for('index', lang=lang) }}" class="mt-6 inline-flex rounded-full bg-pulse px-5 py-3 text-sm font-bold text-white transition hover:bg-rose-600">{{ ui.back_home }}</a>
      </section>
    {% endif %}
  </main>

  <footer class="border-t border-slate-200 bg-white">
    <div class="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
      <a href="{{ url_for('index', lang=lang) }}" class="flex items-center gap-2 font-extrabold"><span class="grid h-8 w-8 place-items-center rounded-xl bg-pulse text-white">WP</span>{{ site_name }}</a>
      <div class="flex flex-wrap gap-x-4 gap-y-2 text-xs font-semibold text-slate-500">
        <a class="hover:text-pulse" href="{{ url_for('legal_page', slug='privacy', lang=lang) }}">{{ 'سياسة الخصوصية' if lang == 'ar' else 'Privacy Policy' }}</a>
        <a class="hover:text-pulse" href="{{ url_for('legal_page', slug='terms', lang=lang) }}">{{ 'شروط الاستخدام' if lang == 'ar' else 'Terms of Service' }}</a>
        <a class="hover:text-pulse" href="{{ url_for('legal_page', slug='about', lang=lang) }}">{{ 'من نحن' if lang == 'ar' else 'About Us' }}</a>
        <a class="hover:text-pulse" href="{{ url_for('legal_page', slug='contact', lang=lang) }}">{{ 'اتصل بنا' if lang == 'ar' else 'Contact Us' }}</a>
      </div>
      <p class="text-xs leading-6 text-slate-500">{{ ui.footer }}</p>
      <p class="text-xs text-slate-500"><a href="mailto:syfsywf86@gmail.com" class="underline underline-offset-4 hover:text-pulse">syfsywf86@gmail.com</a></p>
      <p class="text-[11px] font-medium text-slate-400">© {{ now_year if now_year is defined else 2026 }} {{ site_name }}</p>
    </div>
  </footer>
  <script>
    (() => {
      const root = document.documentElement;
      const themeButton = document.getElementById('themeToggle');
      const sunIcon = document.getElementById('sunIcon');
      const moonIcon = document.getElementById('moonIcon');
      const refreshButton = document.getElementById('refreshNews');
      const refreshButtonText = document.getElementById('refreshButtonText');
      const refreshIcon = document.getElementById('refreshIcon');
      const statusText = document.getElementById('newsStatusText');
      const text = {
        lightTheme: {{ ui.theme_toggle|tojson }},
        refresh: {{ ui.refresh_news|tojson }},
        refreshing: {{ ui.refreshing|tojson }},
        autoRefresh: {{ ui.auto_refresh|tojson }},
        interval: {{ news_refresh_interval|tojson }},
        updated: {{ ui.last_updated|tojson }},
        cooldown: {{ ui.refresh_cooldown|tojson }},
        error: {{ ui.refresh_error|tojson }},
        lang: {{ lang|tojson }}
      };

      function applyTheme(theme) {
        root.dataset.theme = theme;
        const dark = theme === 'dark';
        if (sunIcon) sunIcon.classList.toggle('hidden', dark);
        if (moonIcon) moonIcon.classList.toggle('hidden', !dark);
        if (themeButton) themeButton.setAttribute('aria-pressed', String(dark));
        try { localStorage.setItem('world-pulse-theme', theme); } catch (_) {}
      }
      applyTheme(root.dataset.theme || 'light');
      themeButton?.addEventListener('click', () => applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

      function formatStatus(data) {
        if (!statusText) return;
        let value = text.autoRefresh.replace('{minutes}', String(text.interval));
        if (data && data.last_refresh_at) {
          const time = new Date(data.last_refresh_at);
          if (!Number.isNaN(time.getTime())) {
            const formatted = time.toLocaleString(text.lang === 'ar' ? 'ar-JO' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' });
            value += ' · ' + text.updated + ': ' + formatted;
          }
        }
        statusText.textContent = value;
      }

      let knownRefreshAt = null;
      async function loadStatus() {
        try {
          const response = await fetch('/api/news-status', { cache: 'no-store' });
          if (!response.ok) return;
          const status = await response.json();
          if (knownRefreshAt !== null && status.last_refresh_at && status.last_refresh_at !== knownRefreshAt) {
            window.location.reload();
            return;
          }
          if (knownRefreshAt === null && status.last_refresh_at) knownRefreshAt = status.last_refresh_at;
          else if (knownRefreshAt === null) knownRefreshAt = '';
          formatStatus(status);
        } catch (_) { /* Status display is optional; the news page stays usable. */ }
      }
      loadStatus();
      // Refresh the visible story list after a scheduled/manual background fetch completes.
      window.setInterval(loadStatus, 60000);

      refreshButton?.addEventListener('click', async () => {
        if (refreshButton.disabled) return;
        refreshButton.disabled = true;
        if (refreshButtonText) refreshButtonText.textContent = text.refreshing;
        refreshIcon?.classList.add('animate-spin');
        try {
          let baselineAt = '';
          try {
            const baselineResponse = await fetch('/api/news-status', { cache: 'no-store' });
            if (baselineResponse.ok) baselineAt = (await baselineResponse.json()).last_refresh_at || '';
          } catch (_) {}
          const response = await fetch('/api/refresh', { method: 'POST', headers: { 'Accept': 'application/json' }, cache: 'no-store' });
          const result = await response.json();
          if (result.state === 'cooldown') {
            if (refreshButtonText) refreshButtonText.textContent = text.refresh;
            if (statusText) statusText.textContent = text.cooldown;
            return;
          }
          if (result.state === 'disabled') throw new Error('automatic refresh disabled');
          for (let attempt = 0; attempt < 80; attempt++) {
            await new Promise(resolve => setTimeout(resolve, 1500));
            const statusResponse = await fetch('/api/news-status', { cache: 'no-store' });
            if (!statusResponse.ok) continue;
            const status = await statusResponse.json();
            formatStatus(status);
            const completedWithNewTimestamp = Boolean(status.last_refresh_at) && status.last_refresh_at !== baselineAt;
            if (!status.running && status.state !== 'running' && completedWithNewTimestamp) {
              if (status.state === 'error' || status.state === 'memory_only') {
                if (statusText) statusText.textContent = text.error;
                if (refreshButtonText) refreshButtonText.textContent = text.refresh;
                return;
              }
              window.location.reload();
              return;
            }
          }
          if (statusText) statusText.textContent = text.error;
        } catch (_) {
          if (statusText) statusText.textContent = text.error;
        } finally {
          refreshIcon?.classList.remove('animate-spin');
          refreshButton.disabled = false;
          if (refreshButtonText) refreshButtonText.textContent = text.refresh;
        }
      });

      const askForm = document.getElementById('articleAskForm');
      const askQuestion = document.getElementById('articleQuestion');
      const askButton = document.getElementById('articleAskButton');
      const askSpinner = document.getElementById('askSpinner');
      const askStatus = document.getElementById('articleAskStatus');
      const askAnswer = document.getElementById('articleAskAnswer');
      const askChatGPT = document.getElementById('askChatGPT');
      const askGemini = document.getElementById('askGemini');
      const articleContext = {
        slug: {{ (article.slug if article else '')|tojson }},
        lang: {{ lang|tojson }},
        title: {{ (article.title if article else '')|tojson }},
        summary: {{ (article.summary if article else '')|tojson }}
      };
      const askText = {
        required: {{ ui.question_required|tojson }},
        thinking: {{ ui.ai_thinking|tojson }},
        error: {{ ui.ai_error|tojson }},
        limit: {{ ui.ai_rate_limit|tojson }},
        disabled: {{ ui.ai_disabled|tojson }}
      };
      function externalPrompt() {
        const question = (askQuestion?.value || '').trim();
        return `${articleContext.lang === 'ar' ? 'أجب عن السؤال اعتماداً على الخبر التالي. وضح ما هو مؤكد وما هو غير متأكد، ولا تخترع معلومات.' : 'Answer the question using the following news story. Separate confirmed facts from uncertainty and do not invent information.'}\n\n${articleContext.title}\n\n${articleContext.summary}\n\n${articleContext.lang === 'ar' ? 'السؤال' : 'Question'}: ${question}`;
      }
      function updateExternalLinks() {
        const prompt = externalPrompt();
        if (askChatGPT) askChatGPT.href = 'https://chatgpt.com/?q=' + encodeURIComponent(prompt);
        if (askGemini) askGemini.href = 'https://gemini.google.com/app?q=' + encodeURIComponent(prompt);
      }
      askQuestion?.addEventListener('input', updateExternalLinks);
      updateExternalLinks();
      askForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const question = (askQuestion?.value || '').trim();
        if (!question) {
          if (askStatus) askStatus.textContent = askText.required;
          return;
        }
        if (askButton?.disabled) return;
        askButton.disabled = true;
        askSpinner?.classList.remove('hidden');
        if (askStatus) askStatus.textContent = askText.thinking;
        if (askAnswer) {
          askAnswer.classList.add('hidden');
          askAnswer.textContent = '';
        }
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 25000);
          const response = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ slug: articleContext.slug, lang: articleContext.lang, question }),
            cache: 'no-store',
            signal: controller.signal
          });
          clearTimeout(timeoutId);
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            if (response.status === 429 || data.error === 'rate_limit') throw new Error('rate_limit');
            if (response.status === 503 || data.error === 'disabled') throw new Error('disabled');
            throw new Error('upstream');
          }
          if (askAnswer) {
            askAnswer.textContent = data.answer || askText.error;
            askAnswer.classList.remove('hidden');
          }
          if (askStatus) askStatus.textContent = '';
        } catch (error) {
          if (askStatus) {
            askStatus.textContent = error.message === 'rate_limit' ? askText.limit : error.message === 'disabled' ? askText.disabled : error.name === 'AbortError' ? (articleContext.lang === 'ar' ? 'تأخر الرد. حاول مرة أخرى بعد قليل.' : 'The response timed out. Please try again.') : askText.error;
          }
        } finally {
          if (askButton) askButton.disabled = false;
          askSpinner?.classList.add('hidden');
        }
      });
    })();
  </script>
</body>
</html>
