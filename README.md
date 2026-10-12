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

### (5b) Structure of the current repo
```text
.
├── README.md
├── accounts
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── migrations
│   │   ├── 0001_initial.py
│   │   └── __init__.py
│   ├── models.py
│   ├── templates
│   │   └── accounts
│   │       ├── home.html
│   │       ├── item_form.html
│   │       ├── login.html
│   │       └── register.html
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── config
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── db.sqlite3
├── manage.py
├── requirements.txt
├── static
│   ├── css
│   │   ├── base.css
│   │   ├── components.css
│   │   └── pages
│   │       ├── auth.css
│   │       └── home.css
│   ├── img
│   │   └── logo.jpeg
│   └── js
│       ├── item_form.js
│       └── nav.js
└── templates
    ├── base.html
    ├── layouts
    │   └── form_page.html
    └── partials
        ├── category_art.html
        ├── footer.html
        ├── icon.html
        ├── info_pills.html
        ├── item_card.html
        └── navbar.html
```

Take note of the three main areas: global project files, the `config` project-wide configuration, and individual Django apps such as the `accounts` folder.

## Step 6: Commit, Push Changes & Create a Pull Request
Send your local branch up to be reviewed and merged:

```bash
git add .
git commit -m "Whatever-feature-or-description-you-added"
git push -u origin your-branch-name
```
After pushing, go to the [GitHub Repository](https://github.com/hcibs-boarders-council/hcibs-sj-passdown.git) page and click **"Compare & pull request"** to submit your changes for review!