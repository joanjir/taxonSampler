#!/bin/bash
# ================================================================
#  TaxonSampler — PythonAnywhere deployment script
#  Run this in a PythonAnywhere Bash console.
#
#  Usage:
#    First time : bash deploy_pythonanywhere.sh --init
#    Updates    : bash deploy_pythonanywhere.sh
# ================================================================
set -e

REPO="https://github.com/joanjir/taxonSampler.git"
PROJECT_DIR="$HOME/taxonSampler"
APP_DIR="$PROJECT_DIR/taxbridge"
VENV_DIR="$HOME/.virtualenvs/taxonsampler"
BRANCH="feature/visualizer"
PYTHON_VERSION="python3.10"   # PythonAnywhere free tier default

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  TaxonSampler · PythonAnywhere Deploy  ${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"

# ──────────────────────────────
#  FIRST-TIME SETUP
# ──────────────────────────────
if [ "$1" = "--init" ]; then
    echo -e "\n${YELLOW}[1/6] Cloning repository...${NC}"
    if [ -d "$PROJECT_DIR" ]; then
        echo "  Directory exists. Pulling latest..."
        cd "$PROJECT_DIR"
        git fetch origin
        git checkout "$BRANCH"
        git pull origin "$BRANCH"
    else
        git clone --branch "$BRANCH" "$REPO" "$PROJECT_DIR"
    fi

    echo -e "\n${YELLOW}[2/6] Creating virtualenv...${NC}"
    if [ ! -d "$VENV_DIR" ]; then
        mkvirtualenv taxonsampler --python=$PYTHON_VERSION
    fi
    source "$VENV_DIR/bin/activate"

    echo -e "\n${YELLOW}[3/6] Installing dependencies...${NC}"
    cd "$PROJECT_DIR"
    pip install --upgrade pip
    pip install -r requirements_pythonanywhere.txt

    echo -e "\n${YELLOW}[4/6] Setting up environment...${NC}"
    cd "$APP_DIR"
    # Generate a secret key if .env doesn't exist
    if [ ! -f ".env" ]; then
        SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
        cat > .env << EOF
DJANGO_SECRET_KEY=$SECRET
DJANGO_ENV=pythonanywhere
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=joanji.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://joanji.pythonanywhere.com
LOG_LEVEL=WARNING
NCBI_API_KEY=
EOF
        echo "  Created .env — edit it to add your NCBI_API_KEY"
    fi

    echo -e "\n${YELLOW}[5/6] Running migrations & collectstatic...${NC}"
    export DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput

    echo -e "\n${YELLOW}[6/6] Creating superuser...${NC}"
    echo "  Run: python manage.py createsuperuser"

    echo -e "\n${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}  SETUP COMPLETE!  Now configure the Web tab:${NC}"
    echo ""
    echo "  1. Go to: https://www.pythonanywhere.com/user/joanji/webapps/"
    echo ""
    echo "  2. Source code   : $APP_DIR"
    echo "     Virtualenv    : $VENV_DIR"
    echo "     Python version: 3.10"
    echo ""
    echo "  3. WSGI file — paste contents of:"
    echo "     $APP_DIR/config/pythonanywhere_wsgi.py"
    echo ""
    echo "  4. Static files mapping:"
    echo "     URL: /static/   Directory: $APP_DIR/staticfiles"
    echo ""
    echo "  5. Click 'Reload' on the Web tab."
    echo -e "${GREEN}════════════════════════════════════════${NC}"

# ──────────────────────────────
#  UPDATE (pull + migrate + collectstatic)
# ──────────────────────────────
else
    echo -e "\n${YELLOW}[1/3] Pulling latest changes...${NC}"
    cd "$PROJECT_DIR"
    git pull origin "$BRANCH"

    echo -e "\n${YELLOW}[2/3] Installing new dependencies...${NC}"
    source "$VENV_DIR/bin/activate"
    pip install -r requirements_pythonanywhere.txt

    echo -e "\n${YELLOW}[3/3] Migrations & static files...${NC}"
    cd "$APP_DIR"
    export DJANGO_SETTINGS_MODULE=config.settings.pythonanywhere
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput

    echo -e "\n${GREEN}Done! Reload the web app from the Web tab.${NC}"
fi
