#!/bin/zsh

cd ~/Projects/ictlab
source .venv/bin/activate
export FLASK_APP='__init__:create_app'

flask collect-news
flask classify-news

