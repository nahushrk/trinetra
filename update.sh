#!/bin/bash

set -e

show_help() {
    echo "Usage: $0 [version|branch]"
    echo "If no argument is specified, updates to the latest release (tag)."
    echo "If a version (tag) is specified, updates to that version."
    echo "If a branch is specified, updates to the latest commit on that branch."
    echo ""
    echo "Examples:"
    echo "  $0                # Update to latest release (tag)"
    echo "  $0 v1.2.3         # Update to specific version (tag)"
    echo "  $0 develop        # Update to latest commit on 'develop' branch"
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    show_help
    exit 0
fi

APP_DIR=~/trinetra
VENV_DIR="$APP_DIR/venv"
PYPROJECT_FILE="$APP_DIR/pyproject.toml"
REPO_URL=$(git config --get remote.origin.url)

if [ "$(pwd)" != "$APP_DIR" ]; then
    echo "Error: This script must be run from $APP_DIR"
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Python virtual environment not found at $VENV_DIR. Run install.sh first."
    exit 1
fi

if [ ! -f "$PYPROJECT_FILE" ]; then
    echo "Error: pyproject.toml not found!"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "Error: You have uncommitted changes. Please commit or stash them before updating."
    exit 1
fi

# Fetch latest tags and branches
git fetch --tags
git fetch origin

if [ -n "$1" ]; then
    ARG="$1"
    # Check if argument is a tag
    if git rev-parse "refs/tags/$ARG" >/dev/null 2>&1; then
        TARGET_TYPE="tag"
        TARGET_REF="$ARG"
    # Check if argument is a branch
    elif git rev-parse --verify "origin/$ARG" >/dev/null 2>&1; then
        TARGET_TYPE="branch"
        TARGET_REF="$ARG"
    else
        echo "Error: Neither tag nor branch named '$ARG' exists."
        exit 1
    fi
else
    # Get latest tag from GitHub releases (sorted by version, not date)
    TARGET_TYPE="tag"
    TARGET_REF=$(git tag --sort=-v:refname | head -n 1)
    if [ -z "$TARGET_REF" ]; then
        echo "Error: No tags found in repository."
        exit 1
    fi
fi

if [ "$TARGET_TYPE" == "tag" ]; then
    CURRENT_TAG=$(git describe --tags --abbrev=0)
    if [ "$CURRENT_TAG" == "$TARGET_REF" ]; then
        echo "Already on the latest version: $CURRENT_TAG"
        exit 0
    fi
    echo "Updating from $CURRENT_TAG to tag $TARGET_REF..."
    git checkout "$TARGET_REF"
elif [ "$TARGET_TYPE" == "branch" ]; then
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if [ "$CURRENT_BRANCH" == "$TARGET_REF" ]; then
        echo "Already on branch $CURRENT_BRANCH. Pulling latest changes..."
        git pull origin "$TARGET_REF"
    else
        echo "Checking out branch $TARGET_REF..."
        git checkout "$TARGET_REF"
        git pull origin "$TARGET_REF"
    fi
fi

source "$VENV_DIR/bin/activate"
echo "Installing Python requirements..."
pip install --upgrade pip
pip install .
deactivate

echo "Update complete. Now on $TARGET_TYPE $TARGET_REF."
echo "If you are running as a service, you may want to restart it:"
echo "  sudo systemctl restart trinetra" 