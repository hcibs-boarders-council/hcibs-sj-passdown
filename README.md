# hcibs-sj-passdown
This project is a Carousell style webapp built with Django for boarders of HCIBS. Below are the steps on how to contribute to this project.

## Current Status

This project is still under development! Some parts of the webapp may be incomplete, messy, or subject to change.

If you're contributing (hiii Ayreen), don't worry if the current structure looks confusing at first. The guide below is meant to help you understand how everything is currently organised before you start making changes. Sorry 3am me was a bit too inspired post-promos so a lotta changes happened 🥲

## Step 1: Cloning the Project
```bash
git clone https://github.com/hcibs-boarders-council/hcibs-sj-passdown.git
cd hcibs-sj-passdown
```

## Step 2: Create & Activate the venv
**<u>Mac/Linux:</u>**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**<u>Windows:</u>**
```bash
python -m venv .venv
```
*For Command Prompt:*
```bash
.venv\Scripts\activate.bat
```
*For PowerShell:*
```bash
.venv\Scripts\Activate.ps1
```

## Step 3: Install the requirements.txt
```bash
pip install -r requirements.txt
```

### (3b) Things the app needs running
- **Python 3.13** (the pinned Django 6.1 needs Python 3.12 or newer)
- **PostgreSQL**: by default the app connects to `hcibs_sj_passdown` on `localhost:5432` as `hcibs_sj_user`. Override with `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, or set a single `DATABASE_URL=postgres://user:pass@host:5432/dbname`.
- **Redis**: live chat and notifications use Django Channels over Redis (`redis://127.0.0.1:6379/0` by default, or set `REDIS_URL`). On a Mac: `brew services start redis`, then `redis-cli ping` should say `PONG`.

## Step 4: Make sure to branch out, please don't work in main I'll cry 🙏
```bash
git checkout -b your-branch-name
```

## Step 5: Make your edits to the project!
Do whatever you want here LOLL but make sure you commit your changes once done! <br>
--> Below is also a step-by-step for how to go through the repo :P


### (5a) Django Basics
As this project is built with Django, it is integral to read through the [official documentation](https://docs.djangoproject.com/en/6.1/). But below is an overview for some basic commands to know so that you can actually run the webapp:

#### Initialize the databases:
```bash
python3 manage.py migrate
```
#### Run the webapp:
```bash
python3 manage.py runserver
```
`daphne` is listed first in `INSTALLED_APPS`, so `runserver` also serves the WebSockets used by live chat. Make sure Redis is running first.

#### Run the tests:
```bash
python3 manage.py test
```
The tests create (and then delete) a separate `test_hcibs_sj_passdown` database, so your Postgres user needs the CREATEDB permission. They use an in-memory channel layer, so Redis isn't needed for tests.

### (5b) Structure of the current repo
```text
.
├── config/                 project settings, URLs, ASGI (HTTP + WebSockets) and WSGI entry points
├── accounts/               login, register, logout, Account Details, My Posts, My Claims, Our Vision
│   └── templates/accounts/ (home.html is the Home page; its view lives in listings)
├── listings/               items, photos and claims
│   ├── models.py           Item, ItemPhoto, Claim
│   ├── forms.py            ItemForm (photo limits) and ClaimForm
│   ├── images.py           strips photo metadata and caps photo size on upload
│   ├── views.py            Home (search + filters), Post Item, item page, claim actions
│   └── templates/listings/
├── chat/                   conversations and live updates
│   ├── services.py         shared logic: sending, read state, unread counts, live events
│   ├── consumers.py        WebSocket consumers (one conversation, per-user notifications)
│   ├── views.py            chat pages + JSON endpoints used when the socket is down
│   └── templates/chat/
├── templates/
│   ├── base.html           page shell (navbar, flash messages, footer, shared scripts)
│   ├── layouts/            form_page.html (Login, Register, Post Item)
│   └── partials/           navbar, footer, item card, form field, icons, pagination…
├── static/
│   ├── css/                base.css (tokens, buttons, forms), components.css (shared UI), pages/*.css
│   ├── js/                 ui.js, nav.js, realtime.js, chat.js, home_filters.js, item_form.js, item_gallery.js
│   └── img/
├── manage.py
└── requirements.txt
```

Take note of the three main areas: global project files, the `config` project-wide configuration, and the individual Django apps (`accounts`, `listings`, `chat`). Page-specific styles go in `static/css/pages/`, anything reused goes in `components.css`, and every script is progressive enhancement: pages still work without JavaScript.

## Step 6: Commit, Push Changes & Create a Pull Request
Send your local branch up to be reviewed and merged:

```bash
git add .
git commit -m "Whatever-feature-or-description-you-added"
git push -u origin your-branch-name
```
After pushing, go to the [GitHub Repository](https://github.com/hcibs-boarders-council/hcibs-sj-passdown.git) page and click **"Compare & pull request"** to submit your changes for review!

## Notes for deployment
- Set `DJANGO_ENV=production`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DATABASE_URL` and `REDIS_URL`. The settings refuse to start in production without them.
- Serve the app with Daphne (`daphne -b 0.0.0.0 -p 8000 config.asgi:application`) behind a reverse proxy that forwards WebSocket upgrades for `/ws/` and sets `X-Forwarded-Proto`.
- Run `python manage.py collectstatic` and serve `staticfiles/` and `media/` from the proxy or a storage service.
- `python manage.py check --deploy` still flags the console email backend (`MAILERS`) and HSTS / SSL-redirect settings. Configure these for your host before going live.