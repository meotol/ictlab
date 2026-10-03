#!/bin/zsh
cd /Users/cheolhwanbae/Projects/ictlab
source .venv/bin/activate
exec flask --app __init__:create_app run

